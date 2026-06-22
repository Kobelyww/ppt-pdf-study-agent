from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base
from src.services.document_service import DocumentService
from src.services.export_service import ExportFormat, ExportService
from src.services.version_service import create_persisted_version
from src.storage.backend import LocalStorageBackend
from src.workers.tasks import run_export_task


def _setup(tmp_path: Path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    storage = LocalStorageBackend(tmp_path / "objects")
    document_service = DocumentService(session_factory=Session, storage=storage)
    export_service = ExportService(session_factory=Session, storage=storage)
    upload = document_service.create_upload(
        owner_id="user-1",
        filename="notes.pdf",
        content=b"Integration by parts study notes.",
        content_type="application/pdf",
    )
    version = create_persisted_version(
        session_factory=Session,
        document_id=upload.document.id,
        target_type="outline",
        target_id=upload.document.id,
        content="# Integration\n\nUse u-substitution and integration by parts.",
        created_by="test",
        change_summary="created outline",
    )
    return Session, storage, upload.document, version, export_service


def test_export_worker_completes_job_and_stores_rendered_content(tmp_path: Path):
    Session, storage, document, version, export_service = _setup(tmp_path)
    job = export_service.create_export_job(
        owner_id="user-1",
        document_id=document.id,
        version_id=version.id,
        export_format=ExportFormat.MARKDOWN,
    )

    run_export_task(
        export_job_id=job.id,
        owner_id="user-1",
        session_factory=Session,
        storage=storage,
    )

    completed = export_service.get_export_job(owner_id="user-1", export_job_id=job.id)

    assert completed is not None
    assert completed.status == "completed"
    assert completed.storage_uri is not None
    assert completed.storage_uri.startswith("local://exports/")
    assert storage.read_bytes(completed.storage_uri).decode("utf-8") == version.content


def test_export_worker_marks_job_failed_when_storage_write_fails(tmp_path: Path):
    Session, _storage, _document, version, export_service = _setup(tmp_path)
    job = export_service.create_export_job(
        owner_id="user-1",
        document_id=version.document_id,
        version_id=version.id,
        export_format=ExportFormat.MARKDOWN,
    )

    class FailingStorage:
        def put_bytes(self, **kwargs):
            raise RuntimeError("export storage unavailable")

    try:
        run_export_task(
            export_job_id=job.id,
            owner_id="user-1",
            session_factory=Session,
            storage=FailingStorage(),
        )
    except RuntimeError as exc:
        assert str(exc) == "export storage unavailable"
    else:
        raise AssertionError("expected export storage failure")

    failed = export_service.get_export_job(owner_id="user-1", export_job_id=job.id)

    assert failed is not None
    assert failed.status == "failed"
    assert failed.error_message == "export storage unavailable"
