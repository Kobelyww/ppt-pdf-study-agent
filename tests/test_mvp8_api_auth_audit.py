from pathlib import Path
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.app import create_app
from src.db.models import AuditEventRecord, Base, UserRecord
from src.security.audit import record_audit_event
from src.security.auth import hash_password
from src.services.document_service import DocumentService
from src.storage.backend import LocalStorageBackend


def _client(tmp_path: Path):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        session.add_all(
            [
                UserRecord(
                    id="user-1",
                    email="user@example.com",
                    password_hash=hash_password("password-123"),
                    role="user",
                    is_active=True,
                ),
                UserRecord(
                    id="admin-1",
                    email="admin@example.com",
                    password_hash=hash_password("password-123"),
                    role="admin",
                    is_active=True,
                ),
                UserRecord(
                    id="inactive-1",
                    email="inactive@example.com",
                    password_hash=hash_password("password-123"),
                    role="user",
                    is_active=False,
                ),
            ]
        )
        session.commit()
    service = DocumentService(
        session_factory=Session,
        storage=LocalStorageBackend(tmp_path / "objects"),
    )
    app = create_app(
        document_service=service,
        secret_key="test-secret",
        allow_dev_user_header=False,
    )
    return TestClient(app), Session


def _login(client: TestClient, email: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": "password-123"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_login_me_and_protected_api_require_bearer_token(tmp_path: Path):
    client, _Session = _client(tmp_path)
    headers = _login(client, "user@example.com")

    me = client.get("/api/auth/me", headers=headers)
    unauthorized = client.get("/api/documents")
    documents = client.get("/api/documents", headers=headers)

    assert me.status_code == 200
    assert me.json()["email"] == "user@example.com"
    assert unauthorized.status_code == 401
    assert documents.status_code == 200


def test_inactive_user_cannot_login(tmp_path: Path):
    client, _Session = _client(tmp_path)

    response = client.post(
        "/api/auth/login",
        json={"email": "inactive@example.com", "password": "password-123"},
    )

    assert response.status_code == 401


def test_dev_user_header_is_not_authoritative_when_disabled(tmp_path: Path):
    client, _Session = _client(tmp_path)

    response = client.get("/api/documents", headers={"x-user-id": "user-1"})

    assert response.status_code == 401


def test_audit_query_is_admin_only_and_filters_events(tmp_path: Path):
    client, Session = _client(tmp_path)
    user_headers = _login(client, "user@example.com")
    admin_headers = _login(client, "admin@example.com")
    record_audit_event(
        session_factory=Session,
        actor_id="user-1",
        action="document.uploaded",
        resource_type="document",
        resource_id="doc-1",
        request_id="req-1",
        metadata={"filename": "notes.pdf", "token": "hidden"},
    )

    forbidden = client.get("/api/audit-events", headers=user_headers)
    response = client.get(
        "/api/audit-events",
        params={"resource_type": "document"},
        headers=admin_headers,
    )

    assert forbidden.status_code == 403
    assert response.status_code == 200
    assert response.json()[0]["resource_id"] == "doc-1"
    assert "token" not in response.json()[0]["metadata"]
    with Session() as session:
        assert session.query(AuditEventRecord).count() == 1


def test_audit_query_filters_by_created_time_window(tmp_path: Path):
    client, Session = _client(tmp_path)
    admin_headers = _login(client, "admin@example.com")
    older = record_audit_event(
        session_factory=Session,
        actor_id="user-1",
        action="document.uploaded",
        resource_type="document",
        resource_id="doc-old",
        request_id="req-old",
    )
    newer = record_audit_event(
        session_factory=Session,
        actor_id="user-1",
        action="document.uploaded",
        resource_type="document",
        resource_id="doc-new",
        request_id="req-new",
    )
    with Session() as session:
        old_record = session.get(AuditEventRecord, older.id)
        old_record.created_at = datetime.now(timezone.utc) - timedelta(days=2)
        session.commit()

    response = client.get(
        "/api/audit-events",
        params={
            "created_after": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
            "created_before": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        },
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert [event["resource_id"] for event in response.json()] == [newer.resource_id]
