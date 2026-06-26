from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base, Document, DocumentArtifactRecord, DocumentChunkRecord
from src.services.rag_router import RetrievalMode
from src.services.study_agent_documents import StudyAgentDocumentError, StudyDocumentChunker
from src.services.study_agent_index import StudyDocumentIndexService
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


def _insert_persisted_chunk(
    Session,
    *,
    document_id: str = "doc-study",
    owner_id: str = "user-1",
    artifact_id: str = "artifact-doc-study",
    content: str = "Persisted derivatives evidence.",
) -> None:
    with Session() as session:
        session.add(
            DocumentChunkRecord(
                id=f"chunk-{document_id}",
                owner_id=owner_id,
                document_id=document_id,
                artifact_id=artifact_id,
                chunk_index=0,
                chunk_count=1,
                source=f"document:{document_id}:chunk:0",
                content=content,
                chunk_metadata={
                    "owner_id": owner_id,
                    "document_id": document_id,
                    "document_title": "Calculus Notes",
                    "artifact_id": artifact_id,
                    "artifact_type": "normalized_document",
                    "chunk_index": 0,
                    "chunk_count": 1,
                    "source_kind": "persisted_document_chunk",
                },
                content_hash=f"hash-{document_id}",
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
async def test_runtime_prefers_persisted_chunks_over_query_time_chunking():
    Session = _session_factory()
    _insert_ready_document_with_artifact(
        Session,
        content="Artifact text that should not appear when persisted chunks exist.",
    )
    _insert_persisted_chunk(Session)
    runtime = StudyAgentRuntimeService(
        session_factory=Session,
        chunker=StudyDocumentChunker(max_chars=200, overlap_chars=20),
    )

    result = await runtime.run(
        {
            "query": "What do derivatives measure?",
            "target": "answer",
            "document_ids": ["doc-study"],
            "authenticated_user_id": "user-1",
            "request_id": "req-runtime-persisted",
        }
    )

    assert result.evidence.sources == ("document:doc-study:chunk:0",)
    assert result.evidence.chunks[0].content == "Persisted derivatives evidence."
    assert result.evidence.chunks[0].metadata["source_kind"] == "persisted_document_chunk"
    assert result.audit_metadata["chunk_source"] == "persisted"
    assert result.audit_metadata["fallback_reason"] is None
    assert result.audit_metadata["index_statuses"]["doc-study"]["status"] == "indexed"
    assert result.audit_metadata["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_runtime_fallback_to_artifact_chunking_is_observable():
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
            "authenticated_user_id": "user-1",
            "request_id": "req-runtime-fallback",
        }
    )

    assert result.evidence.chunks[0].metadata["source_kind"] == "normalized_document"
    assert result.audit_metadata["chunk_source"] == "fallback"
    assert result.audit_metadata["fallback_reason"] == "persisted_chunks_missing"
    assert (
        result.audit_metadata["index_statuses"]["doc-study"]["status"]
        == "fallback_available"
    )


@pytest.mark.asyncio
async def test_runtime_applies_route_policy_and_keeps_policy_safe():
    Session = _session_factory()
    _insert_ready_document_with_artifact(
        Session,
        content="Derivatives and integrals are connected by the fundamental theorem.",
    )
    runtime = StudyAgentRuntimeService(
        session_factory=Session,
        chunker=StudyDocumentChunker(max_chars=200, overlap_chars=20),
    )

    result = await runtime.run(
        {
            "query": "导数和积分的关系是什么？",
            "target": "answer",
            "document_ids": ["doc-study"],
            "authenticated_user_id": "user-1",
            "request_id": "req-runtime-policy",
        }
    )

    assert result.plan.mode == RetrievalMode.SIMPLE
    policy = result.audit_metadata["policy"]
    assert policy["status"] == "blocked_by_flag"
    assert policy["router_mode"] == "graph_rag_lite"
    assert policy["selected_mode"] == "simple_rag"
    serialized_policy = str(policy).lower()
    assert "导数" not in serialized_policy
    assert "积分" not in serialized_policy
    assert "关系" not in serialized_policy


@pytest.mark.asyncio
async def test_runtime_falls_back_when_persisted_chunk_set_is_incomplete():
    Session = _session_factory()
    _insert_ready_document_with_artifact(
        Session,
        content=(
            "Derivatives measure instantaneous rate of change. "
            "Gradients extend derivatives to several variables. "
            "Integrals accumulate signed area over intervals."
        ),
    )
    chunker = StudyDocumentChunker(max_chars=48, overlap_chars=8)
    index_service = StudyDocumentIndexService(session_factory=Session, chunker=chunker)
    indexed = index_service.index_document(owner_id="user-1", document_id="doc-study")
    assert indexed.chunk_count >= 2
    with Session() as session:
        row = (
            session.query(DocumentChunkRecord)
            .filter(DocumentChunkRecord.document_id == "doc-study")
            .order_by(DocumentChunkRecord.chunk_index.desc())
            .first()
        )
        session.delete(row)
        session.commit()
    runtime = StudyAgentRuntimeService(
        session_factory=Session,
        chunker=chunker,
        index_service=index_service,
    )

    result = await runtime.run(
        {
            "query": "What do derivatives measure?",
            "target": "answer",
            "document_ids": ["doc-study"],
            "authenticated_user_id": "user-1",
            "request_id": "req-runtime-incomplete-persisted",
        }
    )

    assert result.audit_metadata["chunk_source"] == "fallback"
    assert result.audit_metadata["fallback_reason"] == "persisted_chunks_incomplete"
    assert result.evidence.chunks[0].metadata["source_kind"] == "normalized_document"


@pytest.mark.asyncio
async def test_runtime_falls_back_when_any_requested_document_lacks_persisted_chunks():
    Session = _session_factory()
    _insert_ready_document_with_artifact(Session, document_id="doc-study")
    _insert_ready_document_with_artifact(
        Session,
        document_id="doc-second",
        content="Integrals accumulate signed area.",
    )
    _insert_persisted_chunk(Session, document_id="doc-study")
    runtime = StudyAgentRuntimeService(
        session_factory=Session,
        chunker=StudyDocumentChunker(max_chars=200, overlap_chars=20),
    )

    result = await runtime.run(
        {
            "query": "What do derivatives measure?",
            "target": "answer",
            "document_ids": ["doc-study", "doc-second"],
            "authenticated_user_id": "user-1",
            "request_id": "req-runtime-partial-fallback",
        }
    )

    assert result.audit_metadata["chunk_source"] == "fallback"
    assert result.audit_metadata["fallback_reason"] == "persisted_chunks_incomplete"


@pytest.mark.asyncio
async def test_runtime_falls_back_when_persisted_chunks_are_stale():
    Session = _session_factory()
    _insert_ready_document_with_artifact(Session)
    _insert_persisted_chunk(Session, artifact_id="artifact-old")
    runtime = StudyAgentRuntimeService(
        session_factory=Session,
        chunker=StudyDocumentChunker(max_chars=200, overlap_chars=20),
    )

    result = await runtime.run(
        {
            "query": "What do derivatives measure?",
            "target": "answer",
            "document_ids": ["doc-study"],
            "authenticated_user_id": "user-1",
            "request_id": "req-runtime-stale-fallback",
        }
    )

    assert result.evidence.chunks[0].metadata["source_kind"] == "normalized_document"
    assert result.audit_metadata["chunk_source"] == "fallback"
    assert result.audit_metadata["fallback_reason"] == "persisted_chunks_stale"


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
