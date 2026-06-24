from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base, Document, DocumentArtifactRecord
from src.services.study_agent_documents import (
    StudyAgentDocumentError,
    StudyDocumentChunker,
    StudyDocumentEvidence,
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
