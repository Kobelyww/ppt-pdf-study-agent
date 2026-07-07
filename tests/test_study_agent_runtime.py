from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base, Document, DocumentArtifactRecord, DocumentChunkRecord
from src.services.agentic_rag import AgenticRAGPlanner
from src.services.rag_route_policy import (
    RAGReadinessSnapshot,
    RAGRoutePolicyConfig,
    RAGRoutePolicyService,
)
from src.services.rag_router import RetrievalMode
from src.services.study_agent_experts import ExpertCollaborationConfig
from src.services.study_agent_documents import StudyAgentDocumentError, StudyDocumentChunker
from src.services.study_agent_index import StudyDocumentIndexService
from src.services.study_agent_runtime import StudyAgentRuntimeService


def _session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _insert_ready_document_with_artifact(
    Session,
    *,
    document_id: str = "doc-study",
    owner_id: str = "user-1",
    content: str = "Derivatives measure instantaneous rate of change.",
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
                content=content,
                artifact_metadata={"source": "test"},
                created_at=now,
            )
        )
        session.commit()


def _insert_persisted_chunk(
    Session,
    *,
    document_id: str = "doc-study",
    owner_id: str = "user-1",
    artifact_id: str = "artifact-doc-study",
    content: str = "Persisted derivatives evidence.",
) -> None:
    with Session() as session:
        session.add(
            DocumentChunkRecord(
                id=f"chunk-{document_id}",
                owner_id=owner_id,
                document_id=document_id,
                artifact_id=artifact_id,
                chunk_index=0,
                chunk_count=1,
                source=f"document:{document_id}:chunk:0",
                content=content,
                chunk_metadata={
                    "owner_id": owner_id,
                    "document_id": document_id,
                    "document_title": "Calculus Notes",
                    "artifact_id": artifact_id,
                    "artifact_type": "normalized_document",
                    "chunk_index": 0,
                    "chunk_count": 1,
                    "source_kind": "persisted_document_chunk",
                },
                content_hash=f"hash-{document_id}",
            )
        )
        session.commit()


def _insert_persisted_chunk_with_concept(
    Session,
    *,
    document_id: str = "doc-study",
    owner_id: str = "user-1",
    artifact_id: str | None = None,
    content: str = "Persisted derivatives evidence.",
    concept_id: str = "derivative",
    chunk_index: int = 0,
    chunk_count: int = 1,
    source: str | None = None,
) -> None:
    artifact_id = artifact_id or f"artifact-{document_id}"
    source = source or f"document:{document_id}:chunk:{chunk_index}"
    with Session() as session:
        session.add(
            DocumentChunkRecord(
                id=f"chunk-{owner_id}-{document_id}-{chunk_index}",
                owner_id=owner_id,
                document_id=document_id,
                artifact_id=artifact_id,
                chunk_index=chunk_index,
                chunk_count=chunk_count,
                source=source,
                content=content,
                chunk_metadata={
                    "owner_id": owner_id,
                    "document_id": document_id,
                    "document_title": "Calculus Notes",
                    "artifact_id": artifact_id,
                    "artifact_type": "normalized_document",
                    "chunk_index": chunk_index,
                    "chunk_count": chunk_count,
                    "source_kind": "persisted_document_chunk",
                    "concept_id": concept_id,
                },
                content_hash=f"hash-{owner_id}-{document_id}-{chunk_index}",
            )
        )
        session.commit()


def _advanced_runtime(
    Session,
    *,
    expert_config: ExpertCollaborationConfig | None = None,
    expert_runner=None,
) -> StudyAgentRuntimeService:
    return StudyAgentRuntimeService(
        session_factory=Session,
        expert_config=expert_config or ExpertCollaborationConfig(enabled=True, max_branches=3),
        expert_runner=expert_runner,
        route_policy=RAGRoutePolicyService(
            RAGRoutePolicyConfig(
                advanced_routing_enabled=True,
                graph_rag_enabled=True,
                agentic_rag_enabled=True,
                max_budget_for_agentic="balanced",
            )
        ),
        readiness_provider=lambda: RAGReadinessSnapshot(
            policy_version="rag-policy-v1",
            fixture_version="test-fixture",
            modes={
                "agentic_rag": {
                    "overall": "candidate",
                    "by_category": {
                        "multi_document_synthesis": "candidate",
                        "question_generation": "candidate",
                    },
                },
                "graph_rag_lite": {
                    "overall": "candidate",
                    "by_category": {
                        "multi_document_synthesis": "candidate",
                        "question_generation": "candidate",
                    },
                },
            },
        ),
    )


class _SlowExpertRunner:
    async def run(self, **kwargs):
        await asyncio.sleep(0.2)
        raise AssertionError("runtime wait_for should time this runner out first")


@pytest.mark.asyncio
async def test_runtime_runs_study_agent_against_real_document_artifact():
    Session = _session_factory()
    _insert_ready_document_with_artifact(Session)
    runtime = StudyAgentRuntimeService(
        session_factory=Session,
        chunker=StudyDocumentChunker(max_chars=200, overlap_chars=20),
    )

    result = await runtime.run(
        {
            "query": "What do derivatives measure?",
            "target": "answer",
            "document_ids": ["doc-study"],
            "expected_terms": ["rate"],
            "authenticated_user_id": "user-1",
            "request_id": "req-runtime-1",
        }
    )

    assert result.plan.mode == RetrievalMode.SIMPLE
    assert result.evidence.sources == ("document:doc-study:chunk:0",)
    assert result.evidence.chunks[0].metadata["owner_id"] == "user-1"
    assert result.evidence.chunks[0].metadata["document_id"] == "doc-study"
    assert "Derivatives measure instantaneous rate of change." in result.draft.content
    assert result.verification.needs_review is False
    assert result.audit_metadata["chunk_count"] == 1


@pytest.mark.asyncio
async def test_runtime_prefers_persisted_chunks_over_query_time_chunking():
    Session = _session_factory()
    _insert_ready_document_with_artifact(
        Session,
        content="Artifact text that should not appear when persisted chunks exist.",
    )
    _insert_persisted_chunk(Session)
    runtime = StudyAgentRuntimeService(
        session_factory=Session,
        chunker=StudyDocumentChunker(max_chars=200, overlap_chars=20),
    )

    result = await runtime.run(
        {
            "query": "What do derivatives measure?",
            "target": "answer",
            "document_ids": ["doc-study"],
            "authenticated_user_id": "user-1",
            "request_id": "req-runtime-persisted",
        }
    )

    assert result.evidence.sources == ("document:doc-study:chunk:0",)
    assert result.evidence.chunks[0].content == "Persisted derivatives evidence."
    assert result.evidence.chunks[0].metadata["source_kind"] == "persisted_document_chunk"
    assert result.audit_metadata["chunk_source"] == "persisted"
    assert result.audit_metadata["fallback_reason"] is None
    assert result.audit_metadata["index_statuses"]["doc-study"]["status"] == "indexed"
    assert result.audit_metadata["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_runtime_fallback_to_artifact_chunking_is_observable():
    Session = _session_factory()
    _insert_ready_document_with_artifact(Session)
    runtime = StudyAgentRuntimeService(
        session_factory=Session,
        chunker=StudyDocumentChunker(max_chars=200, overlap_chars=20),
    )

    result = await runtime.run(
        {
            "query": "What do derivatives measure?",
            "target": "answer",
            "document_ids": ["doc-study"],
            "authenticated_user_id": "user-1",
            "request_id": "req-runtime-fallback",
        }
    )

    assert result.evidence.chunks[0].metadata["source_kind"] == "normalized_document"
    assert result.audit_metadata["chunk_source"] == "fallback"
    assert result.audit_metadata["fallback_reason"] == "persisted_chunks_missing"
    assert (
        result.audit_metadata["index_statuses"]["doc-study"]["status"]
        == "fallback_available"
    )


@pytest.mark.asyncio
async def test_runtime_applies_route_policy_and_keeps_policy_safe():
    Session = _session_factory()
    _insert_ready_document_with_artifact(
        Session,
        content="Derivatives and integrals are connected by the fundamental theorem.",
    )
    runtime = StudyAgentRuntimeService(
        session_factory=Session,
        chunker=StudyDocumentChunker(max_chars=200, overlap_chars=20),
    )

    result = await runtime.run(
        {
            "query": "导数和积分的关系是什么？",
            "target": "answer",
            "document_ids": ["doc-study"],
            "authenticated_user_id": "user-1",
            "request_id": "req-runtime-policy",
        }
    )

    assert result.plan.mode == RetrievalMode.SIMPLE
    policy = result.audit_metadata["policy"]
    assert policy["status"] == "blocked_by_flag"
    assert policy["router_mode"] == "graph_rag_lite"
    assert policy["selected_mode"] == "simple_rag"
    serialized_policy = str(policy).lower()
    assert "导数" not in serialized_policy
    assert "积分" not in serialized_policy
    assert "关系" not in serialized_policy


@pytest.mark.asyncio
async def test_runtime_falls_back_when_agentic_step_budget_is_exhausted():
    Session = _session_factory()
    _insert_ready_document_with_artifact(
        Session,
        content="Derivatives and integrals connect through accumulation and rates.",
    )
    _insert_persisted_chunk(
        Session,
        content="Derivatives and integrals connect through accumulation and rates.",
    )
    runtime = StudyAgentRuntimeService(
        session_factory=Session,
        agentic_planner=AgenticRAGPlanner(max_steps=1),
        route_policy=RAGRoutePolicyService(
            RAGRoutePolicyConfig(
                advanced_routing_enabled=True,
                agentic_rag_enabled=True,
                max_budget_for_agentic="balanced",
            )
        ),
        readiness_provider=lambda: RAGReadinessSnapshot(
            policy_version="rag-policy-v1",
            fixture_version="test-fixture",
            modes={
                "agentic_rag": {
                    "overall": "candidate",
                    "by_category": {"question_generation": "candidate"},
                }
            },
        ),
    )

    result = await runtime.run(
        {
            "query": "基于第2章和第4章出一道综合题",
            "target": "question",
            "document_ids": ["doc-study"],
            "budget": "balanced",
            "authenticated_user_id": "user-1",
            "request_id": "req-agentic-step-budget",
        }
    )

    assert result.plan.mode == RetrievalMode.AGENTIC
    assert result.evidence.mode == RetrievalMode.SIMPLE
    assert result.evidence.fallback_reason == "agentic step budget exhausted"
    assert result.evidence.metadata["planned_step_count"] == 5
    assert result.evidence.metadata["executed_step_count"] == 1
    assert result.evidence.metadata["step_budget_exhausted"] is True
    serialized_metadata = str(result.evidence.metadata).lower()
    assert "第2章" not in serialized_metadata
    assert "第4章" not in serialized_metadata
    assert "prompt" not in serialized_metadata
    assert "hidden_reasoning" not in serialized_metadata


@pytest.mark.asyncio
async def test_runtime_falls_back_when_persisted_chunk_set_is_incomplete():
    Session = _session_factory()
    _insert_ready_document_with_artifact(
        Session,
        content=(
            "Derivatives measure instantaneous rate of change. "
            "Gradients extend derivatives to several variables. "
            "Integrals accumulate signed area over intervals."
        ),
    )
    chunker = StudyDocumentChunker(max_chars=48, overlap_chars=8)
    index_service = StudyDocumentIndexService(session_factory=Session, chunker=chunker)
    indexed = index_service.index_document(owner_id="user-1", document_id="doc-study")
    assert indexed.chunk_count >= 2
    with Session() as session:
        row = (
            session.query(DocumentChunkRecord)
            .filter(DocumentChunkRecord.document_id == "doc-study")
            .order_by(DocumentChunkRecord.chunk_index.desc())
            .first()
        )
        session.delete(row)
        session.commit()
    runtime = StudyAgentRuntimeService(
        session_factory=Session,
        chunker=chunker,
        index_service=index_service,
    )

    result = await runtime.run(
        {
            "query": "What do derivatives measure?",
            "target": "answer",
            "document_ids": ["doc-study"],
            "authenticated_user_id": "user-1",
            "request_id": "req-runtime-incomplete-persisted",
        }
    )

    assert result.audit_metadata["chunk_source"] == "fallback"
    assert result.audit_metadata["fallback_reason"] == "persisted_chunks_incomplete"
    assert result.evidence.chunks[0].metadata["source_kind"] == "normalized_document"


@pytest.mark.asyncio
async def test_runtime_falls_back_when_any_requested_document_lacks_persisted_chunks():
    Session = _session_factory()
    _insert_ready_document_with_artifact(Session, document_id="doc-study")
    _insert_ready_document_with_artifact(
        Session,
        document_id="doc-second",
        content="Integrals accumulate signed area.",
    )
    _insert_persisted_chunk(Session, document_id="doc-study")
    runtime = StudyAgentRuntimeService(
        session_factory=Session,
        chunker=StudyDocumentChunker(max_chars=200, overlap_chars=20),
    )

    result = await runtime.run(
        {
            "query": "What do derivatives measure?",
            "target": "answer",
            "document_ids": ["doc-study", "doc-second"],
            "authenticated_user_id": "user-1",
            "request_id": "req-runtime-partial-fallback",
        }
    )

    assert result.audit_metadata["chunk_source"] == "fallback"
    assert result.audit_metadata["fallback_reason"] == "persisted_chunks_incomplete"


@pytest.mark.asyncio
async def test_runtime_falls_back_when_persisted_chunks_are_stale():
    Session = _session_factory()
    _insert_ready_document_with_artifact(Session)
    _insert_persisted_chunk(Session, artifact_id="artifact-old")
    runtime = StudyAgentRuntimeService(
        session_factory=Session,
        chunker=StudyDocumentChunker(max_chars=200, overlap_chars=20),
    )

    result = await runtime.run(
        {
            "query": "What do derivatives measure?",
            "target": "answer",
            "document_ids": ["doc-study"],
            "authenticated_user_id": "user-1",
            "request_id": "req-runtime-stale-fallback",
        }
    )

    assert result.evidence.chunks[0].metadata["source_kind"] == "normalized_document"
    assert result.audit_metadata["chunk_source"] == "fallback"
    assert result.audit_metadata["fallback_reason"] == "persisted_chunks_stale"


@pytest.mark.asyncio
async def test_runtime_requires_authenticated_user_id():
    Session = _session_factory()
    runtime = StudyAgentRuntimeService(session_factory=Session)

    with pytest.raises(StudyAgentDocumentError) as exc_info:
        await runtime.run({"query": "What do derivatives measure?", "document_ids": ["doc-study"]})

    assert exc_info.value.status_code == 422
    assert exc_info.value.code == "authentication_required"


@pytest.mark.asyncio
async def test_runtime_returns_review_needed_for_retrieval_miss_against_valid_chunks():
    Session = _session_factory()
    _insert_ready_document_with_artifact(Session)
    runtime = StudyAgentRuntimeService(
        session_factory=Session,
        chunker=StudyDocumentChunker(max_chars=200, overlap_chars=20),
    )

    result = await runtime.run(
        {
            "query": "What is eigenvalue decomposition?",
            "target": "answer",
            "document_ids": ["doc-study"],
            "authenticated_user_id": "user-1",
            "request_id": "req-runtime-2",
        }
    )

    assert result.evidence.chunks == ()
    assert result.evidence.confidence == 0.0
    assert result.verification.needs_review is True
    assert "no evidence chunks used" in result.verification.issues


@pytest.mark.asyncio
async def test_runtime_attaches_completed_workflow_timeline():
    Session = _session_factory()
    _insert_ready_document_with_artifact(Session)
    runtime = StudyAgentRuntimeService(
        session_factory=Session,
        chunker=StudyDocumentChunker(max_chars=200, overlap_chars=20),
    )

    result = await runtime.run(
        {
            "query": "What do derivatives measure?",
            "target": "answer",
            "document_ids": ["doc-study"],
            "expected_terms": ["rate"],
            "authenticated_user_id": "user-1",
            "request_id": "req-workflow-complete",
        }
    )

    workflow = result.audit_metadata["workflow"]
    assert result.audit_metadata["skill"] == {
        "skill_name": "concept_explanation",
        "skill_version": "v1",
        "supported_targets": ["answer"],
        "allowed_retrieval_modes": ["simple_rag", "graph_rag_lite"],
        "default_budget": "balanced",
        "review_gate_profile": "standard",
        "memory_inputs": ["user_preference", "study_state"],
        "memory_outputs": ["skill_performance"],
    }
    assert workflow["workflow_id"].startswith("workflow-")
    assert workflow["status"] in {"completed", "completed_with_fallback"}
    assert workflow["current_stage"] == "trace"
    assert workflow["needs_review"] is False
    assert [stage["stage"] for stage in workflow["stages"]] == [
        "intake",
        "plan",
        "skill_select",
        "expert_gate",
        "retrieve",
        "generate",
        "verify",
        "review_gate",
        "trace",
    ]
    assert workflow["stages"][0]["output_summary"]["document_count"] == 1
    assert workflow["stages"][1]["output_summary"]["selected_mode"] == "simple_rag"
    skill_stage = workflow["stages"][2]
    assert skill_stage["output_summary"] == {
        "skill_name": "concept_explanation",
        "skill_version": "v1",
        "review_gate_profile": "standard",
    }
    expert_stage = workflow["stages"][3]
    assert expert_stage["output_summary"] == {
        "expert_enabled": False,
        "expert_branch_count": 0,
        "expert_timeout_count": 0,
        "expert_failure_count": 0,
        "expert_fallback_reason": "expert_disabled",
    }
    assert workflow["stages"][4]["output_summary"]["chunk_count"] == 1
    assert workflow["stages"][5]["output_summary"]["citation_count"] == 1
    assert workflow["stages"][6]["output_summary"]["confidence"] >= 0
    assert result.audit_metadata["expert"] == {
        "enabled": False,
        "branch_count": 0,
        "timeout_count": 0,
        "failure_count": 0,
        "fallback_reason": "expert_disabled",
    }


@pytest.mark.asyncio
async def test_runtime_runs_expert_branches_for_eligible_synthesis_request():
    Session = _session_factory()
    _insert_ready_document_with_artifact(
        Session,
        document_id="doc-study",
        content="Derivative material should not be read when persisted chunks exist.",
    )
    _insert_ready_document_with_artifact(
        Session,
        document_id="doc-second",
        content="Integral material should not be read when persisted chunks exist.",
    )
    _insert_persisted_chunk_with_concept(
        Session,
        document_id="doc-study",
        content="Derivative links local change to rates.",
        concept_id="derivative",
    )
    _insert_persisted_chunk_with_concept(
        Session,
        document_id="doc-second",
        content="Integral links accumulation to total change.",
        concept_id="integral",
    )
    runtime = _advanced_runtime(Session)

    result = await runtime.run(
        {
            "query": "请跨章节整合第2章和第4章中 Derivative 与 Integral 的关系",
            "target": "answer",
            "document_ids": ["doc-study", "doc-second"],
            "budget": "balanced",
            "authenticated_user_id": "user-1",
            "request_id": "req-expert-synthesis",
        }
    )

    assert result.plan.mode == RetrievalMode.AGENTIC
    assert result.audit_metadata["expert"] == {
        "enabled": True,
        "branch_count": 3,
        "timeout_count": 0,
        "failure_count": 0,
        "branch_statuses": {
            "retrieval_expert": "passed",
            "graph_expert": "passed",
            "synthesis_expert": "passed",
        },
    }
    expert_stage = next(
        stage for stage in result.audit_metadata["workflow"]["stages"] if stage["stage"] == "expert_gate"
    )
    assert expert_stage["output_summary"] == {
        "expert_enabled": True,
        "expert_branch_count": 3,
        "expert_timeout_count": 0,
        "expert_failure_count": 0,
    }
    serialized_expert = str(result.audit_metadata["expert"])
    assert "第2章" not in serialized_expert
    assert "Derivative links local change" not in serialized_expert


@pytest.mark.asyncio
async def test_runtime_skips_experts_for_non_eligible_category():
    Session = _session_factory()
    _insert_ready_document_with_artifact(Session)
    _insert_persisted_chunk_with_concept(Session)
    runtime = _advanced_runtime(Session)

    result = await runtime.run(
        {
            "query": "What do derivatives measure?",
            "target": "answer",
            "document_ids": ["doc-study"],
            "authenticated_user_id": "user-1",
            "request_id": "req-expert-category-skip",
        }
    )

    assert result.audit_metadata["expert"] == {
        "enabled": False,
        "branch_count": 0,
        "timeout_count": 0,
        "failure_count": 0,
        "fallback_reason": "category_not_eligible",
    }
    expert_stage = next(
        stage for stage in result.audit_metadata["workflow"]["stages"] if stage["stage"] == "expert_gate"
    )
    assert expert_stage["output_summary"]["expert_fallback_reason"] == "category_not_eligible"


@pytest.mark.asyncio
async def test_runtime_expert_metadata_excludes_cross_owner_chunk_content():
    Session = _session_factory()
    _insert_ready_document_with_artifact(Session)
    _insert_persisted_chunk_with_concept(
        Session,
        content="Derivative owner-scoped evidence.",
        concept_id="derivative",
    )
    _insert_persisted_chunk_with_concept(
        Session,
        owner_id="user-2",
        document_id="doc-study",
        content="CROSS OWNER SECRET CHUNK CONTENT",
        concept_id="other-owner-secret",
        chunk_index=1,
        chunk_count=2,
        source="document:doc-secret:chunk:0",
    )
    runtime = _advanced_runtime(Session)

    result = await runtime.run(
        {
            "query": "请跨章节整合第2章和第4章中 Derivative 的内容",
            "target": "answer",
            "document_ids": ["doc-study"],
            "budget": "balanced",
            "authenticated_user_id": "user-1",
            "request_id": "req-expert-owner-scope",
        }
    )

    serialized_metadata = str(
        {
            "expert": result.audit_metadata["expert"],
            "workflow": result.audit_metadata["workflow"],
        }
    )
    assert "CROSS OWNER SECRET" not in serialized_metadata
    assert "doc-secret" not in serialized_metadata
    assert "other-owner-secret" not in serialized_metadata
    assert "user-2" not in serialized_metadata


@pytest.mark.asyncio
async def test_runtime_expert_runner_timeout_falls_back_to_serial_answer():
    Session = _session_factory()
    _insert_ready_document_with_artifact(Session)
    _insert_persisted_chunk_with_concept(
        Session,
        content="Derivative and integral evidence for a practice question.",
        concept_id="derivative",
    )
    runtime = _advanced_runtime(
        Session,
        expert_config=ExpertCollaborationConfig(
            enabled=True,
            max_branches=3,
            branch_timeout_seconds=0.01,
        ),
        expert_runner=_SlowExpertRunner(),
    )

    result = await runtime.run(
        {
            "query": "基于第2章和第4章出一道 Derivative 综合题",
            "target": "question",
            "document_ids": ["doc-study"],
            "budget": "balanced",
            "authenticated_user_id": "user-1",
            "request_id": "req-expert-timeout",
        }
    )

    assert result.draft.content
    assert result.audit_metadata["expert"] == {
        "enabled": True,
        "branch_count": 1,
        "timeout_count": 1,
        "failure_count": 0,
        "fallback_reason": "branch_timeout",
        "branch_statuses": {"retrieval_expert": "timeout"},
    }
    expert_stage = next(
        stage for stage in result.audit_metadata["workflow"]["stages"] if stage["stage"] == "expert_gate"
    )
    assert expert_stage["output_summary"] == {
        "expert_enabled": True,
        "expert_branch_count": 1,
        "expert_timeout_count": 1,
        "expert_failure_count": 0,
        "expert_fallback_reason": "branch_timeout",
    }


@pytest.mark.asyncio
async def test_runtime_rejects_unsupported_requested_skill_version():
    Session = _session_factory()
    _insert_ready_document_with_artifact(Session)
    runtime = StudyAgentRuntimeService(
        session_factory=Session,
        chunker=StudyDocumentChunker(max_chars=200, overlap_chars=20),
    )

    with pytest.raises(ValueError, match="unsupported skill version"):
        await runtime.run(
            {
                "query": "What do derivatives measure?",
                "target": "answer",
                "document_ids": ["doc-study"],
                "skill_name": "concept_explanation",
                "skill_version": "v2",
                "authenticated_user_id": "user-1",
                "request_id": "req-runtime-skill-version",
            }
        )


@pytest.mark.asyncio
async def test_runtime_validates_requested_skill_before_document_access():
    Session = _session_factory()
    runtime = StudyAgentRuntimeService(session_factory=Session)

    with pytest.raises(ValueError) as exc_info:
        await runtime.run(
            {
                "query": "What do derivatives measure?",
                "target": "answer",
                "document_ids": ["missing-doc"],
                "skill_name": "concept_explanation",
                "skill_version": "sk-secret-token",
                "authenticated_user_id": "user-1",
                "request_id": "req-runtime-skill-before-doc",
            }
        )

    assert str(exc_info.value) == "unsupported skill version"
    assert "sk-secret-token" not in str(exc_info.value)
    assert not hasattr(exc_info.value, "workflow")


@pytest.mark.asyncio
async def test_runtime_rejects_requested_skill_that_does_not_support_target():
    Session = _session_factory()
    _insert_ready_document_with_artifact(Session)
    runtime = StudyAgentRuntimeService(
        session_factory=Session,
        chunker=StudyDocumentChunker(max_chars=200, overlap_chars=20),
    )

    with pytest.raises(ValueError, match="does not support target"):
        await runtime.run(
            {
                "query": "Write a practice question.",
                "target": "question",
                "document_ids": ["doc-study"],
                "skill_name": "concept_explanation",
                "skill_version": "v1",
                "authenticated_user_id": "user-1",
                "request_id": "req-runtime-skill-target",
            }
        )


@pytest.mark.asyncio
async def test_runtime_falls_back_when_selected_mode_is_not_allowed_by_requested_skill():
    Session = _session_factory()
    _insert_ready_document_with_artifact(
        Session,
        content="Derivatives measure rates and integrals accumulate signed area.",
    )
    _insert_persisted_chunk(
        Session,
        content="Derivatives measure rates and integrals accumulate signed area.",
    )
    runtime = StudyAgentRuntimeService(
        session_factory=Session,
        route_policy=RAGRoutePolicyService(
            RAGRoutePolicyConfig(
                advanced_routing_enabled=True,
                agentic_rag_enabled=True,
                allow_user_preferred_mode=True,
                require_persisted_chunks_for_advanced=False,
                max_budget_for_agentic="balanced",
            )
        ),
        readiness_provider=lambda: RAGReadinessSnapshot(
            policy_version="rag-policy-v1",
            fixture_version="test-fixture",
            modes={"agentic_rag": {"overall": "candidate"}},
        ),
    )

    result = await runtime.run(
        {
            "query": "Analyze derivatives and integrals.",
            "target": "answer",
            "document_ids": ["doc-study"],
            "preferred_mode": "agentic_rag",
            "skill_name": "concept_explanation",
            "skill_version": "v1",
            "authenticated_user_id": "user-1",
            "request_id": "req-runtime-skill-mode-fallback",
        }
    )

    assert result.plan.mode == RetrievalMode.SIMPLE
    assert result.evidence.mode == RetrievalMode.SIMPLE
    assert result.audit_metadata["policy"]["selected_mode"] == "simple_rag"
    skill_stage = next(
        stage
        for stage in result.audit_metadata["workflow"]["stages"]
        if stage["stage"] == "skill_select"
    )
    assert skill_stage["output_summary"]["skill_name"] == "concept_explanation"


@pytest.mark.asyncio
async def test_runtime_workflow_records_fallback_and_review_gate():
    Session = _session_factory()
    _insert_ready_document_with_artifact(Session)
    runtime = StudyAgentRuntimeService(
        session_factory=Session,
        chunker=StudyDocumentChunker(max_chars=200, overlap_chars=20),
    )

    result = await runtime.run(
        {
            "query": "基于导数出一道题",
            "target": "question",
            "document_ids": ["doc-study"],
            "authenticated_user_id": "user-1",
            "request_id": "req-workflow-review",
        }
    )

    workflow = result.audit_metadata["workflow"]
    retrieve_stage = next(stage for stage in workflow["stages"] if stage["stage"] == "retrieve")
    review_stage = next(stage for stage in workflow["stages"] if stage["stage"] == "review_gate")

    assert retrieve_stage["output_summary"]["fallback_reason"] == "persisted_chunks_missing"
    assert workflow["status"] in {"completed_with_fallback", "needs_review"}
    assert review_stage["status"] in {"passed", "needs_review"}
    assert "query" not in str(workflow).lower()
    assert "导数" not in str(workflow)


@pytest.mark.asyncio
async def test_runtime_workflow_failure_for_missing_evidence_is_safe():
    Session = _session_factory()
    runtime = StudyAgentRuntimeService(session_factory=Session)

    with pytest.raises(StudyAgentDocumentError) as exc_info:
        await runtime.run(
            {
                "query": "What do derivatives measure?",
                "target": "answer",
                "document_ids": ["missing-doc"],
                "authenticated_user_id": "user-1",
                "request_id": "req-workflow-failed",
            }
        )

    assert exc_info.value.status_code == 404
    workflow = exc_info.value.workflow
    assert workflow["status"] == "failed"
    assert [stage["stage"] for stage in workflow["stages"]] == [
        "intake",
        "retrieve",
        "trace",
    ]
    retrieve_stage = workflow["stages"][1]
    assert retrieve_stage["status"] == "failed"
    assert retrieve_stage["error_code"] == "document_evidence_missing"
    serialized_workflow = str(workflow)
    assert "What do derivatives measure" not in serialized_workflow
    assert "missing-doc" not in serialized_workflow
