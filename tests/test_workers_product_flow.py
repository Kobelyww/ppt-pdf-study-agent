from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, ContentVersionRecord, Document, DocumentArtifactRecord
from src.services.document_service import DocumentService
from src.storage.backend import LocalStorageBackend
from src.workers.tasks import run_product_document_task


def _session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def test_product_document_task_creates_artifact_outline_and_questions(tmp_path: Path):
    Session = _session_factory()
    service = DocumentService(
        session_factory=Session,
        storage=LocalStorageBackend(tmp_path / "objects"),
    )
    upload = service.create_upload(
        owner_id="user-1",
        filename="notes.pdf",
        content=b"Derivatives measure instantaneous rate of change.",
        content_type="application/pdf",
    )

    run_product_document_task(
        job_id=upload.job.id,
        document_id=upload.document.id,
        owner_id="user-1",
        session_factory=Session,
        storage=service.storage,
    )

    with Session() as session:
        document = session.get(Document, upload.document.id)
        versions = (
            session.query(ContentVersionRecord)
            .order_by(ContentVersionRecord.target_type)
            .all()
        )
        artifacts = session.query(DocumentArtifactRecord).all()

    assert document.status == "ready"
    assert {version.target_type for version in versions} == {"outline", "question_set"}
    assert any("Derivatives" in version.content for version in versions)
    assert artifacts[0].artifact_type == "normalized_document"


def test_product_document_task_marks_document_and_job_failed_on_storage_error(
    tmp_path: Path,
):
    Session = _session_factory()
    service = DocumentService(
        session_factory=Session,
        storage=LocalStorageBackend(tmp_path / "objects"),
    )
    upload = service.create_upload(
        owner_id="user-1",
        filename="notes.pdf",
        content=b"Derivatives measure instantaneous rate of change.",
        content_type="application/pdf",
    )

    class FailingStorage:
        def read_bytes(self, storage_uri: str) -> bytes:
            raise RuntimeError("storage unavailable")

    try:
        run_product_document_task(
            job_id=upload.job.id,
            document_id=upload.document.id,
            owner_id="user-1",
            session_factory=Session,
            storage=FailingStorage(),
        )
    except RuntimeError as exc:
        assert str(exc) == "storage unavailable"
    else:
        raise AssertionError("expected storage failure")

    with Session() as session:
        document = session.get(Document, upload.document.id)
        job = document.jobs[0]

    assert document.status == "failed"
    assert job.status == "failed"
    assert job.error_message == "storage unavailable"
