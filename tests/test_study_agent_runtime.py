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
