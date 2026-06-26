from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base, Document, DocumentArtifactRecord, DocumentChunkRecord
from src.services.study_agent_index import DocumentIndexStatus, StudyDocumentIndexService
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


def _add_ready_document_with_artifact(
    Session,
    *,
    document_id: str,
    owner_id: str,
    artifact_id: str,
    content: str,
) -> None:
    _insert_document(Session, document_id=document_id, owner_id=owner_id)
    _insert_artifact(
        Session,
        artifact_id=artifact_id,
        document_id=document_id,
        content=content,
        created_at=datetime.now(timezone.utc),
    )


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


def test_index_service_persists_chunks_with_required_metadata():
    Session = _session_factory()
    _insert_document(Session, document_id="doc-1", owner_id="user-1")
    _insert_artifact(
        Session,
        artifact_id="artifact-1",
        document_id="doc-1",
        content="Derivatives measure instantaneous rate of change. Gradients extend derivatives.",
        created_at=datetime.now(timezone.utc),
    )
    service = StudyDocumentIndexService(
        session_factory=Session,
        chunker=StudyDocumentChunker(max_chars=48, overlap_chars=8),
    )

    status = service.index_document(owner_id="user-1", document_id="doc-1")

    assert status.document_id == "doc-1"
    assert status.status == "indexed"
    assert status.artifact_id == "artifact-1"
    assert status.chunk_count >= 2
    assert status.indexed_at is not None
    assert status.fallback_reason is None
    payload = status.to_dict()
    assert payload["expected_chunk_count"] == status.chunk_count
    assert payload["latest_artifact_id"] == status.artifact_id
    assert payload["indexed_artifact_id"] == status.artifact_id
    with Session() as session:
        chunks = (
            session.query(DocumentChunkRecord)
            .filter(DocumentChunkRecord.document_id == "doc-1")
            .order_by(DocumentChunkRecord.chunk_index)
            .all()
        )
    assert len(chunks) == status.chunk_count
    assert chunks[0].owner_id == "user-1"
    assert chunks[0].artifact_id == "artifact-1"
    assert chunks[0].source == "document:doc-1:chunk:0"
    assert len(chunks[0].id) <= 64
    assert chunks[0].chunk_metadata["source_kind"] == "persisted_document_chunk"
    assert chunks[0].chunk_metadata["document_title"] == "Calculus Notes"
    assert chunks[0].content_hash != chunks[0].content


def test_index_service_reindex_is_idempotent_for_same_artifact():
    Session = _session_factory()
    _insert_document(Session, document_id="doc-1", owner_id="user-1")
    _insert_artifact(
        Session,
        artifact_id="artifact-1",
        document_id="doc-1",
        content="Derivatives measure instantaneous rate of change.",
        created_at=datetime.now(timezone.utc),
    )
    service = StudyDocumentIndexService(session_factory=Session)

    first = service.index_document(owner_id="user-1", document_id="doc-1")
    second = service.index_document(owner_id="user-1", document_id="doc-1")

    assert first.status == "indexed"
    assert second.status == "indexed"
    with Session() as session:
        assert session.query(DocumentChunkRecord).count() == first.chunk_count


def test_index_service_reindex_new_artifact_replaces_stale_chunks():
    Session = _session_factory()
    _insert_document(Session, document_id="doc-1", owner_id="user-1")
    old_time = datetime.now(timezone.utc) - timedelta(days=1)
    new_time = datetime.now(timezone.utc)
    _insert_artifact(
        Session,
        artifact_id="artifact-old",
        document_id="doc-1",
        content="Old derivative notes split across several chunks for removal.",
        created_at=old_time,
    )
    service = StudyDocumentIndexService(
        session_factory=Session,
        chunker=StudyDocumentChunker(max_chars=24, overlap_chars=4),
    )
    old_status = service.index_document(owner_id="user-1", document_id="doc-1")
    _insert_artifact(
        Session,
        artifact_id="artifact-new",
        document_id="doc-1",
        content="New integral notes",
        created_at=new_time,
    )

    new_status = service.index_document(owner_id="user-1", document_id="doc-1")

    assert old_status.artifact_id == "artifact-old"
    assert new_status.artifact_id == "artifact-new"
    with Session() as session:
        rows = session.query(DocumentChunkRecord).all()
    assert {row.artifact_id for row in rows} == {"artifact-new"}
    assert len(rows) == new_status.chunk_count


def test_index_service_status_reports_missing_index_and_stale_index():
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
    service = StudyDocumentIndexService(session_factory=Session)

    missing = service.status(owner_id="user-1", document_id="doc-1")
    assert missing.status == "fallback_available"
    assert missing.chunk_count == 0
    assert missing.fallback_reason == "persisted_chunks_missing"

    service.index_document(owner_id="user-1", document_id="doc-1")
    _insert_artifact(
        Session,
        artifact_id="artifact-new",
        document_id="doc-1",
        content="New derivative notes",
        created_at=new_time,
    )

    stale = service.status(owner_id="user-1", document_id="doc-1")
    assert stale.status == "stale"
    assert stale.artifact_id == "artifact-old"
    assert stale.fallback_reason == "latest_artifact_not_indexed"


def test_index_service_status_reports_incomplete_persisted_chunk_set_as_fallback():
    Session = _session_factory()
    _insert_document(Session, document_id="doc-1", owner_id="user-1")
    _insert_artifact(
        Session,
        artifact_id="artifact-1",
        document_id="doc-1",
        content=(
            "Derivatives measure instantaneous rate of change. "
            "Gradients extend derivatives to several variables. "
            "Integrals accumulate signed area over intervals."
        ),
        created_at=datetime.now(timezone.utc),
    )
    service = StudyDocumentIndexService(
        session_factory=Session,
        chunker=StudyDocumentChunker(max_chars=48, overlap_chars=8),
    )
    indexed = service.index_document(owner_id="user-1", document_id="doc-1")
    assert indexed.chunk_count >= 2
    with Session() as session:
        row = (
            session.query(DocumentChunkRecord)
            .filter(DocumentChunkRecord.document_id == "doc-1")
            .order_by(DocumentChunkRecord.chunk_index.desc())
            .first()
        )
        session.delete(row)
        session.commit()

    status = service.status(owner_id="user-1", document_id="doc-1")

    assert status.status == "fallback_available"
    assert status.artifact_id == "artifact-1"
    assert status.fallback_reason == "persisted_chunks_incomplete"


def test_index_service_summary_counts_statuses_and_fallback_reasons():
    Session = _session_factory()
    _add_ready_document_with_artifact(
        Session,
        document_id="doc-indexed",
        owner_id="user-1",
        artifact_id="artifact-indexed",
        content="Derivative content",
    )
    _add_ready_document_with_artifact(
        Session,
        document_id="doc-missing",
        owner_id="user-1",
        artifact_id="artifact-missing",
        content="Gradient content",
    )
    _add_ready_document_with_artifact(
        Session,
        document_id="doc-other",
        owner_id="user-2",
        artifact_id="artifact-other",
        content="Other content",
    )
    service = StudyDocumentIndexService(Session)
    service.index_document(owner_id="user-1", document_id="doc-indexed")

    summary = service.summary(owner_id="user-1")

    assert summary["owner_id"] == "user-1"
    assert summary["total_documents"] == 2
    assert summary["status_counts"]["indexed"] == 1
    assert summary["status_counts"]["fallback_available"] == 1
    assert summary["fallback_reason_counts"]["persisted_chunks_missing"] == 1
    assert {item["document_id"] for item in summary["documents"]} == {
        "doc-indexed",
        "doc-missing",
    }
    forbidden_keys = {"content", "snippet", "query", "answer", "token", "password", "secret"}
    for document_status in summary["documents"]:
        assert forbidden_keys.isdisjoint(document_status)


def test_index_service_load_chunks_filters_owner_and_requested_documents():
    Session = _session_factory()
    _insert_document(Session, document_id="doc-1", owner_id="user-1")
    _insert_document(Session, document_id="doc-2", owner_id="user-2")
    now = datetime.now(timezone.utc)
    _insert_artifact(
        Session,
        artifact_id="artifact-1",
        document_id="doc-1",
        content="Owned notes",
        created_at=now,
    )
    _insert_artifact(
        Session,
        artifact_id="artifact-2",
        document_id="doc-2",
        content="Private notes",
        created_at=now,
    )
    service = StudyDocumentIndexService(session_factory=Session)
    service.index_document(owner_id="user-1", document_id="doc-1")
    service.index_document(owner_id="user-2", document_id="doc-2")

    chunks = service.load_chunks(owner_id="user-1", document_ids=("doc-1", "doc-2"))

    assert {chunk["metadata"]["document_id"] for chunk in chunks} == {"doc-1"}
    assert all(chunk["metadata"]["owner_id"] == "user-1" for chunk in chunks)


def test_document_index_status_to_dict_serializes_datetime_without_content():
    indexed_at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    status = DocumentIndexStatus(
        document_id="doc-1",
        status="indexed",
        artifact_id="artifact-1",
        chunk_count=3,
        indexed_at=indexed_at,
        fallback_reason=None,
    )

    serialized = status.to_dict()

    assert serialized == {
        "document_id": "doc-1",
        "status": "indexed",
        "artifact_id": "artifact-1",
        "chunk_count": 3,
        "indexed_at": "2026-01-02T03:04:05+00:00",
        "fallback_reason": None,
        "expected_chunk_count": None,
        "indexed_artifact_id": None,
        "latest_artifact_id": None,
    }
    assert "content" not in serialized


def test_index_artifact_can_bypass_ready_check_but_index_document_rejects_processing():
    Session = _session_factory()
    _insert_document(
        Session,
        document_id="doc-processing",
        owner_id="user-1",
        status="processing",
    )
    _insert_artifact(
        Session,
        artifact_id="artifact-1",
        document_id="doc-processing",
        content="Worker normalized text",
        created_at=datetime.now(timezone.utc),
    )
    service = StudyDocumentIndexService(session_factory=Session)

    with pytest.raises(StudyAgentDocumentError) as exc_info:
        service.index_document(owner_id="user-1", document_id="doc-processing")

    assert exc_info.value.code == "document_not_ready"
    status = service.index_artifact(
        owner_id="user-1",
        document_id="doc-processing",
        artifact_id="artifact-1",
        require_ready=False,
    )
    assert status.status == "indexed"


def test_index_service_rejects_empty_chunk_output_as_missing_evidence():
    class EmptyChunker:
        def chunk(self, evidence):
            return []

    Session = _session_factory()
    _insert_document(Session, document_id="doc-1", owner_id="user-1")
    _insert_artifact(
        Session,
        artifact_id="artifact-1",
        document_id="doc-1",
        content="Visible artifact content",
        created_at=datetime.now(timezone.utc),
    )
    service = StudyDocumentIndexService(session_factory=Session, chunker=EmptyChunker())

    with pytest.raises(StudyAgentDocumentError) as exc_info:
        service.index_document(owner_id="user-1", document_id="doc-1")

    assert exc_info.value.code == "document_evidence_missing"
    with Session() as session:
        assert session.query(DocumentChunkRecord).count() == 0


def test_index_service_content_hash_includes_source_defining_metadata():
    Session = _session_factory()
    _insert_document(Session, document_id="doc-1", owner_id="user-1")
    now = datetime.now(timezone.utc)
    _insert_artifact(
        Session,
        artifact_id="artifact-1",
        document_id="doc-1",
        content="Same normalized text",
        created_at=now - timedelta(days=1),
    )
    _insert_artifact(
        Session,
        artifact_id="artifact-2",
        document_id="doc-1",
        content="Same normalized text",
        created_at=now,
    )
    service = StudyDocumentIndexService(session_factory=Session)

    first = service.index_artifact(
        owner_id="user-1",
        document_id="doc-1",
        artifact_id="artifact-1",
    )
    with Session() as session:
        first_hash = session.query(DocumentChunkRecord.content_hash).one()[0]
    second = service.index_artifact(
        owner_id="user-1",
        document_id="doc-1",
        artifact_id="artifact-2",
    )
    with Session() as session:
        second_hash = session.query(DocumentChunkRecord.content_hash).one()[0]

    assert first.chunk_count == second.chunk_count == 1
    assert first_hash != second_hash
