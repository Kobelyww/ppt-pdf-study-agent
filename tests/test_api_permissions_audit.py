from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.app import create_app
from src.db.models import AuditEventRecord, Base
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
    service = DocumentService(
        session_factory=Session,
        storage=LocalStorageBackend(tmp_path / "objects"),
    )
    return TestClient(create_app(document_service=service)), service, Session


def test_upload_records_audit_event_without_raw_content(tmp_path: Path):
    client, _service, Session = _client(tmp_path)

    response = client.post(
        "/api/documents",
        headers={"x-user-id": "user-1", "x-request-id": "req-1"},
        files={"file": ("notes.pdf", b"secret content", "application/pdf")},
    )

    assert response.status_code == 202
    with Session() as session:
        events = session.query(AuditEventRecord).all()
    assert events[0].actor_id == "user-1"
    assert events[0].action == "document.uploaded"
    assert "secret content" not in str(events[0].event_metadata)


def test_cross_user_document_detail_is_forbidden(tmp_path: Path):
    client, _service, _Session = _client(tmp_path)
    upload = client.post(
        "/api/documents",
        headers={"x-user-id": "user-1"},
        files={"file": ("notes.pdf", b"notes", "application/pdf")},
    ).json()

    response = client.get(
        f"/api/documents/{upload['document']['id']}",
        headers={"x-user-id": "user-2"},
    )

    assert response.status_code == 403


def test_feedback_uses_header_user_and_records_audit(tmp_path: Path):
    client, _service, Session = _client(tmp_path)

    response = client.post(
        "/api/feedback",
        headers={"x-user-id": "user-1", "x-request-id": "req-feedback"},
        json={
            "target_type": "question",
            "target_id": "q-1",
            "rating": 1,
            "reason": "incorrect_answer",
            "comment": "The answer is wrong.",
        },
    )

    assert response.status_code == 200
    assert client.get(
        "/api/review-tasks",
        headers={"x-user-id": "user-1"},
    ).json()[0]["owner_id"] == "user-1"
    assert client.get(
        "/api/review-tasks",
        headers={"x-user-id": "attacker"},
    ).json() == []
    with Session() as session:
        event = (
            session.query(AuditEventRecord)
            .filter(AuditEventRecord.action == "feedback.created")
            .one()
        )
    assert event.actor_id == "user-1"
    assert event.resource_type == "feedback"
    assert event.resource_id == response.json()["id"]
    assert event.request_id == "req-feedback"
    assert event.event_metadata["target_id"] == "q-1"


def test_review_decision_is_owner_scoped_and_records_audit(tmp_path: Path):
    client, _service, Session = _client(tmp_path)
    client.post(
        "/api/feedback",
        headers={"x-user-id": "user-1"},
        json={
            "target_type": "question",
            "target_id": "q-1",
            "rating": 1,
            "reason": "incorrect_answer",
            "comment": "The answer is wrong.",
            "created_by": "user-1",
        },
    )
    task = client.get(
        "/api/review-tasks",
        headers={"x-user-id": "user-1"},
    ).json()[0]

    forbidden = client.post(
        f"/api/review-tasks/{task['id']}/decision",
        headers={"x-user-id": "user-2"},
        json={"decision": "reject", "comment": "No access."},
    )
    response = client.post(
        f"/api/review-tasks/{task['id']}/decision",
        headers={"x-user-id": "user-1", "x-request-id": "req-review"},
        json={"decision": "accept", "comment": "Will revise."},
    )

    assert forbidden.status_code == 403
    assert response.status_code == 200
    with Session() as session:
        event = (
            session.query(AuditEventRecord)
            .filter(AuditEventRecord.action == "review_task.decided")
            .one()
        )
    assert event.actor_id == "user-1"
    assert event.resource_id == task["id"]
    assert event.event_metadata["decision"] == "accept"


def test_feedback_ignores_body_created_by(tmp_path: Path):
    client, _service, _Session = _client(tmp_path)

    response = client.post(
        "/api/feedback",
        headers={"x-user-id": "user-1"},
        json={
            "target_type": "question",
            "target_id": "q-1",
            "rating": 1,
            "reason": "incorrect_answer",
            "comment": "The answer is wrong.",
            "created_by": "attacker",
        },
    )

    assert response.status_code == 200
    assert client.get(
        "/api/review-tasks",
        headers={"x-user-id": "user-1"},
    ).json()[0]["owner_id"] == "user-1"
    assert client.get(
        "/api/review-tasks",
        headers={"x-user-id": "attacker"},
    ).json() == []
