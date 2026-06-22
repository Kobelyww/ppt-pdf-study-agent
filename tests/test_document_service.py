from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base
from src.services.document_service import DocumentService
from src.storage.backend import LocalStorageBackend


def _service(tmp_path: Path) -> DocumentService:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return DocumentService(
        session_factory=Session,
        storage=LocalStorageBackend(tmp_path / "objects"),
    )


def test_document_service_upload_creates_owned_document_and_job(tmp_path: Path):
    service = _service(tmp_path)

    result = service.create_upload(
        owner_id="user-1",
        filename="notes.pdf",
        content=b"calculus notes",
        content_type="application/pdf",
    )

    assert result.document.owner_id == "user-1"
    assert result.document.original_filename == "notes.pdf"
    assert result.document.status == "uploaded"
    assert result.document.storage_uri.startswith("local://uploads/")
    assert result.job.owner_id == "user-1"
    assert result.job.document_id == result.document.id
    assert result.job.status == "queued"
    assert result.job.progress == 0


def test_document_service_lists_only_owned_documents(tmp_path: Path):
    service = _service(tmp_path)
    service.create_upload(
        owner_id="user-1",
        filename="first.pdf",
        content=b"first",
        content_type="application/pdf",
    )
    service.create_upload(
        owner_id="user-2",
        filename="second.pdf",
        content=b"second",
        content_type="application/pdf",
    )

    user_1_documents = service.list_documents(owner_id="user-1")

    assert [document.owner_id for document in user_1_documents] == ["user-1"]
    assert [document.original_filename for document in user_1_documents] == ["first.pdf"]


def test_document_service_retries_failed_job(tmp_path: Path):
    service = _service(tmp_path)
    result = service.create_upload(
        owner_id="user-1",
        filename="notes.pdf",
        content=b"notes",
        content_type="application/pdf",
    )
    service.update_job_status(
        job_id=result.job.id,
        status="failed",
        owner_id="user-1",
        error_message="parser failed",
    )

    retried = service.retry_job(job_id=result.job.id, owner_id="user-1")

    assert retried.status == "queued"
    assert retried.progress == 0
    assert retried.error_message is None
