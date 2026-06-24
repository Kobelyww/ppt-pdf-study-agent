from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.app import create_app
from src.config import ProductConfig
from src.db.models import Base, ContentVersionRecord, Document, ExportJobRecord, ProcessingJob, UserRecord
from src.security.auth import hash_password
from src.services.export_service import ExportService
from src.services.document_service import DocumentService
from src.services.version_service import create_persisted_version
from src.storage.backend import LocalStorageBackend
from src.workers.runner import run_worker_once
from src.workers.tasks import (
    recover_stale_running_jobs,
    run_product_document_task,
)


def _sqlite_session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _seed_user(Session, *, user_id: str, email: str, role: str = "user", active: bool = True):
    with Session() as session:
        session.add(
            UserRecord(
                id=user_id,
                email=email,
                password_hash=hash_password("password-123"),
                role=role,
                is_active=active,
            )
        )
        session.commit()


def _auth_headers(client: TestClient, email: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": "password-123"},
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_authenticated_product_loop_denies_cross_user_access(tmp_path: Path):
    Session = _sqlite_session_factory()
    _seed_user(Session, user_id="user-1", email="one@example.com")
    _seed_user(Session, user_id="user-2", email="two@example.com")
    service = DocumentService(
        session_factory=Session,
        storage=LocalStorageBackend(tmp_path / "objects"),
    )
    client = TestClient(
        create_app(
            document_service=service,
            secret_key="test-secret",
            allow_dev_user_header=False,
        )
    )
    user_1_headers = _auth_headers(client, "one@example.com")
    user_2_headers = _auth_headers(client, "two@example.com")

    upload_response = client.post(
        "/api/documents",
        headers=user_1_headers,
        files={"file": ("notes.pdf", b"Limits define continuity.", "application/pdf")},
    )
    assert upload_response.status_code == 202
    document_id = upload_response.json()["document"]["id"]
    create_persisted_version(
        session_factory=Session,
        document_id=document_id,
        target_type="outline",
        target_id=document_id,
        content="# Limits",
        created_by="worker",
        change_summary="generated outline",
    )

    assert client.get(f"/api/documents/{document_id}", headers=user_1_headers).status_code == 200
    assert client.get(f"/api/documents/{document_id}", headers=user_2_headers).status_code == 403
    outline_response = client.get(
        f"/api/documents/{document_id}/outline",
        headers=user_1_headers,
    )
    assert outline_response.status_code == 200
    assert outline_response.json()["content"] == "# Limits"


class CapturingQueue:
    def __init__(self):
        self.payloads = []

    def enqueue(self, payload):
        self.payloads.append(payload)
        return getattr(payload, "job_id", None) or getattr(payload, "export_job_id", None)

    def dequeue(self):
        if not self.payloads:
            return None
        return self.payloads.pop(0)


def test_api_uploaded_document_payload_is_executable_by_worker(tmp_path: Path):
    Session = _sqlite_session_factory()
    _seed_user(Session, user_id="user-1", email="one@example.com")
    service = DocumentService(
        session_factory=Session,
        storage=LocalStorageBackend(tmp_path / "objects"),
    )
    queue = CapturingQueue()
    client = TestClient(
        create_app(
            document_service=service,
            job_queue=queue,
            secret_key="test-secret",
            allow_dev_user_header=False,
        )
    )
    headers = _auth_headers(client, "one@example.com")

    upload = client.post(
        "/api/documents",
        headers=headers,
        files={"file": ("notes.pdf", b"Rates of change.", "application/pdf")},
    )
    assert upload.status_code == 202

    assert run_worker_once(queue, session_factory=Session, storage=service.storage, poll_seconds=0)
    with Session() as session:
        document = session.get(Document, upload.json()["document"]["id"])
        versions = session.query(ContentVersionRecord).all()
    assert document.status == "ready"
    assert {version.target_type for version in versions} == {"outline", "question_set"}


def test_api_created_export_payload_is_executable_by_worker(tmp_path: Path):
    Session = _sqlite_session_factory()
    _seed_user(Session, user_id="user-1", email="one@example.com")
    storage = LocalStorageBackend(tmp_path / "objects")
    document_service = DocumentService(session_factory=Session, storage=storage)
    export_service = ExportService(session_factory=Session, storage=storage)
    upload = document_service.create_upload(
        owner_id="user-1",
        filename="notes.pdf",
        content=b"content",
        content_type="application/pdf",
    )
    version = create_persisted_version(
        session_factory=Session,
        document_id=upload.document.id,
        target_type="outline",
        target_id=upload.document.id,
        content="# Outline",
        created_by="worker",
        change_summary="generated outline",
    )
    queue = CapturingQueue()
    client = TestClient(
        create_app(
            document_service=document_service,
            export_service=export_service,
            job_queue=queue,
            secret_key="test-secret",
            allow_dev_user_header=False,
        )
    )
    headers = _auth_headers(client, "one@example.com")

    response = client.post(
        f"/api/exports/{upload.document.id}",
        headers=headers,
        json={"version_id": version.id, "format": "markdown"},
    )
    assert response.status_code == 200

    assert run_worker_once(queue, session_factory=Session, storage=storage, poll_seconds=0)
    with Session() as session:
        export = session.get(ExportJobRecord, response.json()["id"])
    assert export.status == "completed"
    assert export.storage_uri is not None


def test_product_document_task_is_idempotent_for_completed_jobs(tmp_path: Path):
    Session = _sqlite_session_factory()
    service = DocumentService(
        session_factory=Session,
        storage=LocalStorageBackend(tmp_path / "objects"),
    )
    upload = service.create_upload(
        owner_id="user-1",
        filename="notes.pdf",
        content=b"Integration accumulates change.",
        content_type="application/pdf",
    )

    run_product_document_task(
        job_id=upload.job.id,
        document_id=upload.document.id,
        owner_id="user-1",
        session_factory=Session,
        storage=service.storage,
    )
    run_product_document_task(
        job_id=upload.job.id,
        document_id=upload.document.id,
        owner_id="user-1",
        session_factory=Session,
        storage=service.storage,
    )

    with Session() as session:
        versions = session.query(ContentVersionRecord).all()
        artifacts = session.query(Document).filter(Document.id == upload.document.id).one().artifacts
    assert len(versions) == 2
    assert len(artifacts) == 1


def test_recover_stale_running_jobs_marks_old_running_jobs_failed(tmp_path: Path):
    Session = _sqlite_session_factory()
    service = DocumentService(
        session_factory=Session,
        storage=LocalStorageBackend(tmp_path / "objects"),
    )
    upload = service.create_upload(
        owner_id="user-1",
        filename="notes.pdf",
        content=b"content",
        content_type="application/pdf",
    )
    service.update_job_status(job_id=upload.job.id, owner_id="user-1", status="running")

    recovered = recover_stale_running_jobs(session_factory=Session, max_age_seconds=0)

    assert recovered == 1
    with Session() as session:
        job = session.get(ProcessingJob, upload.job.id)
    assert job.status == "failed"
    assert "stale running job" in job.error_message


def test_production_create_app_wires_runtime_and_readiness(monkeypatch, tmp_path: Path):
    config = ProductConfig(
        app_env="production",
        secret_key="real-production-secret",
        allow_dev_user_header=False,
        database_url="postgresql://study:study@postgres/study",
        queue_backend="redis",
        redis_url="redis://redis:6379/0",
        storage_backend="s3",
        s3_endpoint_url="http://minio:9000",
        s3_bucket="study-agent",
        s3_access_key_id="minioadmin",
        s3_secret_access_key="minioadmin",
    )
    Session = _sqlite_session_factory()
    storage = LocalStorageBackend(tmp_path / "objects")

    class HealthyQueue:
        def healthcheck(self):
            return True

    monkeypatch.setattr("src.api.app.load_product_config", lambda: config)
    monkeypatch.setattr("src.api.app.get_engine", lambda database_url: Session.kw["bind"])
    monkeypatch.setattr("src.api.app.create_session_factory", lambda engine: Session)
    monkeypatch.setattr("src.api.app.create_storage_backend", lambda loaded_config: storage)
    monkeypatch.setattr(
        "src.api.app.create_job_queue",
        lambda **kwargs: HealthyQueue(),
    )

    app = create_app()
    client = TestClient(app)

    assert isinstance(app.state.document_service, DocumentService)
    assert app.state.session_factory is Session
    assert app.state.secret_key == "real-production-secret"
    assert app.state.allow_dev_user_header is False
    assert client.get("/ready").status_code == 200


def test_production_runtime_bootstraps_first_admin_user(monkeypatch, tmp_path: Path):
    config = ProductConfig(
        app_env="production",
        secret_key="real-production-secret",
        allow_dev_user_header=False,
        database_url="postgresql://study:study@postgres/study",
        queue_backend="redis",
        redis_url="redis://redis:6379/0",
        storage_backend="s3",
        s3_endpoint_url="http://minio:9000",
        s3_bucket="study-agent",
        s3_access_key_id="minioadmin",
        s3_secret_access_key="minioadmin",
        bootstrap_admin_email="admin@example.com",
        bootstrap_admin_password="password-123",
    )
    Session = _sqlite_session_factory()
    storage = LocalStorageBackend(tmp_path / "objects")

    class HealthyQueue:
        def healthcheck(self):
            return True

    monkeypatch.setattr("src.api.app.get_engine", lambda database_url: Session.kw["bind"])
    monkeypatch.setattr("src.api.app.create_session_factory", lambda engine: Session)
    monkeypatch.setattr("src.api.app.create_storage_backend", lambda loaded_config: storage)
    monkeypatch.setattr("src.api.app.create_job_queue", lambda **kwargs: HealthyQueue())

    from src.api.app import build_product_runtime

    build_product_runtime(config)
    client = TestClient(
        create_app(
            document_service=DocumentService(session_factory=Session, storage=storage),
            session_factory=Session,
            secret_key="real-production-secret",
            allow_dev_user_header=False,
        )
    )
    response = client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "password-123"},
    )

    assert response.status_code == 200
    with Session() as session:
        admin = session.query(UserRecord).filter(UserRecord.email == "admin@example.com").one()
    assert admin.role == "admin"


def test_cors_preflight_allows_authorization_header():
    app = create_app(
        document_service=object(),
        secret_key="test-secret",
        allow_dev_user_header=True,
        cors_origins=["http://localhost:5173"],
    )
    response = TestClient(app).options(
        "/api/documents",
        headers={
            "origin": "http://localhost:5173",
            "access-control-request-method": "GET",
            "access-control-request-headers": "authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_readiness_reports_unavailable_dependency():
    class FailingCheck:
        def healthcheck(self):
            return False

    app = create_app(
        document_service=object(),
        readiness_checks={"database": FailingCheck()},
    )
    response = TestClient(app).get("/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["database"] is False
