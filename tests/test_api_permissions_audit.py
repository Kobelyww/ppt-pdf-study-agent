from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.app import create_app
from src.db.models import (
    AuditEventRecord,
    Base,
    FeedbackRecord,
    ReviewTaskRecord,
    UserRecord,
)
from src.security.auth import hash_password
from src.services.document_service import DocumentService
from src.services.rag_route_policy import RAGReadinessSnapshot, RAGRoutePolicyConfig
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


def _create_user(Session, *, user_id: str, email: str, role: str = "user") -> None:
    with Session() as session:
        session.add(
            UserRecord(
                id=user_id,
                email=email,
                password_hash=hash_password("password-123"),
                role=role,
                is_active=True,
            )
        )
        session.commit()


def _login(client: TestClient, *, email: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": "password-123"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


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


def test_feedback_can_target_study_agent_trace_without_copying_private_content(
    tmp_path: Path,
):
    client, _service, Session = _client(tmp_path)
    headers = {"x-user-id": "user-1", "x-request-id": "req-feedback-trace"}

    response = client.post(
        "/api/feedback",
        json={
            "target_type": "study_agent_trace",
            "target_id": "trace-1",
            "rating": 1,
            "reason": "incorrect",
            "comment": "The answer missed the key term.",
        },
        headers=headers,
    )

    assert response.status_code == 200
    with Session() as session:
        feedback = session.query(FeedbackRecord).filter_by(target_id="trace-1").one()
        review = session.query(ReviewTaskRecord).filter_by(target_id="trace-1").one()
        event = session.query(AuditEventRecord).filter_by(action="feedback.created").one()

    assert feedback.target_type == "study_agent_trace"
    assert review.target_type == "study_agent_trace"
    assert event.event_metadata == {
        "target_type": "study_agent_trace",
        "target_id": "trace-1",
        "rating": 1,
        "reason": "incorrect",
    }
    assert "comment" not in event.event_metadata


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
    assert response.json()["decision"] == "accepted"
    with Session() as session:
        stored_task = session.get(ReviewTaskRecord, task["id"])
        event = (
            session.query(AuditEventRecord)
            .filter(AuditEventRecord.action == "review_task.decided")
            .one()
        )
    assert stored_task.decision == "accepted"
    assert event.actor_id == "user-1"
    assert event.resource_id == task["id"]
    assert event.event_metadata["decision"] == "accepted"


def test_review_decision_rejects_raw_decision_before_persistence_or_audit(
    tmp_path: Path,
):
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

    response = client.post(
        f"/api/review-tasks/{task['id']}/decision",
        headers={"x-user-id": "user-1", "x-request-id": "req-review-invalid"},
        json={"decision": "sk-secret-token", "comment": "raw reviewer comment"},
    )

    assert response.status_code == 422
    with Session() as session:
        stored_task = session.get(ReviewTaskRecord, task["id"])
        audit_count = (
            session.query(AuditEventRecord)
            .filter(AuditEventRecord.action == "review_task.decided")
            .count()
        )

    assert stored_task.status == "open"
    assert stored_task.decision is None
    assert audit_count == 0
    serialized = response.text
    assert "sk-secret-token" not in serialized
    assert "raw reviewer comment" not in serialized


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


def test_admin_can_read_rag_route_policy(tmp_path: Path):
    client, _service, Session = _client(tmp_path)
    _create_user(
        Session,
        user_id="admin-1",
        email="admin@example.com",
        role="admin",
    )
    client.app.state.rag_route_policy_config = RAGRoutePolicyConfig(
        advanced_routing_enabled=True,
        graph_rag_enabled=True,
        enabled_categories=frozenset({"concept_relation", "learning_path"}),
    )
    headers = _login(client, email="admin@example.com")

    response = client.get(
        "/api/admin/rag-route-policy",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json() == {
        "policy_version": "rag-policy-v1",
        "advanced_routing_enabled": True,
        "graph_rag_enabled": True,
        "agentic_rag_enabled": False,
        "enabled_categories": ["concept_relation", "learning_path"],
        "graph_candidate_required": True,
        "agentic_candidate_required": True,
        "allow_user_preferred_mode": False,
        "max_budget_for_agentic": "high",
        "require_persisted_chunks_for_advanced": True,
        "fallback_to_simple_on_block": True,
    }


def test_non_admin_cannot_access_rag_route_policy_admin_apis(tmp_path: Path):
    client, _service, Session = _client(tmp_path)
    _create_user(
        Session,
        user_id="user-1",
        email="user@example.com",
        role="user",
    )
    headers = _login(client, email="user@example.com")

    responses = [
        client.get("/api/admin/rag-route-policy", headers=headers),
        client.get("/api/admin/rag-route-readiness", headers=headers),
        client.post(
            "/api/admin/rag-route-policy/simulate",
            headers=headers,
            json={"query": "学习积分前需要掌握什么？"},
        ),
    ]

    assert [response.status_code for response in responses] == [403, 403, 403]


def test_admin_can_read_rag_route_readiness_snapshot_without_raw_content(
    tmp_path: Path,
):
    client, _service, Session = _client(tmp_path)
    _create_user(
        Session,
        user_id="admin-1",
        email="admin@example.com",
        role="admin",
    )
    client.app.state.rag_readiness_provider = lambda: RAGReadinessSnapshot(
        policy_version="rag-policy-v1",
        fixture_version="rag_eval_set.json",
        created_at="2026-06-26T00:00:00Z",
        modes={
            "simple_rag": {"overall": "baseline", "by_category": {}},
            "graph_rag_lite": {
                "overall": "candidate",
                "by_category": {"concept_relation": "candidate"},
            },
        },
    )
    headers = _login(client, email="admin@example.com")

    response = client.get("/api/admin/rag-route-readiness", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "available": True,
        "policy_version": "rag-policy-v1",
        "fixture_version": "rag_eval_set.json",
        "created_at": "2026-06-26T00:00:00Z",
        "modes": {
            "simple_rag": {"overall": "baseline", "by_category": {}},
            "graph_rag_lite": {
                "overall": "candidate",
                "by_category": {"concept_relation": "candidate"},
            },
        },
    }
    serialized = response.text
    for forbidden in ["query", "answer", "chunk", "snippet", "prompt", "token"]:
        assert forbidden not in serialized


def test_admin_readiness_filters_unsafe_snapshot_fields(tmp_path: Path):
    client, _service, Session = _client(tmp_path)
    _create_user(
        Session,
        user_id="admin-1",
        email="admin@example.com",
        role="admin",
    )
    client.app.state.rag_readiness_provider = lambda: RAGReadinessSnapshot(
        policy_version="rag-policy-v1",
        fixture_version="rag_eval_set.json",
        modes={
            "graph_rag_lite": {
                "overall": "candidate",
                "by_category": {
                    "concept_relation": "candidate",
                    "unknown_private": "raw answer content",
                },
                "content": "raw chunk content",
                "snippet": "source snippet",
                "prompt": "hidden prompt",
                "token": "secret-token",
            },
            "unknown_mode": {
                "overall": "candidate",
                "content": "raw query text",
            },
        },
    )
    headers = _login(client, email="admin@example.com")

    response = client.get("/api/admin/rag-route-readiness", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["modes"] == {
        "graph_rag_lite": {
            "overall": "candidate",
            "by_category": {"concept_relation": "candidate"},
        }
    }
    serialized = response.text
    for forbidden in [
        "raw chunk content",
        "source snippet",
        "hidden prompt",
        "secret-token",
        "raw query text",
        "raw answer content",
        "unknown_mode",
        "unknown_private",
    ]:
        assert forbidden not in serialized


def test_admin_can_read_unavailable_rag_route_readiness(tmp_path: Path):
    client, _service, Session = _client(tmp_path)
    _create_user(
        Session,
        user_id="admin-1",
        email="admin@example.com",
        role="admin",
    )
    headers = _login(client, email="admin@example.com")

    response = client.get("/api/admin/rag-route-readiness", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"available": False, "modes": {}}


def test_admin_can_simulate_policy_without_raw_query_in_response(tmp_path: Path):
    client, _service, Session = _client(tmp_path)
    _create_user(
        Session,
        user_id="admin-1",
        email="admin@example.com",
        role="admin",
    )
    headers = _login(client, email="admin@example.com")
    raw_query = "学习积分前需要掌握什么？ secret-token"

    response = client.post(
        "/api/admin/rag-route-policy/simulate",
        headers=headers,
        json={"query": raw_query, "budget": "balanced"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["selected_mode"] in {"simple_rag", "graph_rag_lite", "agentic_rag"}
    assert payload["router_mode"] == "graph_rag_lite"
    assert payload["category"] == "learning_path"
    serialized = response.text
    assert "query" not in payload
    assert raw_query not in serialized
    assert "secret-token" not in serialized


def test_admin_simulate_policy_rejects_empty_query(tmp_path: Path):
    client, _service, Session = _client(tmp_path)
    _create_user(
        Session,
        user_id="admin-1",
        email="admin@example.com",
        role="admin",
    )
    headers = _login(client, email="admin@example.com")

    response = client.post(
        "/api/admin/rag-route-policy/simulate",
        headers=headers,
        json={"query": "   "},
    )

    assert response.status_code == 422


def test_admin_simulate_policy_rejects_invalid_index_status_shape(tmp_path: Path):
    client, _service, Session = _client(tmp_path)
    _create_user(
        Session,
        user_id="admin-1",
        email="admin@example.com",
        role="admin",
    )
    headers = _login(client, email="admin@example.com")

    response = client.post(
        "/api/admin/rag-route-policy/simulate",
        headers=headers,
        json={
            "query": "学习积分前需要掌握什么？",
            "index_statuses": {"doc-1": "indexed"},
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "index_statuses must map document ids to objects"
