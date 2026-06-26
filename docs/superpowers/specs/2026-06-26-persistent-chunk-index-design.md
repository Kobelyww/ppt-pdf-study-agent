# Persistent Chunk Index Design

## Purpose

Phase 1 made the Study Agent usable from the frontend. Phase 2 turns the current query-time document chunking path into a persistent product index so Study Agent answers, future Graph RAG experiments, and RAG quality evaluation can all refer to stable evidence units.

The current runtime loads the authenticated user's ready `normalized_document` artifacts and chunks them on every `/api/study-agent/query` request. That is acceptable for proving the product loop, but it does not scale, is hard to observe, and gives later retrieval experiments unstable chunk identities. This spec defines the next P0/P1 slice: persist chunks during document processing, prefer persisted chunks at query time, and keep the temporary chunking path only as an explicit transition fallback.

## Goals

- Persist document chunks when a ready document has a usable `normalized_document` artifact.
- Give every chunk stable product fields for owner isolation, source traceability, reindexing, and later evaluation.
- Make Study Agent runtime prefer persisted chunks without breaking the current temporary-index fallback.
- Expose index status so operators and later frontend work can tell whether a document is indexed, missing chunks, stale, or using fallback indexing.
- Provide a narrow owned-document reindex path for recovery and local product operations.
- Preserve existing authentication, owner isolation, audit hygiene, and deterministic testability.

## Non-Goals

- Do not introduce a real embedding provider in this phase.
- Do not require pgvector similarity search for Study Agent retrieval in this phase.
- Do not tune Graph RAG or Agentic RAG routing thresholds.
- Do not change document parsing quality or page/slide metadata extraction beyond carrying existing metadata through the chunk records.
- Do not implement bulk background reindexing for every historical document.
- Do not add a large new frontend workflow; backend status fields may be surfaced later.

## Current State

The codebase already has:

- `DocumentArtifactRecord` for `normalized_document` artifacts.
- `StudyDocumentEvidenceSource` for owner-scoped artifact loading.
- `StudyDocumentChunker` for deterministic query-time chunks.
- `StudyAgentRuntimeService` that chunks artifacts, indexes chunks into an in-memory `RAGService`, and runs the orchestrator.
- A historical migration that creates a basic `document_chunks` table for earlier product schema work.

The important design implication is that Phase 2 should reconcile the existing table/migration history with the current ORM and Study Agent runtime instead of assuming the database is a blank slate. If the existing `document_chunks` schema lacks product fields, use an additive migration and ORM model update rather than replacing the table destructively.

## Data Model

Add or reconcile an ORM record named `DocumentChunkRecord` for `document_chunks`.

Required logical fields:

- `id`: stable chunk record id.
- `owner_id`: authenticated owner id copied from the document.
- `document_id`: owning document id.
- `artifact_id`: source `normalized_document` artifact id.
- `chunk_index`: zero-based index within the artifact.
- `chunk_count`: total chunks generated for the artifact.
- `source`: stable source string, such as `document:{document_id}:chunk:{chunk_index}`.
- `content`: chunk text.
- `metadata`: JSON metadata used by frontend citations and retrieval.
- `content_hash`: deterministic hash of chunk content plus source-defining metadata.
- `created_at`: creation timestamp.
- `updated_at`: update timestamp if the local schema convention supports it.

Existing-compatible optional fields:

- `section_id`
- `page_number`
- `embedding`

Recommended constraints and indexes:

- Index `(owner_id, document_id)`.
- Index `(document_id, artifact_id)`.
- Unique constraint on `(artifact_id, chunk_index)`.
- Optional unique constraint on `(artifact_id, content_hash)` only if it does not conflict with overlapping chunks.

The migration should be additive for existing databases. If `document_chunks` already exists, add missing columns and indexes. If it does not exist in a test database, create the full table.

## Chunk Source Contract

Persisted chunks should retain the same logical contract used by current query-time chunks:

```python
{
    "content": chunk.content,
    "source": chunk.source,
    "metadata": {
        "owner_id": owner_id,
        "document_id": document_id,
        "document_title": document.title,
        "artifact_id": artifact.id,
        "artifact_type": "normalized_document",
        "chunk_index": index,
        "chunk_count": count,
        "source_kind": "persisted_document_chunk",
    },
}
```

When existing parsing metadata is available on the artifact or future normalizer output, carry it through without inventing page or slide values:

- `page_number`
- `slide_number`
- `section_title`
- `heading`
- `block_type`
- `position`

If metadata is unavailable, the persisted chunk is still valid as long as owner, document, artifact, chunk index, and title metadata are present.

## Services

### Study Document Index Service

Add `StudyDocumentIndexService` or an equivalent focused service.

Responsibilities:

- Load an owned ready document and its latest non-empty `normalized_document` artifact.
- Use `StudyDocumentChunker` or a shared chunk conversion path to produce deterministic chunks.
- Persist chunks in a transaction.
- Make reindex idempotent for the current artifact.
- Delete or replace stale chunks for older artifacts when the latest artifact changes.
- Return an index status summary.

Suggested methods:

```python
class StudyDocumentIndexService:
    def index_document(self, *, owner_id: str, document_id: str) -> DocumentIndexStatus: ...
    def index_artifact(self, *, owner_id: str, document_id: str, artifact_id: str) -> DocumentIndexStatus: ...
    def status(self, *, owner_id: str, document_id: str) -> DocumentIndexStatus: ...
    def load_chunks(self, *, owner_id: str, document_ids: Sequence[str]) -> tuple[dict, ...]: ...
```

`DocumentIndexStatus` should include:

- `document_id`
- `status`: `indexed`, `missing`, `stale`, or `fallback_available`
- `artifact_id`
- `chunk_count`
- `indexed_at`
- `fallback_reason`

### Study Agent Runtime

Update `StudyAgentRuntimeService`:

1. Normalize and validate request as it does today.
2. Enforce authenticated user and explicit document ids.
3. Attempt to load persisted chunks for the requested owned ready documents.
4. If persisted chunks are available for all requested documents, index those chunks into `RAGService`.
5. If persisted chunks are missing but `normalized_document` artifacts exist, use the current query-time chunking path and mark a fallback reason.
6. If neither persisted chunks nor usable artifacts exist, return the existing product error for missing evidence.

The runtime should not silently mix owner scopes. Persisted chunk loading must filter by both owner id and requested document ids.

### Worker Integration

When the document processing worker creates a `normalized_document` artifact:

1. Persist the artifact as it does today.
2. Run the index service for the document/artifact in the same product flow.
3. If indexing fails, surface the failure through job error handling or a review signal rather than marking the evidence path as healthy.
4. Keep outline and question generation behavior intact.

The worker should not require external model or vector services for indexing.

## API Surface

Add a narrow owned-document reindex route under the existing document API surface.

Recommended endpoint:

```http
POST /api/documents/{document_id}/study-index/reindex
```

Response:

```json
{
  "document_id": "doc-1",
  "status": "indexed",
  "artifact_id": "artifact-1",
  "chunk_count": 12,
  "indexed_at": "2026-06-26T00:00:00Z",
  "fallback_reason": null
}
```

Error behavior:

- `401`: unauthenticated.
- `404`: document is unavailable to the authenticated user.
- `422`: document is not ready.
- `422`: normalized document artifact is missing or empty.
- `500`: unexpected indexing failure with internal details hidden from the user.

If document list or document detail APIs are already the right place to expose status, add a compact `study_index` field there. Otherwise, provide a service-level status method and defer frontend display to a later phase.

## Audit And Privacy

Indexing and reindexing may write audit events, but audit metadata must remain sanitized.

Allowed audit metadata:

- `document_id`
- `artifact_id`
- `chunk_count`
- `index_status`
- `fallback_used`

Forbidden audit metadata:

- raw chunk content
- query text
- source snippets
- authorization tokens
- passwords or secrets

## Rollout Strategy

1. Add model and migration compatibility first.
2. Add index service and tests.
3. Integrate worker indexing.
4. Update runtime to prefer persisted chunks with fallback.
5. Add reindex API or service route.
6. Run focused Study Agent and worker tests.

The fallback path should remain during Phase 2 so existing fixtures and migration edge cases do not block product use. Later phases can remove fallback only after persisted indexing has enough coverage and operational visibility.

## Acceptance Criteria

- Document processing creates persisted chunks for each ready document with a non-empty `normalized_document` artifact.
- Study Agent answers can use persisted chunks without re-chunking artifacts on every request.
- Runtime fallback to query-time chunking remains intentional and observable.
- Owner and document scope are enforced for persisted chunk reads and reindex operations.
- Reindexing the same artifact does not create duplicate chunks.
- Reprocessing a document with a newer artifact marks older chunks stale or replaces them deterministically.
- Owned ready documents can be reindexed through the service or API.
- Non-ready documents and documents without usable artifacts return product errors.
- Existing upload, processing, Study Agent query, frontend build, and focused backend tests remain green.

## Test Plan

Required focused tests:

- `tests/test_study_agent_documents.py`
  - persisted chunk records include required metadata.
  - index status returns `indexed`, `missing`, and `stale`.
  - fallback source remains available when persisted chunks are absent.

- `tests/test_study_agent_runtime.py`
  - runtime prefers persisted chunks.
  - runtime falls back to artifact chunking when persisted chunks are missing.
  - runtime rejects cross-owner persisted chunk access.

- `tests/test_workers_product_flow.py`
  - worker creates normalized artifact and persisted chunks.
  - reprocessing does not duplicate active chunks.

- API route tests if a reindex endpoint is added:
  - owner can reindex own ready document.
  - cross-owner document is unavailable.
  - processing document cannot be reindexed.
  - document without artifact returns missing evidence error.

Verification commands:

```bash
pytest tests/test_study_agent_documents.py tests/test_study_agent_runtime.py tests/test_workers_product_flow.py -q
pytest tests/test_study_agent_api.py -q
cd frontend && npm run build
```

## Risks

- The existing migration already defines a `document_chunks` table that does not fully match the desired product schema. The implementation must reconcile this carefully with additive migrations and ORM tests.
- If persisted chunk metadata is too sparse, frontend citations will still be less helpful until Phase 3 document parsing quality work.
- If fallback is too quiet, the product may appear indexed while still doing query-time work. Status and audit metadata must make fallback explicit.
- If worker indexing is coupled too tightly to outline/question generation, a chunking bug could block unrelated generated content. Keep indexing failure handling explicit.

## Phase 2 API Decision

Phase 2 will implement both backend observability surfaces:

- Add `POST /api/documents/{document_id}/study-index/reindex` for owned ready-document reindexing.
- Add a compact `study_index` field to document API responses where documents are already serialized.

The `study_index` field should include `status`, `chunk_count`, `artifact_id`, `indexed_at`, and `fallback_reason`. The frontend may display this later, but a full frontend index-status panel is not part of Phase 2.
