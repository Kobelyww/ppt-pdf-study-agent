from fastapi.testclient import TestClient
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.app import create_app
from src.db.models import Base
from src.services.version_service import create_persisted_version
from src.services.document_service import DocumentService
from src.storage.backend import LocalStorageBackend


class FakeDocumentService:
    def __init__(self):
        self.create_document_calls = []
        self.jobs = {}
        self.create_document_status = "queued"

    def create_document(self, metadata):
        self.create_document_calls.append(metadata)
        document_id = "doc-test-1"
        job_id = "job-test-1"
        self.jobs[job_id] = {
            "job_id": job_id,
            "document_id": document_id,
            "status": self.create_document_status,
        }
        return {
            "document_id": document_id,
            "job_id": job_id,
            "status": self.create_document_status,
            "metadata": metadata,
        }

    def get_job(self, job_id):
        return self.jobs.get(job_id)

    def update_job_status(self, job_id, status, error_message=None, **metadata):
        job = self.jobs.setdefault(job_id, {"job_id": job_id})
        job["status"] = status
        job["error_message"] = error_message
        job.update(metadata)


class FakeJobQueue:
    def __init__(self):
        self.enqueued_tasks = []

    def enqueue(self, task):
        self.enqueued_tasks.append(task)
        return task.job_id


class FailingJobQueue:
    def enqueue(self, task):
        raise RuntimeError("queue unavailable")


def test_post_documents_accepts_metadata_and_delegates_to_service():
    service = FakeDocumentService()
    client = TestClient(create_app(document_service=service))

    response = client.post(
        "/api/documents",
        json={
            "title": "Calculus Notes",
            "source_type": "pdf",
            "storage_uri": "file:///tmp/calculus.pdf",
        },
    )

    assert response.status_code == 202
    assert response.json() == {
        "document_id": "doc-test-1",
        "job_id": "job-test-1",
        "status": "queued",
        "metadata": {
            "title": "Calculus Notes",
            "source_type": "pdf",
            "storage_uri": "file:///tmp/calculus.pdf",
        },
    }
    assert service.create_document_calls == [
        {
            "title": "Calculus Notes",
            "source_type": "pdf",
            "storage_uri": "file:///tmp/calculus.pdf",
        }
    ]


def test_post_documents_enqueues_background_task_when_queue_is_configured():
    service = FakeDocumentService()
    queue = FakeJobQueue()
    client = TestClient(create_app(document_service=service, job_queue=queue))

    response = client.post(
        "/api/documents",
        json={"title": "Calculus Notes", "source_type": "pdf"},
    )

    assert response.status_code == 202
    assert len(queue.enqueued_tasks) == 1
    task = queue.enqueued_tasks[0]
    assert task.job_id == "job-test-1"
    assert task.document_id == "doc-test-1"
    assert task.stages
    assert task.stage_keys == [
        "metadata_validation",
        "parse",
        "extract",
        "outline",
        "questions",
    ]


def test_post_documents_marks_job_failed_when_enqueue_fails():
    service = FakeDocumentService()
    client = TestClient(create_app(document_service=service, job_queue=FailingJobQueue()))

    response = client.post(
        "/api/documents",
        json={"title": "Calculus Notes", "source_type": "pdf"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Failed to enqueue document processing job"
    assert service.jobs["job-test-1"]["status"] == "failed"
    assert service.jobs["job-test-1"]["error_message"] == "queue unavailable"


def test_get_job_returns_allowed_status():
    service = FakeDocumentService()
    service.jobs["job-running"] = {
        "job_id": "job-running",
        "document_id": "doc-test-2",
        "status": "running",
    }
    client = TestClient(create_app(document_service=service))

    response = client.get("/api/jobs/job-running")

    assert response.status_code == 200
    assert response.json() == {
        "job_id": "job-running",
        "document_id": "doc-test-2",
        "status": "running",
    }


def test_get_missing_job_returns_404():
    client = TestClient(create_app(document_service=FakeDocumentService()))

    response = client.get("/api/jobs/missing-job")

    assert response.status_code == 404
    assert response.json()["detail"] == "Job not found"


def test_post_documents_rejects_invalid_service_status():
    service = FakeDocumentService()
    service.create_document_status = "unknown"
    client = TestClient(create_app(document_service=service))

    response = client.post(
        "/api/documents",
        json={"title": "Calculus Notes", "source_type": "pdf"},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Invalid job status from document service"


def test_get_job_rejects_invalid_service_status():
    service = FakeDocumentService()
    service.jobs["job-invalid"] = {
        "job_id": "job-invalid",
        "document_id": "doc-test-3",
        "status": "unknown",
    }
    client = TestClient(create_app(document_service=service))

    response = client.get("/api/jobs/job-invalid")

    assert response.status_code == 502
    assert response.json()["detail"] == "Invalid job status from document service"


def test_post_documents_requires_source_type():
    client = TestClient(create_app(document_service=FakeDocumentService()))

    response = client.post("/api/documents", json={"title": "Calculus Notes"})

    assert response.status_code == 422


def test_post_documents_rejects_empty_title():
    client = TestClient(create_app(document_service=FakeDocumentService()))

    response = client.post(
        "/api/documents",
        json={"title": "", "source_type": "pdf"},
    )

    assert response.status_code == 422


def _client_with_persisted_service(tmp_path: Path):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    service = DocumentService(
        session_factory=Session,
        storage=LocalStorageBackend(tmp_path / "objects"),
    )
    return TestClient(create_app(document_service=service)), service


def test_upload_file_creates_document_and_job_for_current_user(tmp_path: Path):
    client, _service = _client_with_persisted_service(tmp_path)

    response = client.post(
        "/api/documents",
        headers={"x-user-id": "user-1"},
        files={"file": ("notes.pdf", b"calculus notes", "application/pdf")},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["document"]["owner_id"] == "user-1"
    assert body["document"]["original_filename"] == "notes.pdf"
    assert body["job"]["owner_id"] == "user-1"
    assert body["job"]["document_id"] == body["document"]["id"]


def test_document_list_is_scoped_to_current_user(tmp_path: Path):
    client, _service = _client_with_persisted_service(tmp_path)
    client.post(
        "/api/documents",
        headers={"x-user-id": "user-1"},
        files={"file": ("first.pdf", b"first", "application/pdf")},
    )
    client.post(
        "/api/documents",
        headers={"x-user-id": "user-2"},
        files={"file": ("second.pdf", b"second", "application/pdf")},
    )

    response = client.get("/api/documents", headers={"x-user-id": "user-1"})

    assert response.status_code == 200
    assert [document["original_filename"] for document in response.json()] == ["first.pdf"]


def test_cross_user_job_access_returns_403(tmp_path: Path):
    client, _service = _client_with_persisted_service(tmp_path)
    upload = client.post(
        "/api/documents",
        headers={"x-user-id": "user-1"},
        files={"file": ("notes.pdf", b"notes", "application/pdf")},
    ).json()

    response = client.get(
        f"/api/jobs/{upload['job']['id']}",
        headers={"x-user-id": "user-2"},
    )

    assert response.status_code == 403


def test_failed_job_can_be_retried_by_owner(tmp_path: Path):
    client, service = _client_with_persisted_service(tmp_path)
    upload = client.post(
        "/api/documents",
        headers={"x-user-id": "user-1"},
        files={"file": ("notes.pdf", b"notes", "application/pdf")},
    ).json()
    service.update_job_status(
        job_id=upload["job"]["id"],
        owner_id="user-1",
        status="failed",
        error_message="parser failed",
    )

    response = client.post(
        f"/api/jobs/{upload['job']['id']}/retry",
        headers={"x-user-id": "user-1"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "queued"


def test_document_versions_endpoint_returns_owned_document_versions(tmp_path: Path):
    client, service = _client_with_persisted_service(tmp_path)
    upload = service.create_upload(
        owner_id="user-1",
        filename="notes.pdf",
        content=b"notes",
        content_type="application/pdf",
    )
    version = create_persisted_version(
        session_factory=service.session_factory,
        document_id=upload.document.id,
        target_type="outline",
        target_id=upload.document.id,
        content="# Outline",
        created_by="test",
        change_summary="initial outline",
    )

    response = client.get(
        f"/api/documents/{upload.document.id}/versions",
        headers={"x-user-id": "user-1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body[0]["id"] == version.id
    assert body[0]["document_id"] == upload.document.id
    assert body[0]["target_type"] == "outline"
    assert body[0]["content"] == "# Outline"
    assert body[0]["created_by"] == "test"
    assert body[0]["change_summary"] == "initial outline"
    assert body[0]["content_metadata"] == {}


def test_document_versions_endpoint_forbids_cross_user_access(tmp_path: Path):
    client, service = _client_with_persisted_service(tmp_path)
    upload = service.create_upload(
        owner_id="user-1",
        filename="notes.pdf",
        content=b"notes",
        content_type="application/pdf",
    )

    response = client.get(
        f"/api/documents/{upload.document.id}/versions",
        headers={"x-user-id": "user-2"},
    )

    assert response.status_code == 403


def test_document_outline_and_questions_endpoints_return_latest_content(tmp_path: Path):
    client, service = _client_with_persisted_service(tmp_path)
    upload = service.create_upload(
        owner_id="user-1",
        filename="notes.pdf",
        content=b"notes",
        content_type="application/pdf",
    )
    create_persisted_version(
        session_factory=service.session_factory,
        document_id=upload.document.id,
        target_type="outline",
        target_id=upload.document.id,
        content="# Outline",
        created_by="test",
        change_summary="initial outline",
    )
    create_persisted_version(
        session_factory=service.session_factory,
        document_id=upload.document.id,
        target_type="question_set",
        target_id=upload.document.id,
        content="# Questions",
        created_by="test",
        change_summary="initial questions",
    )

    outline = client.get(
        f"/api/documents/{upload.document.id}/outline",
        headers={"x-user-id": "user-1"},
    )
    questions = client.get(
        f"/api/documents/{upload.document.id}/questions",
        headers={"x-user-id": "user-1"},
    )

    assert outline.status_code == 200
    assert outline.json()["content"] == "# Outline"
    assert questions.status_code == 200
    assert questions.json()["content"] == "# Questions"


def test_document_outline_endpoint_returns_404_when_no_content(tmp_path: Path):
    client, service = _client_with_persisted_service(tmp_path)
    upload = service.create_upload(
        owner_id="user-1",
        filename="notes.pdf",
        content=b"notes",
        content_type="application/pdf",
    )

    response = client.get(
        f"/api/documents/{upload.document.id}/outline",
        headers={"x-user-id": "user-1"},
    )

    assert response.status_code == 404


def test_create_export_job_for_owned_document(tmp_path: Path):
    client, service = _client_with_persisted_service(tmp_path)
    upload = service.create_upload(
        owner_id="user-1",
        filename="notes.pdf",
        content=b"notes",
        content_type="application/pdf",
    )
    version = create_persisted_version(
        session_factory=service.session_factory,
        document_id=upload.document.id,
        target_type="outline",
        target_id=upload.document.id,
        content="# Outline",
        created_by="test",
        change_summary="initial outline",
    )

    response = client.post(
        f"/api/exports/{upload.document.id}",
        headers={"x-user-id": "user-1"},
        json={"version_id": version.id, "format": "markdown"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["document_id"] == upload.document.id
    assert body["version_id"] == version.id
    assert body["format"] == "markdown"
    assert body["status"] == "queued"
    assert body["storage_uri"] is None


def test_create_export_job_forbids_cross_user_document(tmp_path: Path):
    client, service = _client_with_persisted_service(tmp_path)
    upload = service.create_upload(
        owner_id="user-1",
        filename="notes.pdf",
        content=b"notes",
        content_type="application/pdf",
    )
    version = create_persisted_version(
        session_factory=service.session_factory,
        document_id=upload.document.id,
        target_type="outline",
        target_id=upload.document.id,
        content="# Outline",
        created_by="test",
        change_summary="initial outline",
    )

    response = client.post(
        f"/api/exports/{upload.document.id}",
        headers={"x-user-id": "user-2"},
        json={"version_id": version.id, "format": "markdown"},
    )

    assert response.status_code == 403
