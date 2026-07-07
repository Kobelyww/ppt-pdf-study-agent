from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.app import create_app
from src.db import StudyAgentRunRecord, StudyAgentTraceRecord
from src.db.models import (
    AuditEventRecord,
    Base,
    Document,
    DocumentArtifactRecord,
    DocumentChunkRecord,
    ReviewTaskRecord,
    StudyAgentMemoryRecord,
    UserRecord,
)
from src.security.auth import hash_password
from src.services.document_service import DocumentService
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
from src.services.study_agent_memory import StudyAgentMemoryService
from src.services.study_agent_workflow import new_workflow_id
from src.storage.backend import LocalStorageBackend


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
        result = StudyAgentResult(
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
        return result


@dataclass
class FailingStudyAgentOrchestrator:
    async def run(self, payload: dict) -> StudyAgentResult:
        raise ValueError("bad study request")


@dataclass
class SensitiveFailingStudyAgentOrchestrator:
    async def run(self, payload: dict) -> StudyAgentResult:
        raise ValueError(
            "raw private query 什么是导数？ token sk-secret-token path /Users/private.pdf"
        )


@dataclass
class SensitivePolicyStudyAgentOrchestrator:
    async def run(self, payload: dict) -> StudyAgentResult:
        request = StudyRequest(query=payload["query"], target=StudyTarget.ANSWER)
        evidence = EvidenceBundle(
            mode=RetrievalMode.SIMPLE,
            chunks=(Chunk(content="导数描述函数的变化率。", source="calculus:derivative"),),
            sources=("calculus:derivative",),
            concept_ids=("kp-derivative",),
            confidence=0.8,
            reason="simple token-overlap retrieval",
        )
        result = StudyAgentResult(
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
                "policy": {
                    "selected_mode": "simple_rag",
                    "router_mode": "simple_rag",
                    "status": "allowed",
                    "reason": "用户问：什么是导数？",
                    "blocked_reason": "raw chunk: 导数描述函数的变化率。",
                    "fallback_chain": ["simple_rag", "secret-token"],
                    "policy_version": "rag-policy-v1",
                },
            },
        )
        return result


@dataclass
class SensitiveSkillStudyAgentOrchestrator:
    async def run(self, payload: dict) -> StudyAgentResult:
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
                "skill": {
                    "skill_name": "concept_explanation",
                    "skill_version": "v1",
                    "supported_targets": ["answer"],
                    "allowed_retrieval_modes": ["simple_rag", "graph_rag_lite"],
                    "default_budget": "balanced",
                    "review_gate_profile": "standard",
                    "memory_inputs": ["user_preference", "study_state", "raw prompt"],
                    "memory_outputs": ["skill_performance", "chunk content"],
                    "query": "什么是导数？",
                    "generated_answer": "导数描述函数的变化率。",
                    "chunk_content": "函数变化率原文片段",
                    "prompt": "hidden prompt",
                    "token": "sk-secret-token",
                },
            },
        )


@dataclass
class SensitiveExpertStudyAgentOrchestrator:
    async def run(self, payload: dict) -> StudyAgentResult:
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
                "expert": {
                    "enabled": True,
                    "branch_count": 3,
                    "timeout_count": 1,
                    "failure_count": 1,
                    "fallback_reason": "branch_timeout",
                    "branch_statuses": {
                        "retrieval_expert": "passed",
                        "graph_expert": "timeout",
                        "question_expert": "failed",
                        "raw_prompt_branch": "passed",
                        "synthesis_expert": "contains raw answer",
                    },
                    "query": "raw expert diagnostic query",
                    "generated_answer": "unsafe generated expert answer",
                    "chunk_content": "unsafe expert chunk content",
                    "source_snippet": "unsafe source snippet",
                    "prompt": "hidden expert prompt",
                    "token": "sk-expert-secret-token",
                },
            },
        )


@dataclass
class WorkflowStudyAgentOrchestrator:
    workflow_id: str
    needs_review: bool = False
    review_reason: str = "low_confidence"

    async def run(self, payload: dict) -> StudyAgentResult:
        request = StudyRequest(query=payload["query"], target=StudyTarget.ANSWER)
        evidence = EvidenceBundle(
            mode=RetrievalMode.SIMPLE,
            chunks=(Chunk(content="导数描述函数的变化率。", source="calculus:derivative"),),
            sources=("calculus:derivative",),
            concept_ids=("kp-derivative",),
            confidence=0.8,
            reason="simple token-overlap retrieval",
        )
        result = StudyAgentResult(
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
                passed=not self.needs_review,
                needs_review=self.needs_review,
                confidence=0.42 if self.needs_review else 0.8,
                issues=("low confidence",) if self.needs_review else (),
                source_recall=0.5 if self.needs_review else 1.0,
                answer_term_recall=0.25 if self.needs_review else 1.0,
            ),
            audit_metadata={
                "mode": "simple_rag",
                "target": "answer",
                "needs_review": self.needs_review,
                "source_count": 1,
                "chunk_count": 1,
                "citation_count": 1,
                "issue_count": 1 if self.needs_review else 0,
                "prompt": "hidden prompt",
                "workflow": {
                    "workflow_id": self.workflow_id,
                    "status": "needs_review" if self.needs_review else "completed",
                    "current_stage": "review_gate" if self.needs_review else "trace",
                    "needs_review": self.needs_review,
                    "stage_count": 2,
                    "stages": [
                        {
                            "stage": "intake",
                            "status": "passed",
                            "duration_ms": 1.5,
                            "input_summary": {
                                "workflow_id": self.workflow_id,
                                "query": "什么是导数？",
                                "document_count": 0,
                                "prompt": "hidden prompt",
                            },
                            "output_summary": {
                                "target": "answer",
                                "chunk_content": "导数原文",
                            },
                        },
                        {
                            "stage": "review_gate" if self.needs_review else "retrieve",
                            "status": "needs_review" if self.needs_review else "passed",
                            "duration_ms": 3.0,
                            "input_summary": {"selected_mode": "simple_rag"},
                            "output_summary": {
                                "chunk_count": 1,
                                "source_count": 1,
                                "chunk_content": "导数原文",
                                "token": "sk-secret-token",
                            },
                        },
                    ],
                },
            },
        )
        if self.needs_review:
            workflow = result.audit_metadata["workflow"]
            workflow["stages"][1]["review_reason"] = self.review_reason
            workflow["stages"][1]["output_summary"].update(
                {
                    "needs_review": True,
                    "review_reason": self.review_reason,
                    "confidence": 0.42,
                    "source_recall": 0.5,
                    "answer_term_recall": 0.25,
                    "citation_count": 1,
                    "issue_count": 1,
                }
            )
        return result


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
    document_service = DocumentService(
        session_factory=Session,
        storage=LocalStorageBackend(tmp_path / "storage"),
    )
    app = create_app(
        document_service=document_service,
        session_factory=Session,
        secret_key="test-secret",
        allow_dev_user_header=False,
        study_agent_orchestrator=orchestrator,
    )
    return TestClient(app), orchestrator, Session, document_service


def _login(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"email": "user@example.com", "password": "password-123"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _login_admin(client: TestClient, Session) -> dict[str, str]:
    with Session() as session:
        session.add(
            UserRecord(
                id="admin-1",
                email="admin@example.com",
                password_hash=hash_password("password-123"),
                role="admin",
                is_active=True,
            )
        )
        session.commit()
    response = client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "password-123"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _login_other(client: TestClient, Session) -> dict[str, str]:
    with Session() as session:
        session.add(
            UserRecord(
                id="user-2",
                email="other@example.com",
                password_hash=hash_password("password-123"),
                role="user",
                is_active=True,
            )
        )
        session.commit()
    response = client.post(
        "/api/auth/login",
        json={"email": "other@example.com", "password": "password-123"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _insert_ready_document_for_api(
    Session, *, document_id: str = "doc-api", owner_id: str = "user-1"
) -> None:
    now = datetime.now(timezone.utc)
    with Session() as session:
        session.add(
            Document(
                id=document_id,
                owner_id=owner_id,
                title="API Notes",
                source_type="pdf",
                storage_uri=f"local://uploads/{document_id}.pdf",
                content_hash=f"hash-{document_id}",
                original_filename=f"{document_id}.pdf",
                status="ready",
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            DocumentArtifactRecord(
                id=f"artifact-{document_id}",
                document_id=document_id,
                artifact_type="normalized_document",
                content="Derivatives measure instantaneous rate of change.",
                artifact_metadata={"source": "api-test"},
                created_at=now,
            )
        )
        session.commit()


def test_document_payload_includes_compact_study_index_status(tmp_path: Path):
    client, _orchestrator, Session, _document_service = _client(tmp_path)
    headers = _login(client)
    _insert_ready_document_for_api(Session)

    response = client.get("/api/documents", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["study_index"] == {
        "document_id": "doc-api",
        "status": "fallback_available",
        "artifact_id": "artifact-doc-api",
        "chunk_count": 0,
        "indexed_at": None,
        "fallback_reason": "persisted_chunks_missing",
    }


def test_reindex_endpoint_indexes_owned_ready_document(tmp_path: Path):
    client, _orchestrator, Session, _document_service = _client(tmp_path)
    headers = _login(client)
    _insert_ready_document_for_api(Session)

    response = client.post("/api/documents/doc-api/study-index/reindex", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["document_id"] == "doc-api"
    assert payload["status"] == "indexed"
    assert payload["artifact_id"] == "artifact-doc-api"
    assert payload["chunk_count"] == 1
    assert payload["fallback_reason"] is None
    with Session() as session:
        chunks = session.query(DocumentChunkRecord).all()
    assert len(chunks) == 1
    assert chunks[0].owner_id == "user-1"


def test_reindex_endpoint_returns_404_for_cross_owner_document(tmp_path: Path):
    client, _orchestrator, Session, _document_service = _client(tmp_path)
    headers = _login(client)
    _insert_ready_document_for_api(Session, document_id="doc-private", owner_id="user-2")

    response = client.post("/api/documents/doc-private/study-index/reindex", headers=headers)

    assert response.status_code == 404


def test_reindex_endpoint_rejects_processing_document(tmp_path: Path):
    client, _orchestrator, Session, _document_service = _client(tmp_path)
    headers = _login(client)
    _insert_ready_document_for_api(
        Session, document_id="doc-processing", owner_id="user-1"
    )
    with Session() as session:
        document = session.get(Document, "doc-processing")
        document.status = "processing"
        session.commit()

    response = client.post("/api/documents/doc-processing/study-index/reindex", headers=headers)

    assert response.status_code == 422


def test_reindex_endpoint_returns_422_when_normalized_artifact_missing(tmp_path: Path):
    client, _orchestrator, Session, _document_service = _client(tmp_path)
    headers = _login(client)
    _insert_study_document(
        Session, document_id="doc-missing-artifact", owner_id="user-1", content=None
    )

    response = client.post(
        "/api/documents/doc-missing-artifact/study-index/reindex",
        headers=headers,
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Processed document evidence is unavailable."


def test_reindex_endpoint_returns_503_without_index_service(tmp_path: Path):
    app = create_app(
        secret_key="test-secret",
        allow_dev_user_header=True,
    )
    client = TestClient(app)

    response = client.post(
        "/api/documents/doc-api/study-index/reindex",
        headers={"x-user-id": "user-1"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Study document index is not configured"


def test_reindex_endpoint_persists_sanitized_audit_metadata(tmp_path: Path):
    client, _orchestrator, Session, _document_service = _client(tmp_path)
    headers = _login(client)
    _insert_ready_document_for_api(Session)

    response = client.post(
        "/api/documents/doc-api/study-index/reindex",
        headers={**headers, "x-request-id": "req-reindex-audit"},
    )

    assert response.status_code == 200
    with Session() as session:
        event = (
            session.query(AuditEventRecord)
            .filter(AuditEventRecord.action == "document.study_index.reindexed")
            .one()
        )

    assert event.actor_id == "user-1"
    assert event.resource_type == "document"
    assert event.resource_id == "doc-api"
    assert event.request_id == "req-reindex-audit"
    assert set(event.event_metadata) == {
        "document_id",
        "artifact_id",
        "chunk_count",
        "index_status",
        "fallback_used",
    }
    assert event.event_metadata == {
        "document_id": "doc-api",
        "artifact_id": "artifact-doc-api",
        "chunk_count": 1,
        "index_status": "indexed",
        "fallback_used": False,
    }
    forbidden = {"content", "query", "sources", "chunks", "token", "password"}
    assert forbidden.isdisjoint(event.event_metadata)


def test_study_agent_query_requires_authentication(tmp_path: Path):
    client, _orchestrator, _Session, _document_service = _client(tmp_path)

    response = client.post("/api/study-agent/query", json={"query": "什么是导数？"})

    assert response.status_code == 401


def test_study_agent_query_returns_trace_payload(tmp_path: Path):
    client, orchestrator, _Session, _document_service = _client(tmp_path)
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
    assert payload["trace"]["trace_id"].startswith("trace-")
    assert payload["trace"]["request_id"] == "req-study-1"
    assert payload["trace"]["selected_mode"] == "simple_rag"
    assert payload["trace"]["chunk_source"] in {"persisted", None}
    assert payload["trace"]["source_count"] == 1
    assert payload["trace"]["used_chunk_count"] == 1
    assert payload["trace"]["latency_ms"] >= 0
    assert orchestrator.payloads == [
        {
            "query": "什么是导数？",
            "expected_terms": ["变化率"],
            "authenticated_user_id": "user-1",
            "request_id": "req-study-1",
        }
    ]


def test_study_agent_run_create_returns_completed_run_without_raw_query(tmp_path: Path):
    client, orchestrator, Session, _document_service = _client(tmp_path)
    headers = _login(client)

    response = client.post(
        "/api/study-agent/runs",
        json={"query": "什么是导数？", "expected_terms": ["变化率"]},
        headers={**headers, "x-request-id": "req-study-run-1"},
    )

    assert response.status_code == 200
    payload = response.json()
    run = payload["run"]
    assert payload["verification"]["passed"] is True
    assert "audit_metadata" not in payload
    assert run["id"].startswith("run-")
    assert run["status"] == "completed"
    assert run["query_hash"].startswith("sha256:")
    assert run["trace_id"].startswith("trace-")
    assert run["result_summary"]["trace_id"] == run["trace_id"]
    assert run["result_summary"]["selected_mode"] == "simple_rag"
    assert "audit_metadata" not in run
    assert "query" not in run
    assert "什么是导数" not in json.dumps(run, ensure_ascii=False)
    assert orchestrator.payloads[-1] == {
        "query": "什么是导数？",
        "expected_terms": ["变化率"],
        "authenticated_user_id": "user-1",
        "request_id": "req-study-run-1",
    }
    with Session() as session:
        record = session.get(StudyAgentRunRecord, run["id"])
        events = (
            session.query(AuditEventRecord)
            .filter(AuditEventRecord.action.in_(
                ["study_agent_run.created", "study_agent_run.completed"]
            ))
            .order_by(AuditEventRecord.action)
            .all()
        )
    assert record is not None
    assert record.owner_id == "user-1"
    assert record.status == "completed"
    assert len(events) == 2
    assert all(event.resource_id == run["id"] for event in events)
    serialized_events = json.dumps(
        [event.event_metadata for event in events], ensure_ascii=False
    )
    assert "什么是导数" not in serialized_events


def test_study_agent_run_create_marks_needs_review_and_reuses_review_task(
    tmp_path: Path,
):
    workflow_id = new_workflow_id()
    Session = _session_factory()
    app = create_app(
        session_factory=Session,
        secret_key="test-secret",
        allow_dev_user_header=False,
        study_agent_orchestrator=WorkflowStudyAgentOrchestrator(
            workflow_id,
            needs_review=True,
        ),
    )
    client = TestClient(app)
    headers = _login(client)

    response = client.post(
        "/api/study-agent/runs",
        json={"query": "什么是导数？"},
        headers={**headers, "x-request-id": "req-study-run-review"},
    )

    assert response.status_code == 200
    payload = response.json()
    run = payload["run"]
    assert run["status"] == "needs_review"
    assert run["workflow_id"] == workflow_id
    assert run["review_task_id"] == payload["review_task"]["id"]
    assert run["result_summary"]["needs_review"] is True
    assert run["result_summary"]["stage_count"] == 2
    with Session() as session:
        records = session.query(ReviewTaskRecord).all()
    assert len(records) == 1
    assert records[0].id == payload["review_task"]["id"]


def test_study_agent_run_create_failure_persists_safe_failed_run_and_audit(
    tmp_path: Path,
):
    Session = _session_factory()
    app = create_app(
        session_factory=Session,
        secret_key="test-secret",
        allow_dev_user_header=False,
        study_agent_orchestrator=SensitiveFailingStudyAgentOrchestrator(),
    )
    client = TestClient(app)
    headers = _login(client)

    response = client.post(
        "/api/study-agent/runs",
        json={"query": "什么是导数？"},
        headers={**headers, "x-request-id": "req-study-run-failed"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "bad_study_request"
    with Session() as session:
        run = session.query(StudyAgentRunRecord).one()
        failed_event = (
            session.query(AuditEventRecord)
            .filter(AuditEventRecord.action == "study_agent_run.failed")
            .one()
        )
    assert run.status == "failed"
    assert run.error_code == "bad_study_request"
    assert run.error_message == "bad_study_request"
    serialized = json.dumps(
        {
            "run": {
                "query_hash": run.query_hash,
                "result_summary": run.result_summary,
                "error_code": run.error_code,
                "error_message": run.error_message,
                "lifecycle_metadata": run.lifecycle_metadata,
            },
            "audit": failed_event.event_metadata,
        },
        ensure_ascii=False,
    )
    for forbidden in [
        "什么是导数",
        "raw private query",
        "sk-secret-token",
        "/Users/private.pdf",
        "token",
        "path",
    ]:
        assert forbidden not in serialized


def test_study_agent_runs_list_is_owner_scoped_and_excludes_archived_by_default(
    tmp_path: Path,
):
    client, _orchestrator, Session, _document_service = _client(tmp_path)
    headers = _login(client)
    other_headers = _login_other(client, Session)

    first = client.post(
        "/api/study-agent/runs",
        json={"query": "owner active run"},
        headers={**headers, "x-request-id": "req-owner-active"},
    ).json()["run"]
    archived = client.post(
        "/api/study-agent/runs",
        json={"query": "owner archived run"},
        headers={**headers, "x-request-id": "req-owner-archived"},
    ).json()["run"]
    other = client.post(
        "/api/study-agent/runs",
        json={"query": "other active run"},
        headers={**other_headers, "x-request-id": "req-other-active"},
    )
    archive_response = client.post(
        f"/api/study-agent/runs/{archived['id']}/archive",
        headers=headers,
    )

    assert other.status_code == 200
    assert archive_response.status_code == 200
    active_list = client.get("/api/study-agent/runs", headers=headers)
    archived_list = client.get(
        "/api/study-agent/runs?include_archived=true",
        headers=headers,
    )

    assert active_list.status_code == 200
    assert [run["id"] for run in active_list.json()["runs"]] == [first["id"]]
    archived_ids = {run["id"] for run in archived_list.json()["runs"]}
    assert {first["id"], archived["id"]}.issubset(archived_ids)
    assert other.json()["run"]["id"] not in archived_ids


def test_study_agent_run_detail_returns_403_for_cross_owner_and_404_for_missing(
    tmp_path: Path,
):
    client, _orchestrator, Session, _document_service = _client(tmp_path)
    owner_headers = _login(client)
    other_headers = _login_other(client, Session)
    created = client.post(
        "/api/study-agent/runs",
        json={"query": "owner run"},
        headers=owner_headers,
    ).json()["run"]

    cross_owner = client.get(
        f"/api/study-agent/runs/{created['id']}",
        headers=other_headers,
    )
    missing = client.get(
        "/api/study-agent/runs/run-00000000000000000000000000000000",
        headers=owner_headers,
    )

    assert cross_owner.status_code == 403
    assert cross_owner.json()["detail"] == "Forbidden"
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Run not found"


def test_study_agent_run_controls_change_status_emit_audit_and_conflict(
    tmp_path: Path,
):
    client, _orchestrator, Session, _document_service = _client(tmp_path)
    headers = _login(client)
    other_headers = _login_other(client, Session)
    with Session() as session:
        session.add_all(
            [
                StudyAgentRunRecord(
                    id="run-" + "1" * 32,
                    owner_id="user-1",
                    request_id="req-control-cancel",
                    status="queued",
                    query_hash="sha256:" + "1" * 64,
                    target="answer",
                    document_ids=[],
                    expected_term_count=0,
                    attempt=1,
                    result_summary={},
                    lifecycle_metadata={},
                ),
                StudyAgentRunRecord(
                    id="run-" + "2" * 32,
                    owner_id="user-1",
                    request_id="req-control-pause",
                    status="queued",
                    query_hash="sha256:" + "2" * 64,
                    target="answer",
                    document_ids=[],
                    expected_term_count=0,
                    attempt=1,
                    result_summary={},
                    lifecycle_metadata={},
                ),
            ]
        )
        session.commit()

    cancel = client.post("/api/study-agent/runs/run-" + "1" * 32 + "/cancel", headers=headers)
    pause = client.post("/api/study-agent/runs/run-" + "2" * 32 + "/pause", headers=headers)
    resume = client.post("/api/study-agent/runs/run-" + "2" * 32 + "/resume", headers=headers)
    invalid = client.post("/api/study-agent/runs/run-" + "1" * 32 + "/pause", headers=headers)
    cross_owner = client.post(
        "/api/study-agent/runs/run-" + "2" * 32 + "/cancel",
        headers=other_headers,
    )
    missing = client.post(
        "/api/study-agent/runs/run-00000000000000000000000000000000/cancel",
        headers=headers,
    )
    completed = client.post(
        "/api/study-agent/runs",
        json={"query": "archive me"},
        headers=headers,
    ).json()["run"]
    archive = client.post(
        f"/api/study-agent/runs/{completed['id']}/archive",
        headers=headers,
    )

    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"
    assert pause.status_code == 200
    assert pause.json()["status"] == "paused"
    assert resume.status_code == 200
    assert resume.json()["status"] == "queued"
    assert invalid.status_code == 409
    assert invalid.json()["detail"] == "Invalid run transition"
    assert cross_owner.status_code == 403
    assert missing.status_code == 404
    assert archive.status_code == 200
    assert archive.json()["status"] == "archived"
    with Session() as session:
        actions = {
            event.action
            for event in session.query(AuditEventRecord)
            .filter(AuditEventRecord.action.like("study_agent_run.%"))
            .all()
        }
    assert {
        "study_agent_run.cancel_requested",
        "study_agent_run.pause_requested",
        "study_agent_run.resume_requested",
        "study_agent_run.archived",
    }.issubset(actions)


def test_study_agent_run_retry_creates_child_run_without_raw_stored_query(
    tmp_path: Path,
):
    client, _orchestrator, Session, _document_service = _client(tmp_path)
    headers = _login(client)
    with Session() as session:
        session.add(
            StudyAgentRunRecord(
                id="run-" + "3" * 32,
                owner_id="user-1",
                request_id="req-parent",
                status="failed",
                query_hash="sha256:" + "3" * 64,
                target="answer",
                document_ids=[],
                expected_term_count=0,
                attempt=1,
                result_summary={},
                error_code="bad_study_request",
                error_message="bad_study_request",
                lifecycle_metadata={},
            )
        )
        session.commit()

    response = client.post(
        "/api/study-agent/runs/run-" + "3" * 32 + "/retry",
        json={"query": "Fresh retry query sk-secret-token"},
        headers={**headers, "x-request-id": "req-retry-child"},
    )

    assert response.status_code == 200
    run = response.json()["run"]
    assert run["status"] == "completed"
    assert run["retry_of_run_id"] == "run-" + "3" * 32
    assert run["attempt"] == 2
    assert "fresh retry query" not in json.dumps(run).lower()
    assert "sk-secret-token" not in json.dumps(run)
    with Session() as session:
        child = session.get(StudyAgentRunRecord, run["id"])
        retry_event = (
            session.query(AuditEventRecord)
            .filter(AuditEventRecord.action == "study_agent_run.retry_requested")
            .one()
        )
    assert child.retry_of_run_id == "run-" + "3" * 32
    assert retry_event.resource_id == "run-" + "3" * 32
    assert retry_event.event_metadata["run_id"] == "run-" + "3" * 32
    assert retry_event.event_metadata["child_run_id"] == run["id"]


def test_study_agent_skills_endpoint_returns_safe_registry(tmp_path: Path):
    client, _orchestrator, _Session, _document_service = _client(tmp_path)
    headers = _login(client)

    response = client.get("/api/study-agent/skills", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload[0] == {
        "skill_name": "concept_explanation",
        "skill_version": "v1",
        "supported_targets": ["answer"],
        "allowed_retrieval_modes": ["simple_rag", "graph_rag_lite"],
        "default_budget": "balanced",
        "review_gate_profile": "standard",
        "memory_inputs": ["user_preference", "study_state"],
        "memory_outputs": ["skill_performance"],
    }
    serialized = json.dumps(payload, ensure_ascii=False)
    for forbidden in ["query", "chunk_content", "prompt", "token", "secret"]:
        assert forbidden not in serialized.lower()


def test_skill_performance_endpoint_is_owner_scoped(tmp_path: Path):
    client, _orchestrator, Session, _document_service = _client(tmp_path)
    headers = _login(client)
    with Session() as session:
        session.add_all(
            [
                StudyAgentTraceRecord(
                    id="trace-owner",
                    owner_id="user-1",
                    request_id="req-owner",
                    query_hash="sha256:owner",
                    target="answer",
                    document_ids=["doc-api"],
                    selected_mode="simple_rag",
                    route_reason="safe",
                    estimated_cost="low",
                    fallback_chain=[],
                    chunk_source="persisted",
                    fallback_reason=None,
                    source_count=1,
                    used_chunk_count=1,
                    confidence=0.8,
                    source_recall=1.0,
                    answer_term_recall=1.0,
                    needs_review=False,
                    latency_ms=10,
                    trace_metadata={
                        "skill": {
                            "skill_name": "concept_explanation",
                            "skill_version": "v1",
                        }
                    },
                ),
                StudyAgentTraceRecord(
                    id="trace-other",
                    owner_id="user-2",
                    request_id="req-other",
                    query_hash="sha256:other",
                    target="answer",
                    document_ids=["doc-other"],
                    selected_mode="simple_rag",
                    route_reason="safe",
                    estimated_cost="low",
                    fallback_chain=[],
                    chunk_source="persisted",
                    fallback_reason=None,
                    source_count=1,
                    used_chunk_count=1,
                    confidence=0.1,
                    source_recall=0.1,
                    answer_term_recall=0.1,
                    needs_review=True,
                    latency_ms=10,
                    trace_metadata={
                        "skill": {
                            "skill_name": "practice_question",
                            "skill_version": "v1",
                        }
                    },
                ),
            ]
        )
        session.commit()

    response = client.get("/api/study-agent/skills/performance", headers=headers)

    assert response.status_code == 200
    assert response.json()["skills"][0]["skill_name"] == "concept_explanation"
    serialized = json.dumps(response.json(), ensure_ascii=False)
    assert "user-2" not in serialized
    assert "trace-other" not in serialized


def test_study_agent_query_response_includes_safe_skill_payload():
    app = create_app(
        secret_key="test-secret",
        allow_dev_user_header=True,
        study_agent_orchestrator=SensitiveSkillStudyAgentOrchestrator(),
    )
    client = TestClient(app)

    response = client.post(
        "/api/study-agent/query",
        json={"query": "什么是导数？"},
        headers={"x-user-id": "user-1", "x-request-id": "req-study-sensitive-skill"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["skill"] == {
        "skill_name": "concept_explanation",
        "skill_version": "v1",
        "supported_targets": ["answer"],
        "allowed_retrieval_modes": ["simple_rag", "graph_rag_lite"],
        "default_budget": "balanced",
        "review_gate_profile": "standard",
        "memory_inputs": ["user_preference", "study_state"],
        "memory_outputs": ["skill_performance"],
    }
    serialized = response.text
    serialized_skill = json.dumps(payload["skill"], ensure_ascii=False)
    for value in [
        "函数变化率原文片段",
        "hidden prompt",
        "sk-secret-token",
    ]:
        assert value not in serialized
    for key in ["generated_answer", "chunk_content", "prompt", "token"]:
        assert key not in serialized_skill


def test_study_agent_query_response_includes_safe_expert_payload_only():
    app = create_app(
        secret_key="test-secret",
        allow_dev_user_header=True,
        study_agent_orchestrator=SensitiveExpertStudyAgentOrchestrator(),
    )
    client = TestClient(app)

    response = client.post(
        "/api/study-agent/query",
        json={"query": "什么是导数？"},
        headers={"x-user-id": "user-1", "x-request-id": "req-study-sensitive-expert"},
    )

    assert response.status_code == 200
    payload = response.json()
    expected_expert = {
        "enabled": True,
        "branch_count": 3,
        "timeout_count": 1,
        "failure_count": 1,
        "fallback_reason": "branch_timeout",
        "branch_statuses": {
            "retrieval_expert": "passed",
            "graph_expert": "timeout",
            "question_expert": "failed",
        },
    }
    assert "audit_metadata" not in payload
    assert payload["expert"] == expected_expert
    assert payload["trace"]["expert"] == expected_expert

    serialized = response.text
    serialized_expert_payloads = json.dumps(
        {"expert": payload["expert"], "trace_expert": payload["trace"]["expert"]},
        ensure_ascii=False,
    )
    for value in [
        "raw expert diagnostic query",
        "unsafe generated expert answer",
        "unsafe expert chunk content",
        "unsafe source snippet",
        "hidden expert prompt",
        "sk-expert-secret-token",
        "raw_prompt_branch",
        "contains raw answer",
    ]:
        assert value not in serialized
    for key in [
        "query",
        "generated_answer",
        "chunk_content",
        "source_snippet",
        "prompt",
        "token",
    ]:
        assert key not in serialized_expert_payloads


def test_study_agent_query_unsupported_skill_version_maps_to_422(tmp_path: Path):
    Session = _session_factory()
    app = create_app(
        session_factory=Session,
        secret_key="test-secret",
        allow_dev_user_header=False,
    )
    client = TestClient(app)
    headers = _login(client)
    _insert_ready_document_for_api(Session)

    response = client.post(
        "/api/study-agent/query",
        json={
            "query": "What do derivatives measure?",
            "target": "answer",
            "document_ids": ["doc-api"],
            "skill_name": "concept_explanation",
            "skill_version": "v2",
        },
        headers=headers,
    )

    assert response.status_code == 422
    assert "unsupported skill version" in response.json()["detail"]


def test_study_agent_query_skill_error_omits_raw_requested_values(tmp_path: Path):
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
        json={
            "query": "What do derivatives measure?",
            "target": "answer",
            "document_ids": ["missing-doc"],
            "skill_name": "concept_explanation",
            "skill_version": "sk-secret-token",
        },
        headers=headers,
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail == "unsupported skill version"
    assert "sk-secret-token" not in detail
    assert "Selected document is unavailable" not in detail


def test_study_agent_query_audit_has_not_applied_policy_for_injected_orchestrator(
    tmp_path: Path,
):
    client, _orchestrator, Session, _document_service = _client(tmp_path)
    headers = _login(client)

    response = client.post(
        "/api/study-agent/query",
        json={"query": "什么是导数？"},
        headers={**headers, "x-request-id": "req-study-no-policy"},
    )

    assert response.status_code == 200
    with Session() as session:
        event = (
            session.query(AuditEventRecord)
            .filter(AuditEventRecord.action == "study_agent.query")
            .one()
        )

    assert event.event_metadata["selected_mode"] == "simple_rag"
    assert event.event_metadata["policy_status"] == "not_applied"
    assert "policy" not in event.event_metadata


def test_study_agent_query_response_does_not_expose_raw_audit_metadata_policy():
    app = create_app(
        secret_key="test-secret",
        allow_dev_user_header=True,
        study_agent_orchestrator=SensitivePolicyStudyAgentOrchestrator(),
    )
    client = TestClient(app)

    response = client.post(
        "/api/study-agent/query",
        json={"query": "什么是导数？"},
        headers={"x-user-id": "user-1", "x-request-id": "req-study-sensitive-policy"},
    )

    assert response.status_code == 200
    payload = response.json()
    serialized = response.text
    assert "audit_metadata" not in payload
    assert payload["policy"] == {
        "selected_mode": "simple_rag",
        "router_mode": "simple_rag",
        "status": "allowed",
        "fallback_chain": ["simple_rag"],
        "policy_version": "rag-policy-v1",
    }
    for value in [
        "用户问",
        "raw chunk",
        "secret-token",
    ]:
        assert value not in serialized


def test_memory_summary_endpoint_is_owner_scoped(tmp_path: Path):
    client, _orchestrator, Session, _document_service = _client(tmp_path)
    headers = _login(client)
    with Session() as session:
        session.add_all(
            [
                StudyAgentMemoryRecord(
                    id="memory-user-1",
                    owner_id="user-1",
                    scope_type="user",
                    scope_id="user-1",
                    category="user_preference",
                    key="answer_style",
                    value_json={"value": "concise"},
                    confidence=1.0,
                    source_type="explicit_preference",
                    source_id="source-user-1",
                    privacy_level="safe_metadata",
                ),
                StudyAgentMemoryRecord(
                    id="memory-user-2",
                    owner_id="user-2",
                    scope_type="user",
                    scope_id="user-2",
                    category="user_preference",
                    key="answer_style",
                    value_json={"value": "detailed"},
                    confidence=1.0,
                    source_type="explicit_preference",
                    source_id="source-user-2",
                    privacy_level="safe_metadata",
                ),
            ]
        )
        session.commit()

    response = client.get("/api/study-agent/memories/summary", headers=headers)

    assert response.status_code == 200
    assert response.json() == {
        "preferences": {"answer_style": "concise"},
        "review_reason_counts": {},
        "memory_record_count": 1,
    }
    serialized = json.dumps(response.json(), ensure_ascii=False)
    assert "detailed" not in serialized
    assert "user-2" not in serialized


def test_delete_memory_endpoint_is_owner_scoped(tmp_path: Path):
    client, _orchestrator, Session, _document_service = _client(tmp_path)
    headers = _login(client)
    with Session() as session:
        session.add_all(
            [
                StudyAgentMemoryRecord(
                    id="memory-owned",
                    owner_id="user-1",
                    scope_type="user",
                    scope_id="user-1",
                    category="user_preference",
                    key="answer_style",
                    value_json={"value": "concise"},
                    confidence=1.0,
                    source_type="explicit_preference",
                    source_id="source-owned",
                    privacy_level="safe_metadata",
                ),
                StudyAgentMemoryRecord(
                    id="memory-other",
                    owner_id="user-2",
                    scope_type="user",
                    scope_id="user-2",
                    category="user_preference",
                    key="answer_style",
                    value_json={"value": "detailed"},
                    confidence=1.0,
                    source_type="explicit_preference",
                    source_id="source-other",
                    privacy_level="safe_metadata",
                ),
            ]
        )
        session.commit()

    other_delete = client.delete(
        "/api/study-agent/memories/memory-other",
        headers=headers,
    )
    own_delete = client.delete(
        "/api/study-agent/memories/memory-owned",
        headers=headers,
    )
    summary = client.get("/api/study-agent/memories/summary", headers=headers)

    assert other_delete.status_code == 404
    assert own_delete.status_code == 200
    assert own_delete.json() == {"id": "memory-owned", "status": "deleted"}
    assert summary.status_code == 200
    assert summary.json() == {
        "preferences": {},
        "review_reason_counts": {},
        "memory_record_count": 0,
    }
    with Session() as session:
        assert session.get(StudyAgentMemoryRecord, "memory-other") is not None


def test_study_agent_query_returns_safe_workflow_payload(tmp_path: Path):
    workflow_id = new_workflow_id()
    Session = _session_factory()
    app = create_app(
        session_factory=Session,
        secret_key="test-secret",
        allow_dev_user_header=False,
        study_agent_orchestrator=WorkflowStudyAgentOrchestrator(workflow_id),
    )
    client = TestClient(app)
    headers = _login(client)

    response = client.post(
        "/api/study-agent/query",
        json={"query": "什么是导数？"},
        headers={**headers, "x-request-id": "req-study-workflow"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["workflow"]["workflow_id"] == workflow_id
    assert payload["workflow"]["status"] == "completed"
    assert payload["workflow"]["current_stage"] == "trace"
    assert payload["workflow"]["stage_count"] == 2
    assert payload["workflow"]["stages"][0]["input_summary"] == {
        "workflow_id": workflow_id,
        "document_count": 0,
    }
    assert payload["workflow"]["stages"][0]["output_summary"] == {"target": "answer"}
    assert payload["workflow"]["stages"][1]["output_summary"] == {
        "chunk_count": 1,
        "source_count": 1,
    }
    assert payload["trace"]["workflow"]["workflow_id"] == workflow_id
    serialized = json.dumps(
        {"workflow": payload["workflow"], "trace_workflow": payload["trace"]["workflow"]},
        ensure_ascii=False,
    )
    for value in ["导数原文", "hidden prompt", "sk-secret-token"]:
        assert value not in serialized
    for key in ["chunk_content", "prompt", "token"]:
        assert key not in serialized


def test_study_agent_query_creates_review_task_for_needs_review_workflow(tmp_path: Path):
    workflow_id = new_workflow_id()
    Session = _session_factory()
    app = create_app(
        session_factory=Session,
        secret_key="test-secret",
        allow_dev_user_header=False,
        study_agent_orchestrator=WorkflowStudyAgentOrchestrator(
            workflow_id,
            needs_review=True,
        ),
    )
    client = TestClient(app)
    headers = _login(client)

    response = client.post(
        "/api/study-agent/query",
        json={"query": "什么是导数？"},
        headers={**headers, "x-request-id": "req-study-review-task"},
    )

    assert response.status_code == 200
    payload = response.json()
    review_task = payload["review_task"]
    assert review_task["id"].startswith("review-")
    assert review_task["target_type"] == "study_agent_workflow"
    assert review_task["target_id"] == workflow_id
    assert review_task["status"] == "open"
    assert review_task["reason"] == "low_confidence"
    assert review_task["metadata"]["workflow_id"] == workflow_id
    assert review_task["metadata"]["trace_id"] == payload["trace"]["trace_id"]
    with Session() as session:
        records = session.query(ReviewTaskRecord).all()
    assert len(records) == 1
    assert records[0].owner_id == "user-1"


def test_study_agent_query_reuses_open_review_task_for_duplicate_workflow(tmp_path: Path):
    workflow_id = new_workflow_id()
    Session = _session_factory()
    app = create_app(
        session_factory=Session,
        secret_key="test-secret",
        allow_dev_user_header=False,
        study_agent_orchestrator=WorkflowStudyAgentOrchestrator(
            workflow_id,
            needs_review=True,
        ),
    )
    client = TestClient(app)
    headers = _login(client)

    first = client.post(
        "/api/study-agent/query",
        json={"query": "什么是导数？"},
        headers={**headers, "x-request-id": "req-study-review-task-1"},
    )
    second = client.post(
        "/api/study-agent/query",
        json={"query": "什么是导数？"},
        headers={**headers, "x-request-id": "req-study-review-task-2"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["review_task"]["id"] == first.json()["review_task"]["id"]
    with Session() as session:
        records = session.query(ReviewTaskRecord).all()
    assert len(records) == 1


def test_study_agent_review_task_payloads_and_audit_metadata_are_safe(tmp_path: Path):
    workflow_id = new_workflow_id()
    Session = _session_factory()
    app = create_app(
        session_factory=Session,
        secret_key="test-secret",
        allow_dev_user_header=False,
        study_agent_orchestrator=WorkflowStudyAgentOrchestrator(
            workflow_id,
            needs_review=True,
        ),
    )
    client = TestClient(app)
    headers = _login(client)

    response = client.post(
        "/api/study-agent/query",
        json={"query": "什么是导数？"},
        headers={**headers, "x-request-id": "req-study-review-task-safe"},
    )

    assert response.status_code == 200
    with Session() as session:
        events = (
            session.query(AuditEventRecord)
            .filter(AuditEventRecord.action.in_(["study_agent.query", "review_task.created"]))
            .all()
        )
        task = session.query(ReviewTaskRecord).one()
    serialized = json.dumps(
        {
            "response_review_task": response.json()["review_task"],
            "task_metadata": task.task_metadata,
            "audit_metadata": [event.event_metadata for event in events],
        },
        ensure_ascii=False,
    )
    for forbidden in [
        "什么是导数",
        "导数原文",
        "hidden prompt",
        "sk-secret-token",
        "generated answer",
        "chunk_content",
        "prompt",
        "token",
        "input_summary",
        "output_summary",
    ]:
        assert forbidden not in serialized


def test_study_agent_review_task_ignores_unknown_raw_review_reason(tmp_path: Path):
    workflow_id = new_workflow_id()
    Session = _session_factory()
    app = create_app(
        session_factory=Session,
        secret_key="test-secret",
        allow_dev_user_header=False,
        study_agent_orchestrator=WorkflowStudyAgentOrchestrator(
            workflow_id,
            needs_review=True,
            review_reason="custom_lowercase_reason",
        ),
    )
    client = TestClient(app)
    headers = _login(client)

    response = client.post(
        "/api/study-agent/query",
        json={"query": "什么是导数？"},
        headers={**headers, "x-request-id": "req-study-review-task-unknown-reason"},
    )

    assert response.status_code == 200
    review_task = response.json()["review_task"]
    assert review_task["reason"] == "needs_review"
    assert "review_reasons" not in review_task["metadata"]
    serialized = json.dumps(review_task, ensure_ascii=False)
    for forbidden in [
        "custom_lowercase_reason",
        "导数原文",
        "hidden prompt",
        "sk-secret-token",
        "chunk_content",
        "prompt",
        "token",
    ]:
        assert forbidden not in serialized


def test_review_tasks_list_includes_safe_metadata_and_remains_owner_scoped(
    tmp_path: Path,
):
    workflow_id = new_workflow_id()
    Session = _session_factory()
    with Session() as session:
        session.add(
            UserRecord(
                id="user-2",
                email="other@example.com",
                password_hash=hash_password("password-123"),
                role="user",
                is_active=True,
            )
        )
        session.commit()
    app = create_app(
        session_factory=Session,
        secret_key="test-secret",
        allow_dev_user_header=False,
        study_agent_orchestrator=WorkflowStudyAgentOrchestrator(
            workflow_id,
            needs_review=True,
        ),
    )
    client = TestClient(app)
    owner_headers = _login(client)
    other_login = client.post(
        "/api/auth/login",
        json={"email": "other@example.com", "password": "password-123"},
    )
    assert other_login.status_code == 200
    other_headers = {"Authorization": f"Bearer {other_login.json()['access_token']}"}

    created = client.post(
        "/api/study-agent/query",
        json={"query": "什么是导数？"},
        headers={**owner_headers, "x-request-id": "req-study-review-list"},
    )
    owner_list = client.get("/api/review-tasks", headers=owner_headers)
    other_list = client.get("/api/review-tasks", headers=other_headers)

    assert created.status_code == 200
    assert owner_list.status_code == 200
    assert other_list.status_code == 200
    tasks = owner_list.json()
    assert len(tasks) == 1
    assert tasks[0]["id"] == created.json()["review_task"]["id"]
    assert tasks[0]["metadata"]["workflow_id"] == workflow_id
    assert tasks[0]["metadata"]["review_reasons"] == ["low_confidence"]
    assert tasks[0]["metadata"]["source_count"] == 1
    assert tasks[0]["metadata"]["chunk_count"] == 1
    assert other_list.json() == []
    assert "导数原文" not in owner_list.text


def test_review_tasks_list_sanitizes_persisted_task_metadata(tmp_path: Path):
    client, _orchestrator, Session, _document_service = _client(tmp_path)
    headers = _login(client)
    with Session() as session:
        session.add(
            ReviewTaskRecord(
                id="review-unsafe-metadata",
                owner_id="user-1",
                target_type="study_agent_workflow",
                target_id="workflow-unsafe-list",
                status="open",
                reason="low_confidence",
                task_metadata={
                    "workflow_id": "workflow-unsafe-list",
                    "trace_id": "trace-safe-list",
                    "selected_mode": "simple_rag",
                    "review_reasons": ["low_confidence", "custom_lowercase_reason"],
                    "source_count": 2,
                    "chunk_count": 4,
                    "query": "什么是导数？",
                    "content": "导数原文",
                    "prompt": "hidden prompt",
                    "token": "sk-secret-token",
                    "nested": {"content": "raw nested content"},
                },
            )
        )
        session.commit()

    response = client.get("/api/review-tasks", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    metadata = payload[0]["metadata"]
    assert metadata == {
        "workflow_id": "workflow-unsafe-list",
        "trace_id": "trace-safe-list",
        "selected_mode": "simple_rag",
        "review_reasons": ["low_confidence"],
        "source_count": 2,
        "chunk_count": 4,
    }
    assert payload[0]["task_metadata"] == metadata
    serialized = json.dumps(payload, ensure_ascii=False)
    for forbidden in [
        "什么是导数",
        "导数原文",
        "hidden prompt",
        "sk-secret-token",
        "query",
        "content",
        "prompt",
        "token",
        "nested",
        "custom_lowercase_reason",
    ]:
        assert forbidden not in serialized


def test_review_decision_creates_safe_review_outcome_memory(tmp_path: Path):
    workflow_id = new_workflow_id()
    Session = _session_factory()
    app = create_app(
        session_factory=Session,
        secret_key="test-secret",
        allow_dev_user_header=False,
        study_agent_orchestrator=WorkflowStudyAgentOrchestrator(
            workflow_id,
            needs_review=True,
        ),
    )
    client = TestClient(app)
    headers = _login(client)

    created = client.post(
        "/api/study-agent/query",
        json={"query": "什么是导数？"},
        headers={**headers, "x-request-id": "req-study-memory-review"},
    )
    assert created.status_code == 200
    review_task_id = created.json()["review_task"]["id"]
    decided = client.post(
        f"/api/review-tasks/{review_task_id}/decision",
        json={"decision": "resolved", "comment": "raw reviewer comment sk-secret-token"},
        headers={**headers, "x-request-id": "req-study-memory-decision"},
    )
    summary = client.get("/api/study-agent/memories/summary", headers=headers)

    assert decided.status_code == 200
    assert summary.status_code == 200
    assert summary.json()["review_reason_counts"] == {"low_confidence": 1}
    with Session() as session:
        memory = session.query(StudyAgentMemoryRecord).one()
    assert memory.owner_id == "user-1"
    assert memory.category == "review_outcome"
    assert memory.scope_id == workflow_id
    assert memory.key == review_task_id
    assert memory.value_json == {
        "decision": "resolved",
        "reasons": ["low_confidence"],
        "metrics": {"chunk_count": 1, "confidence": 0.42, "source_count": 1},
    }
    serialized = json.dumps(
        {
            "decision_response": decided.json(),
            "summary": summary.json(),
            "memory_value": memory.value_json,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    for forbidden in [
        "什么是导数",
        "导数原文",
        "hidden prompt",
        "sk-secret-token",
        "raw reviewer comment",
        "query",
        "chunk_content",
        "prompt",
        "token",
        "comment",
        "input_summary",
        "output_summary",
    ]:
        assert forbidden not in serialized


def test_review_decision_memory_is_idempotent_when_task_is_decided_twice(
    tmp_path: Path,
):
    workflow_id = new_workflow_id()
    Session = _session_factory()
    app = create_app(
        session_factory=Session,
        secret_key="test-secret",
        allow_dev_user_header=False,
        study_agent_orchestrator=WorkflowStudyAgentOrchestrator(
            workflow_id,
            needs_review=True,
        ),
    )
    client = TestClient(app)
    headers = _login(client)

    created = client.post(
        "/api/study-agent/query",
        json={"query": "什么是导数？"},
        headers={**headers, "x-request-id": "req-study-memory-idempotent"},
    )
    assert created.status_code == 200
    review_task_id = created.json()["review_task"]["id"]

    first = client.post(
        f"/api/review-tasks/{review_task_id}/decision",
        json={"decision": "resolved", "comment": "first raw comment"},
        headers=headers,
    )
    second = client.post(
        f"/api/review-tasks/{review_task_id}/decision",
        json={"decision": "resolved", "comment": "second raw comment"},
        headers=headers,
    )
    summary = client.get("/api/study-agent/memories/summary", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert summary.json()["review_reason_counts"] == {"low_confidence": 1}
    with Session() as session:
        memories = session.query(StudyAgentMemoryRecord).all()

    assert len(memories) == 1
    assert memories[0].key == review_task_id


def test_review_decision_memory_write_failure_does_not_break_decision(
    tmp_path: Path,
    monkeypatch,
):
    workflow_id = new_workflow_id()
    Session = _session_factory()
    app = create_app(
        session_factory=Session,
        secret_key="test-secret",
        allow_dev_user_header=False,
        study_agent_orchestrator=WorkflowStudyAgentOrchestrator(
            workflow_id,
            needs_review=True,
        ),
    )
    client = TestClient(app)
    headers = _login(client)

    created = client.post(
        "/api/study-agent/query",
        json={"query": "什么是导数？"},
        headers={**headers, "x-request-id": "req-study-memory-runtime-error"},
    )
    assert created.status_code == 200
    review_task_id = created.json()["review_task"]["id"]

    def raise_memory_error(self, **kwargs):
        raise RuntimeError("raw memory backend failure sk-secret-token")

    monkeypatch.setattr(
        StudyAgentMemoryService,
        "store_review_outcome",
        raise_memory_error,
    )
    response = client.post(
        f"/api/review-tasks/{review_task_id}/decision",
        json={"decision": "resolved", "comment": "raw reviewer comment"},
        headers={**headers, "x-request-id": "req-study-memory-runtime-decision"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": review_task_id,
        "status": "decided",
        "decision": "resolved",
    }
    with Session() as session:
        task = session.get(ReviewTaskRecord, review_task_id)
        memory_count = session.query(StudyAgentMemoryRecord).count()
        event = (
            session.query(AuditEventRecord)
            .filter(AuditEventRecord.action == "review_task.decided")
            .one()
        )

    assert task.status == "decided"
    assert task.decision == "resolved"
    assert memory_count == 0
    serialized = json.dumps(
        {"response": response.json(), "audit": event.event_metadata},
        ensure_ascii=False,
    )
    assert "raw memory backend failure" not in serialized
    assert "sk-secret-token" not in serialized
    assert "raw reviewer comment" not in serialized


def test_review_decision_without_safe_reason_does_not_fail_or_write_memory(
    tmp_path: Path,
):
    client, _orchestrator, Session, _document_service = _client(tmp_path)
    headers = _login(client)
    with Session() as session:
        session.add(
            ReviewTaskRecord(
                id="review-legacy-unsafe",
                owner_id="user-1",
                target_type="study_agent_workflow",
                target_id="workflow-legacy-unsafe",
                status="open",
                reason="needs_review",
                task_metadata={
                    "workflow_id": "workflow-legacy-unsafe",
                    "review_reasons": ["custom_lowercase_reason"],
                    "query": "什么是导数？",
                    "content": "导数原文",
                    "prompt": "hidden prompt",
                    "token": "sk-secret-token",
                },
            )
        )
        session.commit()

    response = client.post(
        "/api/review-tasks/review-legacy-unsafe/decision",
        json={"decision": "resolved", "comment": "raw reviewer comment"},
        headers=headers,
    )

    assert response.status_code == 200
    with Session() as session:
        assert session.query(StudyAgentMemoryRecord).count() == 0
    serialized = json.dumps(response.json(), ensure_ascii=False)
    for forbidden in [
        "custom_lowercase_reason",
        "什么是导数",
        "导数原文",
        "hidden prompt",
        "sk-secret-token",
        "raw reviewer comment",
    ]:
        assert forbidden not in serialized


def test_study_agent_workflow_detail_is_owner_scoped(tmp_path: Path):
    workflow_id = new_workflow_id()
    Session = _session_factory()
    with Session() as session:
        session.add(
            UserRecord(
                id="user-2",
                email="other@example.com",
                password_hash=hash_password("password-123"),
                role="user",
                is_active=True,
            )
        )
        session.commit()
    app = create_app(
        session_factory=Session,
        secret_key="test-secret",
        allow_dev_user_header=False,
        study_agent_orchestrator=WorkflowStudyAgentOrchestrator(workflow_id),
    )
    client = TestClient(app)
    owner_headers = _login(client)
    other_login = client.post(
        "/api/auth/login",
        json={"email": "other@example.com", "password": "password-123"},
    )
    assert other_login.status_code == 200
    other_headers = {"Authorization": f"Bearer {other_login.json()['access_token']}"}

    query_response = client.post(
        "/api/study-agent/query",
        json={"query": "什么是导数？"},
        headers={**owner_headers, "x-request-id": "req-study-workflow-detail"},
    )
    assert query_response.status_code == 200
    workflow_id = query_response.json()["workflow"]["workflow_id"]

    owner_detail = client.get(
        f"/api/study-agent/workflows/{workflow_id}",
        headers=owner_headers,
    )
    other_detail = client.get(
        f"/api/study-agent/workflows/{workflow_id}",
        headers=other_headers,
    )

    assert owner_detail.status_code == 200
    assert owner_detail.json()["workflow_id"] == workflow_id
    assert owner_detail.json()["stages"][1]["output_summary"] == {
        "chunk_count": 1,
        "source_count": 1,
    }
    assert other_detail.status_code == 404
    assert "导数原文" not in owner_detail.text


def test_study_agent_workflow_detail_returns_404_for_malformed_workflow_id(
    tmp_path: Path,
):
    client, _orchestrator, _Session, _document_service = _client(tmp_path)
    headers = _login(client)

    response = client.get(
        "/api/study-agent/workflows/workflow-1",
        headers=headers,
    )

    assert response.status_code == 404


def test_study_agent_workflow_detail_returns_503_without_trace_store():
    app = create_app(
        secret_key="test-secret",
        allow_dev_user_header=True,
    )
    client = TestClient(app)

    response = client.get(
        f"/api/study-agent/workflows/{new_workflow_id()}",
        headers={"x-user-id": "user-1"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Study agent trace store is not configured"


def test_trace_detail_api_returns_owner_scoped_safe_trace(tmp_path: Path):
    client, _orchestrator, _Session, _document_service = _client(tmp_path)
    headers = _login(client)
    response = client.post(
        "/api/study-agent/query",
        json={"query": "什么是导数？", "target": "answer"},
        headers={**headers, "x-request-id": "req-trace-detail"},
    )
    trace_id = response.json()["trace"]["trace_id"]

    detail = client.get(f"/api/study-agent/traces/{trace_id}", headers=headers)

    assert detail.status_code == 200
    payload = detail.json()
    assert payload["trace_id"] == trace_id
    assert payload["query_hash"].startswith("sha256:")
    serialized = str(payload)
    assert "什么是导数" not in serialized
    assert "导数描述" not in serialized


def test_index_summary_api_returns_owner_scoped_counts(tmp_path: Path):
    client, _orchestrator, _Session, _document_service = _client(tmp_path)
    headers = _login(client)

    response = client.get("/api/study-agent/index-summary", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["owner_id"] == "user-1"
    assert "status_counts" in payload
    assert "fallback_reason_counts" in payload


def test_admin_rag_evaluation_api_requires_admin_role(tmp_path: Path):
    client, _orchestrator, _Session, _document_service = _client(tmp_path)
    headers = _login(client)

    response = client.post(
        "/api/admin/rag-evaluations",
        json={"modes": ["simple_rag"]},
        headers=headers,
    )

    assert response.status_code == 403


def test_admin_rag_evaluation_api_creates_run(tmp_path: Path):
    client, _orchestrator, Session, _document_service = _client(tmp_path)
    headers = _login_admin(client, Session)

    response = client.post(
        "/api/admin/rag-evaluations",
        json={"modes": ["simple_rag"]},
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"].startswith("eval-run-")
    assert payload["modes"] == ["simple_rag"]
    assert payload["case_count"] == 9
    assert "summary" in payload
    assert "readiness" in payload


def test_admin_rag_evaluation_api_gets_run_metadata_and_requires_admin(tmp_path: Path):
    client, _orchestrator, Session, _document_service = _client(tmp_path)
    admin_headers = _login_admin(client, Session)
    user_headers = _login(client)

    created = client.post(
        "/api/admin/rag-evaluations",
        json={},
        headers=admin_headers,
    )
    assert created.status_code == 200
    run_id = created.json()["id"]

    response = client.get(
        f"/api/admin/rag-evaluations/{run_id}",
        headers=admin_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == run_id
    assert payload["status"] == "completed"
    assert payload["created_by"] == "admin-1"
    assert payload["case_count"] == 9
    assert payload["summary"]
    assert "readiness" in payload
    assert payload["report_uri"]

    forbidden = client.get(
        f"/api/admin/rag-evaluations/{run_id}",
        headers=user_headers,
    )
    assert forbidden.status_code == 403


def test_admin_rag_evaluation_api_stores_report_in_configured_storage(
    tmp_path: Path,
):
    client, _orchestrator, Session, document_service = _client(tmp_path)
    headers = _login_admin(client, Session)

    response = client.post(
        "/api/admin/rag-evaluations",
        json={"report_dir": str(tmp_path / "reports")},
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["report_uri"].startswith("local://")
    assert not (tmp_path / "reports").exists()
    report = document_service.storage.read_bytes(payload["report_uri"]).decode("utf-8")
    assert "Mode Comparison" in report


def test_study_agent_query_returns_compact_unpersisted_trace_without_session_factory():
    orchestrator = FakeStudyAgentOrchestrator(payloads=[])
    app = create_app(
        secret_key="test-secret",
        allow_dev_user_header=True,
        study_agent_orchestrator=orchestrator,
    )
    client = TestClient(app)

    response = client.post(
        "/api/study-agent/query",
        json={"query": "什么是导数？"},
        headers={"x-user-id": "user-1", "x-request-id": "req-study-unpersisted"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert {"request", "plan", "evidence", "draft", "verification"}.issubset(payload)
    trace = payload["trace"]
    assert trace["trace_id"] == "trace-unpersisted"
    assert trace["request_id"] == "req-study-unpersisted"
    assert trace["selected_mode"] == "simple_rag"
    assert trace["route_reason"] == "definition or direct lookup query"
    assert trace["chunk_source"] is None
    assert trace["fallback_reason"] is None
    assert trace["document_count"] == 0
    assert trace["source_count"] == 1
    assert trace["used_chunk_count"] == 1
    assert trace["confidence"] == 0.8
    assert trace["source_recall"] == 1.0
    assert trace["answer_term_recall"] == 1.0
    assert trace["needs_review"] is False
    assert trace["latency_ms"] >= 0
    assert set(trace) == {
        "trace_id",
        "request_id",
        "selected_mode",
        "route_reason",
        "chunk_source",
        "fallback_reason",
        "document_count",
        "source_count",
        "used_chunk_count",
        "confidence",
        "source_recall",
        "answer_term_recall",
        "needs_review",
        "latency_ms",
    }
    assert {
        "query_hash",
        "target",
        "document_ids",
        "estimated_cost",
        "fallback_chain",
        "created_at",
    }.isdisjoint(trace)
    assert orchestrator.payloads == [
        {
            "query": "什么是导数？",
            "authenticated_user_id": "user-1",
            "request_id": "req-study-unpersisted",
        }
    ]


def test_study_agent_query_uses_authenticated_user_context(tmp_path: Path):
    client, orchestrator, _Session, _document_service = _client(tmp_path)
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
    client, _orchestrator, _Session, _document_service = _client(tmp_path)
    headers = _login(client)

    response = client.post(
        "/api/study-agent/query",
        json={"query": "   "},
        headers=headers,
    )

    assert response.status_code == 422


def test_study_agent_query_persists_sanitized_audit_event(tmp_path: Path):
    client, Session = _runtime_client()
    _insert_study_document(
        Session,
        document_id="doc-allowed",
        owner_id="user-1",
        content="导数描述函数变化率。",
    )
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
    assert set(event.event_metadata) == {
        "trace_id",
        "policy_version",
        "category",
        "router_mode",
        "selected_mode",
        "policy_status",
        "needs_review",
        "fallback_reason",
        "latency_ms",
    }
    assert event.event_metadata["policy_version"] == "rag-policy-v1"
    assert event.event_metadata["category"] == "definition"
    assert event.event_metadata["router_mode"] == "simple_rag"
    assert event.event_metadata["selected_mode"] == "simple_rag"
    assert event.event_metadata["policy_status"] == "allowed"
    assert event.event_metadata["needs_review"] is False
    assert event.event_metadata["trace_id"].startswith("trace-")
    assert "fallback_reason" in event.event_metadata
    assert "latency_ms" in event.event_metadata
    assert "policy" not in event.event_metadata
    assert "mode" not in event.event_metadata
    assert "target" not in event.event_metadata
    assert "source_count" not in event.event_metadata
    assert "chunk_count" not in event.event_metadata
    assert "document_count" not in event.event_metadata
    assert "chunk_source" not in event.event_metadata
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


def test_study_agent_query_returns_runtime_policy_diagnostics():
    client, Session = _runtime_client()
    _insert_study_document(
        Session,
        document_id="doc-policy",
        owner_id="user-1",
        content="Derivatives and integrals are connected by the fundamental theorem.",
    )
    headers = _login(client)

    response = client.post(
        "/api/study-agent/query",
        json={
            "query": "Explain the relationship between derivatives and integrals",
            "target": "answer",
            "document_ids": ["doc-policy"],
        },
        headers={**headers, "x-request-id": "req-study-policy"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert "policy" in payload
    assert payload["policy"]["selected_mode"] in {
        "simple_rag",
        "graph_rag_lite",
        "agentic_rag",
    }
    assert "query" not in payload["policy"]
    assert payload["trace"]["policy"] == payload["policy"]


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
