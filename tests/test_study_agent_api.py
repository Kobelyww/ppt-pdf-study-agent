from dataclasses import dataclass
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.app import create_app
from src.db.models import Base, UserRecord
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
    return TestClient(app), orchestrator


def _login(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"email": "user@example.com", "password": "password-123"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_study_agent_query_requires_authentication(tmp_path: Path):
    client, _orchestrator = _client(tmp_path)

    response = client.post("/api/study-agent/query", json={"query": "什么是导数？"})

    assert response.status_code == 401


def test_study_agent_query_returns_trace_payload(tmp_path: Path):
    client, orchestrator = _client(tmp_path)
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
    client, orchestrator = _client(tmp_path)
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
    client, _orchestrator = _client(tmp_path)
    headers = _login(client)

    response = client.post(
        "/api/study-agent/query",
        json={"query": "   "},
        headers=headers,
    )

    assert response.status_code == 422


def test_study_agent_query_returns_503_without_orchestrator(tmp_path: Path):
    Session = _session_factory()
    app = create_app(
        session_factory=Session,
        secret_key="test-secret",
        allow_dev_user_header=False,
    )
    client = TestClient(app)
    headers = _login(client)

    response = client.post(
        "/api/study-agent/query",
        json={"query": "什么是导数？"},
        headers=headers,
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
