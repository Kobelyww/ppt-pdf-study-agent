# Study Agent Document Evidence Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/api/study-agent/query` work against authenticated users' real processed document artifacts using query-time temporary indexing.

**Architecture:** Add a focused document-evidence layer that loads owner-scoped `normalized_document` artifacts, chunks them deterministically, and builds a temporary `RAGService` for the existing Study Agent orchestrator. Keep the API thin: authenticate, inject context, select injected orchestrator or default runtime service, map typed product errors, audit, and return the existing result shape.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLAlchemy ORM, pytest, existing `RAGService`, `EvidenceCollector`, and `StudyAgentOrchestrator`.

---

## File Structure

- Create `src/services/study_agent_documents.py`
  - Owns document evidence records, typed product errors, owner-scoped artifact loading, and deterministic chunking.
- Create `src/services/study_agent_runtime.py`
  - Owns per-request runtime assembly: evidence source, chunker, temporary `RAGService`, `EvidenceCollector`, and `StudyAgentOrchestrator`.
- Modify `src/api/app.py`
  - Accept and store an optional `study_agent_runtime_service`.
- Modify `src/api/routes/study_agent.py`
  - Select injected orchestrator first, otherwise lazily build/use `StudyAgentRuntimeService`.
  - Map `StudyAgentDocumentError` to explicit HTTP errors before generic `ValueError`.
- Modify `src/services/__init__.py`
  - Export the new service classes for tests and product wiring.
- Create `tests/test_study_agent_documents.py`
  - Unit tests for source loading, typed errors, latest artifact selection, and chunk metadata.
- Create `tests/test_study_agent_runtime.py`
  - Service integration tests for real artifact to `StudyAgentResult`.
- Modify `tests/test_study_agent_api.py`
  - API tests for default runtime behavior and product error mapping.

Each implementation task must finish with two reviews before commit:

1. Spec review: compare the task result against `docs/superpowers/specs/2026-06-24-study-agent-document-evidence-integration-design.md`.
2. Quality review: inspect naming, boundary ownership, error semantics, privacy leakage, and test coverage.

---

### Task 1: Document Evidence Source

**Files:**
- Create: `src/services/study_agent_documents.py`
- Create: `tests/test_study_agent_documents.py`

- [ ] **Step 1: Write the failing source tests**

Create `tests/test_study_agent_documents.py` with this content:

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base, Document, DocumentArtifactRecord
from src.services.study_agent_documents import (
    StudyAgentDocumentError,
    StudyDocumentEvidenceSource,
)


def _session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _insert_document(
    Session,
    *,
    document_id: str,
    owner_id: str,
    status: str = "ready",
    title: str = "Calculus Notes",
) -> None:
    now = datetime.now(timezone.utc)
    with Session() as session:
        session.add(
            Document(
                id=document_id,
                owner_id=owner_id,
                title=title,
                source_type="pdf",
                storage_uri=f"local://uploads/{document_id}.pdf",
                content_hash=f"hash-{document_id}",
                original_filename=f"{document_id}.pdf",
                status=status,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


def _insert_artifact(
    Session,
    *,
    artifact_id: str,
    document_id: str,
    content: str,
    created_at: datetime,
    artifact_type: str = "normalized_document",
) -> None:
    with Session() as session:
        session.add(
            DocumentArtifactRecord(
                id=artifact_id,
                document_id=document_id,
                artifact_type=artifact_type,
                content=content,
                artifact_metadata={"source": "test"},
                created_at=created_at,
            )
        )
        session.commit()


def test_evidence_source_loads_latest_ready_owner_artifact():
    Session = _session_factory()
    _insert_document(Session, document_id="doc-1", owner_id="user-1")
    old_time = datetime.now(timezone.utc) - timedelta(days=1)
    new_time = datetime.now(timezone.utc)
    _insert_artifact(
        Session,
        artifact_id="artifact-old",
        document_id="doc-1",
        content="Old derivative notes",
        created_at=old_time,
    )
    _insert_artifact(
        Session,
        artifact_id="artifact-new",
        document_id="doc-1",
        content="Derivatives measure instantaneous rate of change.",
        created_at=new_time,
    )

    evidence = StudyDocumentEvidenceSource(Session).load(
        owner_id="user-1",
        document_ids=("doc-1",),
    )

    assert len(evidence) == 1
    assert evidence[0].document_id == "doc-1"
    assert evidence[0].document_title == "Calculus Notes"
    assert evidence[0].owner_id == "user-1"
    assert evidence[0].artifact_id == "artifact-new"
    assert evidence[0].content == "Derivatives measure instantaneous rate of change."
    assert evidence[0].artifact_metadata == {"source": "test"}


def test_evidence_source_requires_explicit_document_ids():
    Session = _session_factory()

    with pytest.raises(StudyAgentDocumentError) as exc_info:
        StudyDocumentEvidenceSource(Session).load(owner_id="user-1", document_ids=())

    assert exc_info.value.status_code == 422
    assert exc_info.value.code == "document_scope_required"
    assert "explicit document selection" in exc_info.value.detail


def test_evidence_source_returns_non_leaking_error_for_cross_user_document():
    Session = _session_factory()
    _insert_document(Session, document_id="doc-private", owner_id="user-2")

    with pytest.raises(StudyAgentDocumentError) as exc_info:
        StudyDocumentEvidenceSource(Session).load(
            owner_id="user-1",
            document_ids=("doc-private",),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.code == "document_unavailable"
    assert exc_info.value.detail == "Selected document is unavailable to the current user."


def test_evidence_source_rejects_non_ready_owned_document():
    Session = _session_factory()
    _insert_document(
        Session,
        document_id="doc-processing",
        owner_id="user-1",
        status="processing",
    )

    with pytest.raises(StudyAgentDocumentError) as exc_info:
        StudyDocumentEvidenceSource(Session).load(
            owner_id="user-1",
            document_ids=("doc-processing",),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.code == "document_not_ready"
    assert "must finish processing" in exc_info.value.detail


def test_evidence_source_rejects_ready_document_without_normalized_artifact():
    Session = _session_factory()
    _insert_document(Session, document_id="doc-no-artifact", owner_id="user-1")

    with pytest.raises(StudyAgentDocumentError) as exc_info:
        StudyDocumentEvidenceSource(Session).load(
            owner_id="user-1",
            document_ids=("doc-no-artifact",),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.code == "document_evidence_missing"
    assert "Processed document evidence is unavailable" in exc_info.value.detail
```

- [ ] **Step 2: Run the source tests to verify they fail**

Run:

```bash
pytest tests/test_study_agent_documents.py -q
```

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'src.services.study_agent_documents'`.

- [ ] **Step 3: Implement the source and error model**

Create `src/services/study_agent_documents.py` with this content:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from src.db.models import Document, DocumentArtifactRecord


@dataclass(frozen=True)
class StudyDocumentEvidence:
    document_id: str
    document_title: str
    owner_id: str
    artifact_id: str
    artifact_type: str
    content: str
    artifact_metadata: dict[str, Any]
    created_at: datetime


class StudyAgentDocumentError(ValueError):
    def __init__(self, *, status_code: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail


class StudyDocumentEvidenceSource:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    def load(
        self,
        *,
        owner_id: str,
        document_ids: Sequence[str],
    ) -> tuple[StudyDocumentEvidence, ...]:
        normalized_owner_id = str(owner_id or "").strip()
        if not normalized_owner_id:
            raise StudyAgentDocumentError(
                status_code=422,
                code="authentication_required",
                detail="Study Agent requires an authenticated user.",
            )

        requested_ids = _dedupe_nonempty(document_ids)
        if not requested_ids:
            raise StudyAgentDocumentError(
                status_code=422,
                code="document_scope_required",
                detail="Study Agent requires explicit document selection.",
            )

        with self.session_factory() as session:
            documents = (
                session.query(Document)
                .filter(
                    Document.owner_id == normalized_owner_id,
                    Document.id.in_(requested_ids),
                )
                .all()
            )
            documents_by_id = {document.id: document for document in documents}
            if any(document_id not in documents_by_id for document_id in requested_ids):
                raise StudyAgentDocumentError(
                    status_code=404,
                    code="document_unavailable",
                    detail="Selected document is unavailable to the current user.",
                )

            evidence: list[StudyDocumentEvidence] = []
            for document_id in requested_ids:
                document = documents_by_id[document_id]
                if document.status != "ready":
                    raise StudyAgentDocumentError(
                        status_code=422,
                        code="document_not_ready",
                        detail=(
                            f"Document {document.id} must finish processing before "
                            "Study Agent can use it."
                        ),
                    )

                artifact = (
                    session.query(DocumentArtifactRecord)
                    .filter(
                        DocumentArtifactRecord.document_id == document.id,
                        DocumentArtifactRecord.artifact_type == "normalized_document",
                    )
                    .order_by(DocumentArtifactRecord.created_at.desc())
                    .first()
                )
                if artifact is None or not artifact.content.strip():
                    raise StudyAgentDocumentError(
                        status_code=422,
                        code="document_evidence_missing",
                        detail="Processed document evidence is unavailable.",
                    )

                evidence.append(
                    StudyDocumentEvidence(
                        document_id=document.id,
                        document_title=document.title,
                        owner_id=document.owner_id,
                        artifact_id=artifact.id,
                        artifact_type=artifact.artifact_type,
                        content=artifact.content,
                        artifact_metadata=dict(artifact.artifact_metadata or {}),
                        created_at=artifact.created_at,
                    )
                )

        return tuple(evidence)


def _dedupe_nonempty(values: Sequence[str]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for value in values:
        normalized = str(value).strip()
        if normalized:
            seen.setdefault(normalized, None)
    return tuple(seen)
```

- [ ] **Step 4: Run the source tests to verify they pass**

Run:

```bash
pytest tests/test_study_agent_documents.py -q
```

Expected: PASS, all source tests green.

- [ ] **Step 5: Spec review for Task 1**

Check these items manually:

- Empty `document_ids` raises a typed `422` error with explicit document selection wording.
- Cross-user or missing documents raise typed `404` without saying whether the id exists under another owner.
- Non-ready owned documents raise typed `422`.
- Ready documents without `normalized_document` raise typed `422`.
- The newest normalized artifact is selected by `created_at`.

If any item fails, fix `src/services/study_agent_documents.py` and rerun `pytest tests/test_study_agent_documents.py -q`.

- [ ] **Step 6: Quality review for Task 1**

Check these items manually:

- The source class depends on `session_factory`, not FastAPI state.
- Error messages do not include document content, query text, or another owner id.
- The source does not perform chunking or retrieval.
- The tests cover success and every required product error path from the spec.

If any item fails, fix the source or tests and rerun `pytest tests/test_study_agent_documents.py -q`.

- [ ] **Step 7: Commit Task 1**

Run:

```bash
git add src/services/study_agent_documents.py tests/test_study_agent_documents.py
git commit -m "feat: load study agent document evidence"
```

Expected: commit succeeds with only the new source module and source tests staged.

---

### Task 2: Deterministic Document Chunker

**Files:**
- Modify: `src/services/study_agent_documents.py`
- Modify: `tests/test_study_agent_documents.py`

- [ ] **Step 1: Add failing chunker tests**

Append these tests to `tests/test_study_agent_documents.py`:

```python
from src.services.study_agent_documents import StudyDocumentChunker, StudyDocumentEvidence


def test_chunker_builds_stable_chunks_with_required_metadata():
    evidence = StudyDocumentEvidence(
        document_id="doc-1",
        document_title="Calculus Notes",
        owner_id="user-1",
        artifact_id="artifact-1",
        artifact_type="normalized_document",
        content="Derivatives measure instantaneous rate of change. Gradients extend derivatives.",
        artifact_metadata={"source": "test"},
        created_at=datetime.now(timezone.utc),
    )

    chunks = StudyDocumentChunker(max_chars=36, overlap_chars=8).chunk((evidence,))

    assert len(chunks) >= 2
    assert chunks[0]["source"] == "document:doc-1:chunk:0"
    assert chunks[1]["source"] == "document:doc-1:chunk:1"
    assert chunks[0]["metadata"]["owner_id"] == "user-1"
    assert chunks[0]["metadata"]["document_id"] == "doc-1"
    assert chunks[0]["metadata"]["document_title"] == "Calculus Notes"
    assert chunks[0]["metadata"]["artifact_id"] == "artifact-1"
    assert chunks[0]["metadata"]["artifact_type"] == "normalized_document"
    assert chunks[0]["metadata"]["chunk_index"] == 0
    assert chunks[0]["metadata"]["chunk_count"] == len(chunks)
    assert chunks[0]["metadata"]["source_kind"] == "normalized_document"


def test_chunker_skips_blank_artifact_content():
    evidence = StudyDocumentEvidence(
        document_id="doc-blank",
        document_title="Blank",
        owner_id="user-1",
        artifact_id="artifact-blank",
        artifact_type="normalized_document",
        content="   \n\t   ",
        artifact_metadata={},
        created_at=datetime.now(timezone.utc),
    )

    chunks = StudyDocumentChunker(max_chars=36, overlap_chars=8).chunk((evidence,))

    assert chunks == []


def test_chunker_rejects_invalid_overlap_configuration():
    with pytest.raises(ValueError, match="overlap_chars must be smaller than max_chars"):
        StudyDocumentChunker(max_chars=10, overlap_chars=10)
```

- [ ] **Step 2: Run the chunker tests to verify they fail**

Run:

```bash
pytest tests/test_study_agent_documents.py -q
```

Expected: FAIL with `ImportError` or `AttributeError` because `StudyDocumentChunker` does not exist yet.

- [ ] **Step 3: Add the chunker implementation**

Append this code to `src/services/study_agent_documents.py`:

```python
class StudyDocumentChunker:
    def __init__(self, *, max_chars: int = 900, overlap_chars: int = 120) -> None:
        if max_chars <= 0:
            raise ValueError("max_chars must be positive")
        if overlap_chars < 0:
            raise ValueError("overlap_chars must not be negative")
        if overlap_chars >= max_chars:
            raise ValueError("overlap_chars must be smaller than max_chars")
        self.max_chars = max_chars
        self.overlap_chars = overlap_chars

    def chunk(self, evidence: Sequence[StudyDocumentEvidence]) -> list[dict[str, Any]]:
        chunks: list[dict[str, Any]] = []
        for item in evidence:
            segments = self._split_content(item.content)
            chunk_count = len(segments)
            for index, segment in enumerate(segments):
                chunks.append(
                    {
                        "content": segment,
                        "source": f"document:{item.document_id}:chunk:{index}",
                        "metadata": {
                            "owner_id": item.owner_id,
                            "document_id": item.document_id,
                            "document_title": item.document_title,
                            "artifact_id": item.artifact_id,
                            "artifact_type": item.artifact_type,
                            "chunk_index": index,
                            "chunk_count": chunk_count,
                            "source_kind": "normalized_document",
                        },
                    }
                )
        return chunks

    def _split_content(self, content: str) -> list[str]:
        normalized = " ".join(str(content).split())
        if not normalized:
            return []

        segments: list[str] = []
        start = 0
        text_length = len(normalized)
        while start < text_length:
            end = min(text_length, start + self.max_chars)
            if end < text_length:
                boundary = self._best_boundary(normalized, start, end)
                if boundary > start:
                    end = boundary

            segment = normalized[start:end].strip()
            if segment:
                segments.append(segment)

            if end >= text_length:
                break

            next_start = max(0, end - self.overlap_chars)
            if next_start <= start:
                next_start = end
            start = next_start

        return segments

    def _best_boundary(self, text: str, start: int, end: int) -> int:
        lower_bound = start + max(1, self.max_chars // 2)
        candidates = [
            text.rfind("。", start, end),
            text.rfind(".", start, end),
            text.rfind("\n", start, end),
            text.rfind(" ", start, end),
        ]
        boundary = max(candidates)
        if boundary >= lower_bound:
            return boundary + 1
        return end
```

- [ ] **Step 4: Run the chunker tests to verify they pass**

Run:

```bash
pytest tests/test_study_agent_documents.py -q
```

Expected: PASS, source and chunker tests green.

- [ ] **Step 5: Spec review for Task 2**

Check these items manually:

- Default chunking is `max_chars=900` and `overlap_chars=120`.
- Source format is exactly `document:{document_id}:chunk:{chunk_index}`.
- Metadata includes every field listed in the spec.
- Chunk boundaries are deterministic and query-independent.

If any item fails, fix `src/services/study_agent_documents.py` and rerun `pytest tests/test_study_agent_documents.py -q`.

- [ ] **Step 6: Quality review for Task 2**

Check these items manually:

- The chunker does not access the database.
- The chunker does not perform authorization.
- Blank content cannot produce empty-content chunks.
- Invalid overlap settings cannot create an infinite loop.

If any item fails, fix the implementation or tests and rerun `pytest tests/test_study_agent_documents.py -q`.

- [ ] **Step 7: Commit Task 2**

Run:

```bash
git add src/services/study_agent_documents.py tests/test_study_agent_documents.py
git commit -m "feat: chunk study agent document evidence"
```

Expected: commit succeeds with the chunker and its tests staged.

---

### Task 3: Study Agent Runtime Service

**Files:**
- Create: `src/services/study_agent_runtime.py`
- Create: `tests/test_study_agent_runtime.py`
- Modify: `src/services/__init__.py`

- [ ] **Step 1: Write failing runtime tests**

Create `tests/test_study_agent_runtime.py` with this content:

```python
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base, Document, DocumentArtifactRecord
from src.services.rag_router import RetrievalMode
from src.services.study_agent_documents import StudyAgentDocumentError, StudyDocumentChunker
from src.services.study_agent_runtime import StudyAgentRuntimeService


def _session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _insert_ready_document_with_artifact(
    Session,
    *,
    document_id: str = "doc-study",
    owner_id: str = "user-1",
    content: str = "Derivatives measure instantaneous rate of change.",
) -> None:
    now = datetime.now(timezone.utc)
    with Session() as session:
        session.add(
            Document(
                id=document_id,
                owner_id=owner_id,
                title="Calculus Notes",
                source_type="pdf",
                storage_uri=f"local://uploads/{document_id}.pdf",
                content_hash=f"hash-{document_id}",
                original_filename=f"{document_id}.pdf",
                status="ready",
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            DocumentArtifactRecord(
                id=f"artifact-{document_id}",
                document_id=document_id,
                artifact_type="normalized_document",
                content=content,
                artifact_metadata={"source": "test"},
                created_at=now,
            )
        )
        session.commit()


@pytest.mark.asyncio
async def test_runtime_runs_study_agent_against_real_document_artifact():
    Session = _session_factory()
    _insert_ready_document_with_artifact(Session)
    runtime = StudyAgentRuntimeService(
        session_factory=Session,
        chunker=StudyDocumentChunker(max_chars=200, overlap_chars=20),
    )

    result = await runtime.run(
        {
            "query": "What do derivatives measure?",
            "target": "answer",
            "document_ids": ["doc-study"],
            "expected_terms": ["rate"],
            "authenticated_user_id": "user-1",
            "request_id": "req-runtime-1",
        }
    )

    assert result.plan.mode == RetrievalMode.SIMPLE
    assert result.evidence.sources == ("document:doc-study:chunk:0",)
    assert result.evidence.chunks[0].metadata["owner_id"] == "user-1"
    assert result.evidence.chunks[0].metadata["document_id"] == "doc-study"
    assert "Derivatives measure instantaneous rate of change." in result.draft.content
    assert result.verification.needs_review is False
    assert result.audit_metadata["chunk_count"] == 1


@pytest.mark.asyncio
async def test_runtime_requires_authenticated_user_id():
    Session = _session_factory()
    runtime = StudyAgentRuntimeService(session_factory=Session)

    with pytest.raises(StudyAgentDocumentError) as exc_info:
        await runtime.run({"query": "What do derivatives measure?", "document_ids": ["doc-study"]})

    assert exc_info.value.status_code == 422
    assert exc_info.value.code == "authentication_required"


@pytest.mark.asyncio
async def test_runtime_returns_review_needed_for_retrieval_miss_against_valid_chunks():
    Session = _session_factory()
    _insert_ready_document_with_artifact(Session)
    runtime = StudyAgentRuntimeService(
        session_factory=Session,
        chunker=StudyDocumentChunker(max_chars=200, overlap_chars=20),
    )

    result = await runtime.run(
        {
            "query": "What is eigenvalue decomposition?",
            "target": "answer",
            "document_ids": ["doc-study"],
            "authenticated_user_id": "user-1",
            "request_id": "req-runtime-2",
        }
    )

    assert result.evidence.chunks == ()
    assert result.evidence.confidence == 0.0
    assert result.verification.needs_review is True
    assert "no evidence chunks used" in result.verification.issues
```

- [ ] **Step 2: Run the runtime tests to verify they fail**

Run:

```bash
pytest tests/test_study_agent_runtime.py -q
```

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'src.services.study_agent_runtime'`.

- [ ] **Step 3: Implement the runtime service**

Create `src/services/study_agent_runtime.py` with this content:

```python
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.knowledge.knowledge_graph import KnowledgeGraph
from src.services.agentic_rag import AgenticRAGPlanner
from src.services.rag_router import RAGStrategyRouter
from src.services.rag_service import RAGService
from src.services.study_agent import (
    EvidenceCollector,
    StudyAgentOrchestrator,
    StudyContentGenerator,
    StudyVerifier,
    normalize_study_request,
)
from src.services.study_agent_documents import (
    StudyAgentDocumentError,
    StudyDocumentChunker,
    StudyDocumentEvidence,
    StudyDocumentEvidenceSource,
)


class StudyAgentRuntimeService:
    def __init__(
        self,
        *,
        session_factory,
        evidence_source: StudyDocumentEvidenceSource | None = None,
        chunker: StudyDocumentChunker | None = None,
        graph: KnowledgeGraph | None = None,
        graph_factory: Callable[[tuple[StudyDocumentEvidence, ...]], KnowledgeGraph | None] | None = None,
        agentic_planner: AgenticRAGPlanner | None = None,
        generator: StudyContentGenerator | None = None,
        verifier: StudyVerifier | None = None,
        router: RAGStrategyRouter | None = None,
        top_k: int = 5,
    ) -> None:
        self.session_factory = session_factory
        self.evidence_source = evidence_source or StudyDocumentEvidenceSource(session_factory)
        self.chunker = chunker or StudyDocumentChunker()
        self.graph = graph
        self.graph_factory = graph_factory
        self.agentic_planner = agentic_planner
        self.generator = generator
        self.verifier = verifier
        self.router = router
        self.top_k = top_k

    async def run(self, payload: dict[str, Any]):
        request = normalize_study_request(payload)
        if not request.authenticated_user_id:
            raise StudyAgentDocumentError(
                status_code=422,
                code="authentication_required",
                detail="Study Agent requires an authenticated user.",
            )

        evidence = self.evidence_source.load(
            owner_id=request.authenticated_user_id,
            document_ids=request.document_ids,
        )
        chunks = self.chunker.chunk(evidence)
        if not chunks:
            raise StudyAgentDocumentError(
                status_code=422,
                code="document_evidence_missing",
                detail="Processed document evidence is unavailable.",
            )

        rag_service = RAGService()
        rag_service.index_chunks(chunks)
        collector = EvidenceCollector(
            rag_service=rag_service,
            graph=self._graph_for(evidence),
            agentic_planner=self.agentic_planner,
            top_k=self.top_k,
        )
        orchestrator = StudyAgentOrchestrator(
            evidence_collector=collector,
            generator=self.generator,
            verifier=self.verifier,
            router=self.router,
        )
        return await orchestrator.run(payload)

    def _graph_for(self, evidence: tuple[StudyDocumentEvidence, ...]) -> KnowledgeGraph | None:
        if self.graph_factory is not None:
            return self.graph_factory(evidence)
        return self.graph
```

- [ ] **Step 4: Export the new classes**

Modify `src/services/__init__.py` so it includes these imports and names:

```python
from .study_agent_documents import (
    StudyAgentDocumentError,
    StudyDocumentChunker,
    StudyDocumentEvidence,
    StudyDocumentEvidenceSource,
)
from .study_agent_runtime import StudyAgentRuntimeService
```

Add these names to `__all__`:

```python
    "StudyAgentDocumentError",
    "StudyDocumentChunker",
    "StudyDocumentEvidence",
    "StudyDocumentEvidenceSource",
    "StudyAgentRuntimeService",
```

- [ ] **Step 5: Run the runtime tests to verify they pass**

Run:

```bash
pytest tests/test_study_agent_runtime.py tests/test_study_agent_documents.py -q
```

Expected: PASS, runtime and document evidence tests green.

- [ ] **Step 6: Spec review for Task 3**

Check these items manually:

- Runtime normalizes after API context fields are present.
- Runtime requires `authenticated_user_id`.
- Runtime builds a fresh `RAGService` per request.
- Runtime reuses existing `EvidenceCollector` and `StudyAgentOrchestrator`.
- Retrieval misses against valid chunks return `needs_review=true`, not a product error.

If any item fails, fix `src/services/study_agent_runtime.py` and rerun the tests from Step 5.

- [ ] **Step 7: Quality review for Task 3**

Check these items manually:

- Runtime constructor dependencies are explicit and testable.
- No document content or query text is placed in error details.
- Runtime does not mutate app state.
- Runtime does not bypass the existing `EvidenceCollector` owner and document filters.

If any item fails, fix implementation or tests and rerun the tests from Step 5.

- [ ] **Step 8: Commit Task 3**

Run:

```bash
git add src/services/study_agent_runtime.py src/services/__init__.py tests/test_study_agent_runtime.py
git commit -m "feat: assemble study agent document runtime"
```

Expected: commit succeeds with runtime service, exports, and runtime tests staged.

---

### Task 4: API Runtime Wiring And Product Errors

**Files:**
- Modify: `src/api/app.py`
- Modify: `src/api/routes/study_agent.py`
- Modify: `tests/test_study_agent_api.py`

- [ ] **Step 1: Add failing API tests for the default runtime**

Add this import near the top of `tests/test_study_agent_api.py`:

```python
from datetime import datetime, timezone
```

Expand the existing `src.db.models` import so it includes `Document` and `DocumentArtifactRecord`:

```python
from src.db.models import AuditEventRecord, Base, Document, DocumentArtifactRecord, UserRecord
```

Append these helpers and tests to `tests/test_study_agent_api.py`:

```python
def _runtime_client():
    Session = _session_factory()
    app = create_app(
        session_factory=Session,
        secret_key="test-secret",
        allow_dev_user_header=False,
    )
    return TestClient(app), Session


def _insert_study_document(
    Session,
    *,
    document_id: str,
    owner_id: str,
    status: str = "ready",
    content: str | None = "Derivatives measure instantaneous rate of change.",
) -> None:
    now = datetime.now(timezone.utc)
    with Session() as session:
        session.add(
            Document(
                id=document_id,
                owner_id=owner_id,
                title="Calculus Notes",
                source_type="pdf",
                storage_uri=f"local://uploads/{document_id}.pdf",
                content_hash=f"hash-{document_id}",
                original_filename=f"{document_id}.pdf",
                status=status,
                created_at=now,
                updated_at=now,
            )
        )
        if content is not None:
            session.add(
                DocumentArtifactRecord(
                    id=f"artifact-{document_id}",
                    document_id=document_id,
                    artifact_type="normalized_document",
                    content=content,
                    artifact_metadata={"source": "api-test"},
                    created_at=now,
                )
            )
        session.commit()


def test_study_agent_query_uses_default_runtime_when_orchestrator_is_not_injected():
    client, Session = _runtime_client()
    _insert_study_document(Session, document_id="doc-study", owner_id="user-1")
    headers = _login(client)

    response = client.post(
        "/api/study-agent/query",
        json={
            "query": "What do derivatives measure?",
            "target": "answer",
            "document_ids": ["doc-study"],
            "expected_terms": ["rate"],
        },
        headers={**headers, "x-request-id": "req-study-runtime"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["evidence"]["sources"] == ["document:doc-study:chunk:0"]
    assert payload["evidence"]["chunks"][0]["metadata"]["owner_id"] == "user-1"
    assert payload["evidence"]["chunks"][0]["metadata"]["document_id"] == "doc-study"
    assert payload["verification"]["needs_review"] is False


def test_study_agent_default_runtime_requires_document_ids():
    client, _Session = _runtime_client()
    headers = _login(client)

    response = client.post(
        "/api/study-agent/query",
        json={"query": "What do derivatives measure?"},
        headers=headers,
    )

    assert response.status_code == 422
    assert "explicit document selection" in response.json()["detail"]


def test_study_agent_default_runtime_hides_cross_user_document():
    client, Session = _runtime_client()
    _insert_study_document(Session, document_id="doc-private", owner_id="user-2")
    headers = _login(client)

    response = client.post(
        "/api/study-agent/query",
        json={
            "query": "What do derivatives measure?",
            "document_ids": ["doc-private"],
        },
        headers=headers,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Selected document is unavailable to the current user."


def test_study_agent_default_runtime_rejects_non_ready_document():
    client, Session = _runtime_client()
    _insert_study_document(
        Session,
        document_id="doc-processing",
        owner_id="user-1",
        status="processing",
    )
    headers = _login(client)

    response = client.post(
        "/api/study-agent/query",
        json={
            "query": "What do derivatives measure?",
            "document_ids": ["doc-processing"],
        },
        headers=headers,
    )

    assert response.status_code == 422
    assert "must finish processing" in response.json()["detail"]


def test_study_agent_default_runtime_rejects_ready_document_without_artifact():
    client, Session = _runtime_client()
    _insert_study_document(
        Session,
        document_id="doc-no-artifact",
        owner_id="user-1",
        content=None,
    )
    headers = _login(client)

    response = client.post(
        "/api/study-agent/query",
        json={
            "query": "What do derivatives measure?",
            "document_ids": ["doc-no-artifact"],
        },
        headers=headers,
    )

    assert response.status_code == 422
    assert "Processed document evidence is unavailable" in response.json()["detail"]
```

- [ ] **Step 2: Run the new API tests to verify they fail**

Run:

```bash
pytest tests/test_study_agent_api.py::test_study_agent_query_uses_default_runtime_when_orchestrator_is_not_injected tests/test_study_agent_api.py::test_study_agent_default_runtime_requires_document_ids tests/test_study_agent_api.py::test_study_agent_default_runtime_hides_cross_user_document tests/test_study_agent_api.py::test_study_agent_default_runtime_rejects_non_ready_document tests/test_study_agent_api.py::test_study_agent_default_runtime_rejects_ready_document_without_artifact -q
```

Expected: FAIL because the route still returns `503` when no orchestrator is injected.

- [ ] **Step 3: Add runtime service support to app state**

Modify the `create_app` signature in `src/api/app.py` by adding this keyword argument after `study_agent_orchestrator`:

```python
    study_agent_runtime_service: Any | None = None,
```

Set the app state after the current `study_agent_orchestrator` assignment:

```python
    app.state.study_agent_orchestrator = study_agent_orchestrator
    app.state.study_agent_runtime_service = study_agent_runtime_service
```

- [ ] **Step 4: Wire route runtime selection and typed error mapping**

Modify `src/api/routes/study_agent.py` imports:

```python
from src.services.study_agent_documents import StudyAgentDocumentError
from src.services.study_agent_runtime import StudyAgentRuntimeService
```

Replace the start of `query_study_agent` with this runtime selection and error mapping:

```python
@router.post("/query")
async def query_study_agent(
    payload: StudyAgentQueryRequest,
    request: Request,
) -> dict[str, Any]:
    context = get_user_context(request)
    runner = _study_agent_runner(request)
    if runner is None:
        raise HTTPException(status_code=503, detail="Study agent is not configured")
    payload_data = payload.model_dump(exclude_none=True)
    payload_data["authenticated_user_id"] = context.user_id
    payload_data["request_id"] = context.request_id
    try:
        result = await runner.run(payload_data)
    except StudyAgentDocumentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _record_study_agent_audit(
        request,
        actor_id=context.user_id,
        request_id=context.request_id,
        result=result,
        payload=payload_data,
    )
    return _to_jsonable(result)
```

Add this helper below the route:

```python
def _study_agent_runner(request: Request) -> Any | None:
    orchestrator = getattr(request.app.state, "study_agent_orchestrator", None)
    if orchestrator is not None:
        return orchestrator

    runtime = getattr(request.app.state, "study_agent_runtime_service", None)
    if runtime is not None:
        return runtime

    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        return None

    runtime = StudyAgentRuntimeService(session_factory=session_factory)
    request.app.state.study_agent_runtime_service = runtime
    return runtime
```

- [ ] **Step 5: Run the API tests to verify they pass**

Run:

```bash
pytest tests/test_study_agent_api.py -q
```

Expected: PASS, including existing injected orchestrator tests and the new default runtime tests.

- [ ] **Step 6: Spec review for Task 4**

Check these items manually:

- Injected orchestrator still takes precedence.
- Default runtime is used when no orchestrator is injected and `session_factory` exists.
- Missing runtime prerequisites still return `503`.
- `StudyAgentDocumentError` maps to its own status code and detail.
- Cross-user document requests return `404` without ownership leakage.

If any item fails, fix `src/api/app.py`, `src/api/routes/study_agent.py`, or tests, then rerun `pytest tests/test_study_agent_api.py -q`.

- [ ] **Step 7: Quality review for Task 4**

Check these items manually:

- The route remains thin and does not query the database directly.
- Identity fields from request JSON are still ignored by `StudyAgentQueryRequest`.
- Audit metadata remains sanitized and does not include query text or chunk content.
- Lazy runtime creation does not replace an explicitly injected runtime service.

If any item fails, fix route/app wiring and rerun `pytest tests/test_study_agent_api.py -q`.

- [ ] **Step 8: Commit Task 4**

Run:

```bash
git add src/api/app.py src/api/routes/study_agent.py tests/test_study_agent_api.py
git commit -m "feat: wire study agent document runtime api"
```

Expected: commit succeeds with only API wiring and API tests staged.

---

### Task 5: Full Verification And Documentation Sync

**Files:**
- Modify: `README.md`
- Modify: `SPEC.md`

- [ ] **Step 1: Update product documentation**

In `README.md`, add a short note under the Study Agent/API section that states:

```markdown
Study Agent queries now require explicit `document_ids` and use the authenticated user's processed `normalized_document` artifacts as evidence. The first production path builds a temporary in-memory index per request; persistent chunk/vector indexing remains a future scaling step.
```

In `SPEC.md`, add the same product requirement to the Study Agent section:

```markdown
- Study Agent document evidence: `/api/study-agent/query` requires explicit `document_ids`; the default runtime loads only the authenticated user's ready documents with `normalized_document` artifacts, chunks them at query time, and returns grounded results with citations and review metadata.
```

- [ ] **Step 2: Run focused tests**

Run:

```bash
pytest tests/test_study_agent_documents.py tests/test_study_agent_runtime.py tests/test_study_agent_api.py tests/test_study_agent_evidence.py tests/test_study_agent_orchestrator.py -q
```

Expected: PASS.

- [ ] **Step 3: Run full backend tests**

Run:

```bash
pytest -q
```

Expected: PASS with the repository's existing xfail count unchanged.

- [ ] **Step 4: Run frontend build**

Run:

```bash
npm run build
```

Expected: PASS. If the repository has no frontend package in this worktree, record the exact command output in the final implementation report.

- [ ] **Step 5: Run Docker Compose config validation**

Run:

```bash
docker compose config
```

Expected: PASS and prints the resolved Compose configuration.

- [ ] **Step 6: Final spec review**

Check each acceptance criterion in `docs/superpowers/specs/2026-06-24-study-agent-document-evidence-integration-design.md` against current tests and code:

- Ready document plus normalized artifact returns grounded result with `document:{document_id}:chunk:{index}` sources.
- Chunk metadata includes owner, document, artifact, and chunk fields.
- Missing `document_ids` returns `422`.
- Cross-user document returns `404`.
- Non-ready document returns `422`.
- Missing normalized artifact returns `422`.
- Retrieval miss from valid chunks returns `needs_review=true`.
- API default runtime works without injected orchestrator.
- Injected orchestrator remains supported.

If any item lacks code or test evidence, add the missing focused test and implementation before continuing.

- [ ] **Step 7: Final quality review**

Review the diff manually:

```bash
git diff --stat
git diff -- src/services/study_agent_documents.py src/services/study_agent_runtime.py src/api/routes/study_agent.py src/api/app.py
```

Confirm:

- New modules are focused and do not duplicate `StudyAgentOrchestrator` behavior.
- Product errors are typed, not parsed from strings.
- No audit path includes document content, query text, or chunk text.
- Tests use owner-scoped data and prove no cross-user evidence leakage.
- There are no unrelated refactors.

If any item fails, fix it and rerun focused tests from Step 2.

- [ ] **Step 8: Commit Task 5**

Run:

```bash
git add README.md SPEC.md
git commit -m "docs: document study agent real evidence path"
```

Expected: commit succeeds with only documentation updates staged.

---

## Completion Criteria

The implementation is complete only when all of these are true:

- Every task checkbox is complete.
- Each task has passed both the spec review and quality review.
- `pytest tests/test_study_agent_documents.py tests/test_study_agent_runtime.py tests/test_study_agent_api.py tests/test_study_agent_evidence.py tests/test_study_agent_orchestrator.py -q` passes.
- `pytest -q` passes with only the repository's existing xfail count.
- `npm run build` passes or the repository clearly lacks a frontend build target and that output is recorded.
- `docker compose config` passes.
- The working tree contains only intended implementation changes before final landing.
