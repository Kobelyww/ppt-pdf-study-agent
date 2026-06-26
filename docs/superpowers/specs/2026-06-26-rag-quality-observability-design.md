# RAG Quality Evaluation And Index Observability Design

## Purpose

Phase 2 made Study Agent evidence stable by persisting document chunks and making query-time chunking an explicit fallback. The next product slice should make retrieval quality and index health measurable before the project invests more work in Graph RAG, Agentic RAG, or automatic routing thresholds.

This spec turns the current lightweight RAG evaluation prototype into a product-grade quality loop. The system should be able to answer three operational questions:

- Did this Study Agent query use healthy indexed evidence?
- Did the selected retrieval mode produce grounded, cited, reviewable output?
- Are Graph RAG Lite or Agentic RAG ready to outperform simple RAG for specific query categories?

This phase intentionally sits between persistent indexing and advanced RAG experiments. It gives later experiments a scoreboard, trace contract, and safety gates.

## Roadmap Alignment

The original product roadmap lists "RAG Quality Evaluation Loop" after persistent chunk indexing and before Graph/Agentic RAG experiment tuning. Because Phase 1 frontend workbench and Phase 2 persistent chunk index have shipped, this becomes the next implementation phase.

This spec covers P0 and P1 only:

- **P0:** safe query traces, index health observability, deterministic evaluation runner, report output, and regression tests.
- **P1:** admin/operator API polish, compact frontend diagnostics, feedback-to-trace linking, and route-readiness reports.

## Goals

- Persist safe Study Agent query trace summaries for owned debugging and quality analysis.
- Extend index observability so missing, stale, incomplete, and fallback paths are visible at query and document levels.
- Productize the existing `RAGEvaluator` and `RAGEvaluationReport` into a deterministic runner that can compare simple RAG, Graph RAG Lite, and Agentic RAG without external provider access.
- Expand the golden evaluation fixture format with query target, category, expected sources, expected terms, fixture document ids, and optional ideal-answer metadata.
- Produce JSON and Markdown evaluation reports suitable for CI artifacts, local review, and later route threshold tuning.
- Link Study Agent feedback to trace/evaluation metadata without storing raw private content in audit logs.
- Define route readiness gates for future Graph RAG and Agentic RAG experiments.

## Non-Goals

- Do not add a real embedding provider in this phase.
- Do not switch Study Agent retrieval to pgvector or a managed vector database.
- Do not tune Graph RAG or Agentic RAG routing thresholds automatically.
- Do not add a large frontend analytics dashboard.
- Do not persist raw user query text, answer content, chunk text, or source snippets in audit metadata.
- Do not run bulk historical reindexing for all existing documents.
- Do not change document parsing quality or page/slide extraction in this phase.

## Current State

The codebase already has the key foundations:

- `StudyDocumentIndexService` persists chunks, reports per-document status, loads owner-scoped persisted chunks, and detects missing, stale, and incomplete chunk sets.
- `StudyAgentRuntimeService` prefers persisted chunks and records `chunk_source` plus `fallback_reason` in result audit metadata.
- `/api/study-agent/query` returns the full Study Agent result payload to the authenticated user and persists a sanitized audit event.
- `RAGEvaluator`, `RAGEvalCase`, and `RAGEvaluationReport` can score answer term recall, source recall, latency, and token cost.
- `tests/fixtures/rag_eval_set.json` exists, but its schema is still narrow.
- Feedback, review tasks, audit events, and owner isolation already exist in the product API.

The remaining gap is not basic RAG capability. The gap is observability: there is no persistent safe trace record, no query-level index health summary, no evaluation run artifact model, and no readiness report that says when advanced retrieval modes are safe to promote.

## P0 Scope

### Safe Study Agent Trace Records

Add a persistent owner-scoped trace summary for every successful Study Agent query.

Recommended model: `StudyAgentTraceRecord`.

Required fields:

- `id`: stable trace id returned to the caller.
- `owner_id`: authenticated user id.
- `request_id`: request id if present.
- `query_hash`: deterministic hash of normalized query text.
- `target`: `answer`, `question`, or `outline_fragment`.
- `document_ids`: JSON array of requested document ids.
- `selected_mode`: `simple_rag`, `graph_rag_lite`, or `agentic_rag`.
- `route_reason`: router or preferred-mode reason.
- `estimated_cost`: selected plan cost label.
- `fallback_chain`: JSON array of planned fallback modes.
- `chunk_source`: `persisted` or `fallback`.
- `fallback_reason`: runtime fallback reason when present.
- `source_count`: number of cited source ids.
- `used_chunk_count`: number of evidence chunks used.
- `confidence`: final verification confidence.
- `source_recall`: verification source recall.
- `answer_term_recall`: verification term recall.
- `needs_review`: verifier review flag.
- `latency_ms`: measured Study Agent runtime latency.
- `created_at`: trace creation time.

Optional safe fields:

- `category`: router or evaluation category when known.
- `expected_term_count`: count only, not raw terms.
- `index_statuses`: compact JSON map of document id to index status and fallback reason.
- `error_code`: only for later failed-query support if implemented carefully.

Forbidden fields:

- raw query text
- generated answer text
- raw chunk content
- source snippets
- authorization tokens
- passwords, secrets, API keys

The trace table may store source ids or chunk source identifiers only if they are owner-scoped and do not include snippets. Audit events should still store only summary counts.

Recommended indexes:

- `(owner_id, created_at)`
- `(owner_id, request_id)`
- `(owner_id, query_hash)`
- `(owner_id, selected_mode, created_at)`
- `(needs_review, created_at)` if review workflows query traces directly

### Query Response Trace Contract

Extend the `/api/study-agent/query` response additively with a compact trace object:

```json
{
  "trace": {
    "trace_id": "trace-1",
    "request_id": "req-1",
    "selected_mode": "simple_rag",
    "route_reason": "simple factual lookup",
    "chunk_source": "persisted",
    "fallback_reason": null,
    "document_count": 1,
    "source_count": 2,
    "used_chunk_count": 3,
    "confidence": 0.82,
    "source_recall": 1.0,
    "answer_term_recall": 0.75,
    "needs_review": false,
    "latency_ms": 42
  }
}
```

The existing `request`, `plan`, `evidence`, `draft`, and `verification` response sections should remain backward compatible.

### Index Health Observability

Extend index status behavior at service level so query traces can explain evidence health.

Required status details:

- `document_id`
- `status`: `indexed`, `missing`, `stale`, or `fallback_available`
- `artifact_id`
- `chunk_count`
- `indexed_at`
- `fallback_reason`
- `expected_chunk_count` when known
- `indexed_artifact_id` when different from latest artifact
- `latest_artifact_id` when known

Add an owner-scoped summary method, for example:

```python
class StudyDocumentIndexService:
    def summary(self, *, owner_id: str) -> StudyIndexSummary: ...
```

Summary output should include counts by status and fallback reason, not raw content.

### Evaluation Fixture Schema

Expand `tests/fixtures/rag_eval_set.json` to a validated schema:

```json
{
  "id": "definition-derivative-001",
  "query": "What is a derivative?",
  "target": "answer",
  "category": "definition",
  "document_fixture_ids": ["calculus-basics"],
  "expected_sources": ["document:calculus-basics:chunk:0"],
  "expected_terms": ["rate of change"],
  "preferred_modes": ["simple_rag", "graph_rag_lite", "agentic_rag"],
  "budget": "balanced",
  "ideal_answer": "optional public fixture answer"
}
```

Required keys for P0:

- `id`
- `query`
- `target`
- `category`
- `document_fixture_ids`
- `expected_sources`
- `expected_terms`

Optional keys:

- `preferred_modes`
- `budget`
- `ideal_answer`
- `notes`

Fixtures must use public deterministic test content, not private uploaded user documents.

### Evaluation Runner

Add a service-level runner that can execute the golden suite against deterministic in-process Study Agent components.

Recommended service: `RAGQualityEvaluationService`.

Responsibilities:

- Load and validate evaluation fixtures.
- Build deterministic fixture documents/chunks for each case.
- Run each case against requested modes:
  - simple RAG
  - Graph RAG Lite
  - Agentic RAG
- Measure:
  - source recall
  - answer term recall
  - answer coverage when an ideal answer exists
  - latency
  - estimated token cost
  - needs-review rate
  - fallback rate
- Produce a structured `RAGEvaluationRun` object.
- Write JSON and Markdown reports under `docs/evaluation/` or a configured artifact directory.

The runner must not require network access, external LLM providers, real embeddings, or private user data.

### Evaluation Persistence

Add product database records for evaluation metadata.

Recommended models:

- `RAGEvaluationRunRecord`
- `RAGEvaluationCaseScoreRecord`

`RAGEvaluationRunRecord` fields:

- `id`
- `owner_id` or `created_by`
- `fixture_version`
- `modes`
- `case_count`
- `status`: `running`, `completed`, or `failed`
- `summary`
- `report_uri`
- `created_at`
- `completed_at`

`RAGEvaluationCaseScoreRecord` fields:

- `id`
- `run_id`
- `case_id`
- `mode`
- `category`
- `source_recall`
- `answer_term_recall`
- `answer_coverage`
- `latency_ms`
- `estimated_cost`
- `needs_review`
- `fallback_reason`
- `error_code`

The database records store metrics and identifiers only. Raw query text and generated answers remain in public fixture files or ephemeral reports only when the fixture is explicitly public.

Recommended indexes:

- `rag_evaluation_runs`: `(created_by, created_at)`, `(status, created_at)`
- `rag_evaluation_case_scores`: `(run_id, mode)`, `(run_id, category)`, `(mode, category)`

### Reports

JSON report requirements:

- run id
- fixture version
- mode list
- per-case scores
- per-mode summary
- per-category summary
- fallback summary
- readiness gates

Markdown report requirements:

- executive summary
- mode comparison table
- category breakdown
- failed or low-score cases
- fallback and index-health notes
- recommendation for routing readiness

Reports should default to metrics and identifiers only. They may include raw query text or generated answer excerpts only for committed public fixtures and only when the report path is clearly marked as non-user-data evaluation output.

### Route Readiness Gates

Add non-enforcing readiness gates for later Graph/Agentic RAG work.

Recommended initial gates:

- Graph RAG Lite can be marked `candidate` for a category only if:
  - average source recall is at least simple RAG source recall minus `0.05`
  - average answer term recall is at least simple RAG term recall minus `0.05`
  - needs-review rate is not higher than simple RAG by more than `10%`
  - median latency is less than or equal to `2x` simple RAG latency

- Agentic RAG can be marked `candidate` for a category only if:
  - average source recall is higher than simple RAG by at least `0.05`, or answer coverage is higher by at least `0.05`
  - needs-review rate is lower than or equal to simple RAG
  - fallback rate is below `20%`
  - estimated cost is recorded for every case

This phase should report readiness. It should not automatically change production routing behavior.

## P1 Scope

### Operator API

Add narrow authenticated APIs after the service layer is stable:

```http
GET /api/study-agent/traces/{trace_id}
GET /api/study-agent/index-summary
POST /api/admin/rag-evaluations
GET /api/admin/rag-evaluations/{run_id}
```

Rules:

- Trace reads are owner-scoped.
- Evaluation run APIs require admin access if the current auth model can express admin users.
- Responses must exclude raw query text, answer text, chunk text, and snippets.
- API errors should use existing product error patterns.

### Frontend Diagnostics

Add compact diagnostics to the existing Study Agent workbench:

- show trace id after a query completes
- show retrieval mode and route reason
- show persisted vs fallback chunk source
- show fallback warning when the query used missing, stale, or incomplete persisted chunks
- show confidence, recall, and review status in the existing result area

Do not build a separate dashboard in P1. The goal is to help users understand the current answer, not to create an analytics product.

### Feedback Linking

When users submit feedback for a Study Agent result, allow the target to reference the trace id.

Expected behavior:

- Low-rating feedback can create a review task linked to `study_agent_trace`.
- Feedback/audit metadata stores trace id, rating, reason, target type, and target id only.
- Raw answer content and raw query text are not copied into feedback metadata.

### Evaluation Report Storage

If object storage is configured, allow evaluation reports to be written through the existing `StorageBackend`. Local test runs may continue writing to `docs/evaluation/` or a temp artifact directory.

## Data Flow

### Query Trace Flow

1. Authenticated user calls `/api/study-agent/query`.
2. Runtime validates owned ready documents and loads persisted chunks.
3. Runtime records index status and fallback reason for the selected documents.
4. Orchestrator routes the query, collects evidence, generates a draft, and verifies the result.
5. API records sanitized audit metadata.
6. Trace service persists safe trace summary.
7. API returns the existing Study Agent payload plus compact `trace`.

### Evaluation Flow

1. Evaluator loads the golden fixture file.
2. Evaluator builds deterministic fixture chunks and optional graph structures.
3. Evaluator runs every selected mode for every case.
4. Evaluator scores sources, terms, coverage, latency, cost, fallback, and review flags.
5. Evaluation run and case scores are persisted.
6. JSON and Markdown reports are emitted.
7. Readiness gates mark each mode/category as `candidate`, `hold`, or `insufficient_data`.

## API And Backend Contracts

All new backend contracts should preserve existing owner isolation:

- Query traces are readable only by the trace owner.
- Index summaries are scoped to the authenticated owner unless explicitly admin-only.
- Evaluation run management is admin-only when exposed through API.
- Evaluation services can be run locally without an HTTP API.

The API should stay additive. Existing clients relying on the current Study Agent response should continue to work.

## Frontend Contract

P0 does not require frontend changes beyond TypeScript compatibility if backend payload types change.

P1 may add:

- `StudyAgentTraceSummary` type.
- `StudyIndexSummary` type.
- compact diagnostics in the existing Study Agent panel.

The frontend should not expose raw internal logs or operator-only evaluation reports to normal users.

## Audit And Privacy

Allowed audit metadata:

- `trace_id`
- `mode`
- `target`
- `needs_review`
- `source_count`
- `chunk_count`
- `document_count`
- `chunk_source`
- `fallback_reason`
- `latency_ms`

Allowed trace metadata:

- owner id
- request id
- query hash
- document ids
- mode, route reason, fallback reason
- counts, metrics, confidence, review status
- safe source identifiers when needed

Forbidden audit and trace metadata:

- raw query text
- generated answer text
- raw chunk content
- source snippets
- uploaded file content
- authorization headers
- tokens, passwords, secrets, API keys

Evaluation fixtures may contain query text only when the fixture is public and committed for deterministic tests.

## Rollout Strategy

1. Add trace and evaluation ORM models plus migrations.
2. Add trace service and wire it to `/api/study-agent/query`.
3. Extend index status summaries and runtime index-health collection.
4. Expand evaluation fixture schema and validation.
5. Productize evaluation runner and report generation.
6. Persist evaluation runs and case scores.
7. Add P1 APIs and compact frontend diagnostics only after P0 tests pass.

The rollout should keep Graph RAG and Agentic RAG routing behavior unchanged until readiness reports justify future tuning.

## Acceptance Criteria

### P0 Acceptance Criteria

- Every successful Study Agent query creates an owner-scoped trace summary.
- `/api/study-agent/query` returns a compact trace object without breaking the existing response.
- Trace persistence records query hash, mode, route reason, index health, fallback reason, metrics, and review status.
- Trace and audit metadata do not store raw query text, answer text, chunk text, source snippets, tokens, passwords, or secrets.
- Index status can explain indexed, missing, stale, incomplete, and fallback paths.
- A deterministic evaluation runner can compare simple RAG, Graph RAG Lite, and Agentic RAG without network access.
- Evaluation reports include quality, latency, cost, fallback, and needs-review metrics by mode and category.
- Evaluation run metadata and case scores can be persisted.
- Readiness gates produce candidate/hold recommendations without changing production routing.
- Focused backend tests pass.

### P1 Acceptance Criteria

- Owner-scoped trace detail API returns safe trace summaries.
- Index summary API returns counts by status and fallback reason.
- Admin evaluation APIs can start or read evaluation runs when admin auth is available.
- The frontend Study Agent panel shows compact trace diagnostics and fallback warnings.
- Feedback can be linked to a Study Agent trace without copying private content into audit metadata.
- JSON and Markdown reports can be written through configured artifact storage or local test artifacts.

## Test Plan

Required backend tests:

- `tests/test_study_agent_traces.py`
  - successful query persists trace summary.
  - trace excludes raw query, answer, chunks, snippets, and secrets.
  - trace reads are owner-scoped.
  - trace records chunk source and fallback reason.

- `tests/test_study_agent_api.py`
  - query response includes compact trace payload.
  - audit metadata remains sanitized.
  - trace detail API rejects cross-owner access.

- `tests/test_study_agent_documents.py`
  - index summary counts indexed, missing, stale, and fallback documents.
  - incomplete persisted chunk sets are visible in status and summary.

- `tests/test_rag_evaluation.py`
  - expanded fixture schema validates required fields.
  - evaluator scores source recall, answer term recall, coverage, latency, cost, fallback, and review flags.
  - fixture loader rejects private-content fields.

- `tests/test_rag_mode_comparison.py`
  - report summarizes by mode and category.
  - readiness gates produce `candidate`, `hold`, and `insufficient_data`.

- `tests/test_db_models.py` and `tests/test_db_migrations.py`
  - trace and evaluation records are ORM-compatible.
  - migrations create required indexes and constraints.

Frontend tests:

- `cd frontend && npm run build` after P1 frontend diagnostics.

Recommended final verification:

```bash
pytest tests/test_study_agent_api.py tests/test_study_agent_documents.py tests/test_rag_evaluation.py tests/test_rag_mode_comparison.py tests/test_db_models.py tests/test_db_migrations.py -q
cd frontend && npm run build
```

## Review Requirements

After each implementation task, run the project-required two reviews before moving forward:

- **Spec review:** compare the task diff against this spec and confirm no P0/P1 requirement was skipped or expanded into out-of-scope Graph RAG tuning, embeddings, pgvector, or frontend dashboard work.
- **Quality review:** inspect naming, owner isolation, privacy boundaries, trace sanitization, migration compatibility, deterministic tests, and report reproducibility.

## Next Plan

The implementation plan following this spec should be:

`docs/superpowers/plans/2026-06-26-rag-quality-observability.md`

The plan should use subagent-driven development, but keep data-model/migration edits serialized to avoid conflicting schema changes.
