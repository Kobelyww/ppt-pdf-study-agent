from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.app import create_app
from src.db.models import AuditEventRecord, Base, Document, DocumentArtifactRecord, UserRecord
from src.security.auth import hash_password
from src.services.rag_router import RetrievalMode
from src.services.rag_service import Chunk
from src.services.study_agent import (
    EvidenceBundle,
    StudyAgentResult,
    StudyDraft,
    StudyPlan,
    StudyRequest,
    StudyTarget,
    StudyVerification,
)


@dataclass
class FakeStudyAgentOrchestrator:
    payloads: list[dict]

    async def run(self, payload: dict) -> StudyAgentResult:
        self.payloads.append(payload)
        request = StudyRequest(query=payload["query"], target=StudyTarget.ANSWER)
        evidence = EvidenceBundle(
            mode=RetrievalMode.SIMPLE,
            chunks=(Chunk(content="导数描述函数的变化率。", source="calculus:derivative"),),
            sources=("calculus:derivative",),
            concept_ids=("kp-derivative",),
            confidence=0.8,
            reason="simple token-overlap retrieval",
        )
        return StudyAgentResult(
            request=request,
            plan=StudyPlan(
                mode=RetrievalMode.SIMPLE,
                reason="definition or direct lookup query",
                steps=("retrieve_chunks",),
                estimated_cost="low",
            ),
            evidence=evidence,
            draft=StudyDraft(
                target=StudyTarget.ANSWER,
                content="导数描述函数的变化率。",
                citations=("calculus:derivative",),
                used_chunk_count=1,
            ),
            verification=StudyVerification(
                passed=True,
                needs_review=False,
                confidence=0.8,
                issues=(),
                source_recall=1.0,
                answer_term_recall=1.0,
            ),
            audit_metadata={
                "mode": "simple_rag",
                "target": "answer",
                "needs_review": False,
                "source_count": 1,
                "chunk_count": 1,
            },
        )


@dataclass
class FailingStudyAgentOrchestrator:
    async def run(self, payload: dict) -> StudyAgentResult:
        raise ValueError("bad study request")


def _session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        session.add(
            UserRecord(
                id="user-1",
                email="user@example.com",
                password_hash=hash_password("password-123"),
                role="user",
                is_active=True,
            )
        )
        session.commit()
    return Session


def _client(tmp_path: Path):
    Session = _session_factory()
    orchestrator = FakeStudyAgentOrchestrator(payloads=[])
    app = create_app(
        session_factory=Session,
        secret_key="test-secret",
        allow_dev_user_header=False,
        study_agent_orchestrator=orchestrator,
    )
    return TestClient(app), orchestrator, Session


def _login(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"email": "user@example.com", "password": "password-123"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_study_agent_query_requires_authentication(tmp_path: Path):
    client, _orchestrator, _Session = _client(tmp_path)

    response = client.post("/api/study-agent/query", json={"query": "什么是导数？"})

    assert response.status_code == 401


def test_study_agent_query_returns_trace_payload(tmp_path: Path):
    client, orchestrator, _Session = _client(tmp_path)
    headers = _login(client)

    response = client.post(
        "/api/study-agent/query",
        json={"query": "什么是导数？", "expected_terms": ["变化率"]},
        headers={**headers, "x-request-id": "req-study-1"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["request"]["query"] == "什么是导数？"
    assert payload["plan"]["mode"] == "simple_rag"
    assert payload["evidence"]["sources"] == ["calculus:derivative"]
    assert payload["draft"]["citations"] == ["calculus:derivative"]
    assert payload["verification"]["passed"] is True
    assert orchestrator.payloads == [
        {
            "query": "什么是导数？",
            "expected_terms": ["变化率"],
            "authenticated_user_id": "user-1",
            "request_id": "req-study-1",
        }
    ]


def test_study_agent_query_uses_authenticated_user_context(tmp_path: Path):
    client, orchestrator, _Session = _client(tmp_path)
    headers = _login(client)

    response = client.post(
        "/api/study-agent/query",
        json={
            "query": "什么是导数？",
            "user_id": "attacker",
            "owner_id": "attacker",
            "created_by": "attacker",
        },
        headers={**headers, "x-request-id": "req-study-2"},
    )

    assert response.status_code == 200
    assert orchestrator.payloads == [
        {
            "query": "什么是导数？",
            "authenticated_user_id": "user-1",
            "request_id": "req-study-2",
        }
    ]


def test_study_agent_query_validates_payload(tmp_path: Path):
    client, _orchestrator, _Session = _client(tmp_path)
    headers = _login(client)

    response = client.post(
        "/api/study-agent/query",
        json={"query": "   "},
        headers=headers,
    )

    assert response.status_code == 422


def test_study_agent_query_persists_sanitized_audit_event(tmp_path: Path):
    client, _orchestrator, Session = _client(tmp_path)
    headers = _login(client)

    response = client.post(
        "/api/study-agent/query",
        json={
            "query": "什么是导数？",
            "target": "answer",
            "document_ids": ["doc-allowed"],
        },
        headers={**headers, "x-request-id": "req-study-audit"},
    )

    assert response.status_code == 200
    with Session() as session:
        events = session.query(AuditEventRecord).all()

    assert len(events) == 1
    event = events[0]
    assert event.actor_id == "user-1"
    assert event.action == "study_agent.query"
    assert event.resource_type == "study_agent"
    assert event.resource_id == "req-study-audit"
    assert event.request_id == "req-study-audit"
    assert event.event_metadata["mode"] == "simple_rag"
    assert event.event_metadata["target"] == "answer"
    assert event.event_metadata["needs_review"] is False
    assert event.event_metadata["source_count"] == 1
    assert event.event_metadata["chunk_count"] == 1
    assert event.event_metadata["document_count"] == 1
    assert "query" not in event.event_metadata
    assert "content" not in event.event_metadata
    assert "sources" not in event.event_metadata
    assert "chunks" not in event.event_metadata


def test_study_agent_query_returns_503_without_orchestrator(tmp_path: Path):
    app = create_app(
        secret_key="test-secret",
        allow_dev_user_header=True,
    )
    client = TestClient(app)

    response = client.post(
        "/api/study-agent/query",
        json={"query": "什么是导数？"},
        headers={"x-user-id": "user-1"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Study agent is not configured"


def test_study_agent_query_maps_value_error_to_422(tmp_path: Path):
    Session = _session_factory()
    app = create_app(
        session_factory=Session,
        secret_key="test-secret",
        allow_dev_user_header=False,
        study_agent_orchestrator=FailingStudyAgentOrchestrator(),
    )
    client = TestClient(app)
    headers = _login(client)

    response = client.post(
        "/api/study-agent/query",
        json={"query": "什么是导数？"},
        headers=headers,
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "bad study request"


def _runtime_client():
    Session = _session_factory()
    app = create_app(
        session_factory=Session,
        secret_key="test-secret",
        allow_dev_user_header=False,
    )
    return TestClient(app), Session


def _insert_study_document(
    Session,
    *,
    document_id: str,
    owner_id: str,
    status: str = "ready",
    content: str | None = "Derivatives measure instantaneous rate of change.",
) -> None:
    now = datetime.now(timezone.utc)
    with Session() as session:
        session.add(
            Document(
                id=document_id,
                owner_id=owner_id,
                title="Calculus Notes",
                source_type="pdf",
                storage_uri=f"local://uploads/{document_id}.pdf",
                content_hash=f"hash-{document_id}",
                original_filename=f"{document_id}.pdf",
                status=status,
                created_at=now,
                updated_at=now,
            )
        )
        if content is not None:
            session.add(
                DocumentArtifactRecord(
                    id=f"artifact-{document_id}",
                    document_id=document_id,
                    artifact_type="normalized_document",
                    content=content,
                    artifact_metadata={"source": "api-test"},
                    created_at=now,
                )
            )
        session.commit()


def test_study_agent_query_uses_default_runtime_when_orchestrator_is_not_injected():
    client, Session = _runtime_client()
    _insert_study_document(Session, document_id="doc-study", owner_id="user-1")
    headers = _login(client)

    response = client.post(
        "/api/study-agent/query",
        json={
            "query": "What do derivatives measure?",
            "target": "answer",
            "document_ids": ["doc-study"],
            "expected_terms": ["rate"],
        },
        headers={**headers, "x-request-id": "req-study-runtime"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["evidence"]["sources"] == ["document:doc-study:chunk:0"]
    assert payload["evidence"]["chunks"][0]["metadata"]["owner_id"] == "user-1"
    assert payload["evidence"]["chunks"][0]["metadata"]["document_id"] == "doc-study"
    assert payload["verification"]["needs_review"] is False


def test_study_agent_default_runtime_requires_document_ids():
    client, _Session = _runtime_client()
    headers = _login(client)

    response = client.post(
        "/api/study-agent/query",
        json={"query": "What do derivatives measure?"},
        headers=headers,
    )

    assert response.status_code == 422
    assert "explicit document selection" in response.json()["detail"]


def test_study_agent_default_runtime_hides_cross_user_document():
    client, Session = _runtime_client()
    _insert_study_document(Session, document_id="doc-private", owner_id="user-2")
    headers = _login(client)

    response = client.post(
        "/api/study-agent/query",
        json={
            "query": "What do derivatives measure?",
            "document_ids": ["doc-private"],
        },
        headers=headers,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Selected document is unavailable to the current user."


def test_study_agent_default_runtime_rejects_non_ready_document():
    client, Session = _runtime_client()
    _insert_study_document(
        Session,
        document_id="doc-processing",
        owner_id="user-1",
        status="processing",
    )
    headers = _login(client)

    response = client.post(
        "/api/study-agent/query",
        json={
            "query": "What do derivatives measure?",
            "document_ids": ["doc-processing"],
        },
        headers=headers,
    )

    assert response.status_code == 422
    assert "must finish processing" in response.json()["detail"]


def test_study_agent_default_runtime_rejects_ready_document_without_artifact():
    client, Session = _runtime_client()
    _insert_study_document(
        Session,
        document_id="doc-no-artifact",
        owner_id="user-1",
        content=None,
    )
    headers = _login(client)

    response = client.post(
        "/api/study-agent/query",
        json={
            "query": "What do derivatives measure?",
            "document_ids": ["doc-no-artifact"],
        },
        headers=headers,
    )

    assert response.status_code == 422
    assert "Processed document evidence is unavailable" in response.json()["detail"]
