from __future__ import annotations

import pytest

from src.services.rag_route_policy import RAGRoutePolicyDecision
from src.services.rag_router import RetrievalMode
from src.services.rag_service import Chunk
from src.services.study_agent import StudyBudget, StudyTarget
from src.services.study_agent_experts import (
    DeterministicExpertBranchRunner,
    ExpertBranchResult,
    ExpertCollaborationConfig,
    ExpertEligibilityService,
    safe_expert_metadata,
)
from src.services.study_agent_skills import StudySkill


def _policy(
    *,
    selected_mode: RetrievalMode = RetrievalMode.AGENTIC,
    category: str = "multi_document_synthesis",
    status: str = "allowed",
) -> RAGRoutePolicyDecision:
    return RAGRoutePolicyDecision(
        selected_mode=selected_mode,
        router_mode=selected_mode,
        effective_mode=selected_mode,
        category=category,
        status=status,
        reason=f"{selected_mode.value} is allowed by route policy",
        fallback_chain=[RetrievalMode.GRAPH, RetrievalMode.SIMPLE],
        readiness_status="candidate",
        blocked_reason=None,
        estimated_cost="high",
        experiment_enabled=True,
        policy_version="rag-policy-v1",
    )


def _skill(*, modes=(RetrievalMode.AGENTIC, RetrievalMode.GRAPH, RetrievalMode.SIMPLE)):
    return StudySkill(
        skill_name="multi_document_synthesis",
        version="v1",
        supported_targets=(StudyTarget.ANSWER, StudyTarget.QUESTION),
        allowed_retrieval_modes=tuple(modes),
        default_budget=StudyBudget.HIGH,
        review_gate_profile="strict",
        memory_inputs=("user_preference", "study_state"),
        memory_outputs=("review_outcome", "skill_performance"),
    )


def test_expert_branch_result_safe_dict_omits_raw_values():
    result = ExpertBranchResult(
        branch_name="retrieval_expert",
        status="passed",
        source_ids=("document:doc-1:chunk:0", "/tmp/raw-secret.pdf"),
        concept_ids=("derivative", "sk-secret-token"),
        confidence=0.88,
        metrics={
            "source_count": 1,
            "chunk_count": 2,
            "query": "raw private query",
            "prompt": "hidden prompt",
            "token": "sk-secret-token",
            "latency_ms": 12.5,
        },
        safe_reason_code=None,
        internal_payload={"draft": "generated answer should not persist"},
    )

    safe = result.to_safe_dict()

    assert safe == {
        "branch_name": "retrieval_expert",
        "status": "passed",
        "source_count": 1,
        "concept_count": 1,
        "confidence": 0.88,
        "metrics": {
            "source_count": 1,
            "chunk_count": 2,
            "latency_ms": 12.5,
        },
    }
    serialized = str(safe).lower()
    assert "raw private query" not in serialized
    assert "hidden prompt" not in serialized
    assert "sk-secret-token" not in serialized
    assert "/tmp/raw-secret" not in serialized
    assert "generated answer" not in serialized


@pytest.mark.asyncio
async def test_deterministic_expert_runner_returns_safe_branch_summary():
    chunks = (
        Chunk(
            content="PRIVATE raw chunk content about derivatives should never persist.",
            source="document:doc-study:chunk:0",
            metadata={
                "owner_id": "user-1",
                "document_id": "doc-study",
                "concept_id": "derivative",
                "raw_path": "/Users/alice/private/calculus.pdf",
            },
            score=0.8,
        ),
        Chunk(
            content="Generated answer seed text and hidden prompt bait.",
            source="document:doc-second:chunk:0",
            metadata={
                "owner_id": "user-1",
                "document_id": "doc-second",
                "concept_id": "integral",
                "token": "sk-secret-token",
            },
            score=0.6,
        ),
    )

    summary = await DeterministicExpertBranchRunner().run(
        chunks=chunks,
        category="multi_document_synthesis",
        max_branches=3,
    )

    assert summary.enabled is True
    assert [branch.branch_name for branch in summary.branch_results] == [
        "retrieval_expert",
        "graph_expert",
        "synthesis_expert",
    ]
    assert [branch.status for branch in summary.branch_results] == [
        "passed",
        "passed",
        "passed",
    ]
    safe = summary.to_safe_dict()
    assert safe == {
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
    serialized = str(safe).lower()
    assert "private raw chunk content" not in serialized
    assert "generated answer" not in serialized
    assert "hidden prompt" not in serialized
    assert "/users/alice" not in serialized
    assert "sk-secret-token" not in serialized


def test_expert_branch_result_counts_only_opaque_safe_source_ids():
    result = ExpertBranchResult(
        branch_name="retrieval_expert",
        status="passed",
        source_ids=(
            "document:doc-1:chunk:0",
            "document:/Users/alice/private.pdf",
            "document:C:\\Users\\alice\\private.pdf",
            "document:https://example.com/private.pdf",
            "document:doc 1:chunk:0",
            "document:private.pdf:chunk:0",
        ),
    )

    safe = result.to_safe_dict()

    assert safe["source_count"] == 1
    serialized = str(safe).lower()
    assert "alice" not in serialized
    assert "private.pdf" not in serialized
    assert "https://example.com" not in serialized


def test_expert_branch_result_omits_credential_like_concept_labels():
    result = ExpertBranchResult(
        branch_name="graph_expert",
        status="passed",
        concept_ids=(
            "derivative",
            "password_hint",
            "openai_api_key",
            "authorization_header",
            "bearer_session",
            "credential_store",
            "encryption_key",
        ),
    )

    safe = result.to_safe_dict()

    assert safe["concept_count"] == 1
    serialized = str(safe).lower()
    for blocked in ("password", "api_key", "authorization", "bearer", "credential", "key"):
        assert blocked not in serialized


def test_safe_expert_metadata_allows_only_labels_counts_and_statuses():
    metadata = safe_expert_metadata(
        {
            "enabled": True,
            "branch_count": 2,
            "timeout_count": 1,
            "failure_count": 0,
            "fallback_reason": "branch_timeout",
            "branch_statuses": {
                "retrieval_expert": "passed",
                "graph_expert": "timeout",
                "raw_private_branch": "passed",
            },
            "query": "raw private query",
            "exception": "ValueError sk-secret-token",
        }
    )

    assert metadata == {
        "enabled": True,
        "branch_count": 2,
        "timeout_count": 1,
        "failure_count": 0,
        "fallback_reason": "branch_timeout",
        "branch_statuses": {
            "retrieval_expert": "passed",
            "graph_expert": "timeout",
        },
    }


def test_expert_gate_is_disabled_by_default():
    decision = ExpertEligibilityService(ExpertCollaborationConfig()).decide(
        policy_decision=_policy(),
        skill=_skill(),
        index_statuses={"doc-1": {"status": "indexed"}},
    )

    assert decision.enabled is False
    assert decision.safe_reason_code == "expert_disabled"


def test_expert_gate_disabled_config_ignores_invalid_timeout():
    config = ExpertCollaborationConfig(
        enabled=False,
        branch_timeout_seconds="not-a-number",  # type: ignore[arg-type]
    )

    decision = ExpertEligibilityService(config).decide(
        policy_decision=_policy(),
        skill=_skill(),
        index_statuses={"doc-1": {"status": "indexed"}},
    )

    assert decision.enabled is False
    assert decision.safe_reason_code == "expert_disabled"


@pytest.mark.parametrize(
    "invalid_timeout",
    ["not-a-number", None, float("nan"), float("inf")],
)
def test_expert_gate_enabled_config_invalid_timeout_uses_serial_fallback(
    invalid_timeout,
):
    config = ExpertCollaborationConfig(
        enabled=True,
        branch_timeout_seconds=invalid_timeout,  # type: ignore[arg-type]
    )

    decision = ExpertEligibilityService(config).decide(
        policy_decision=_policy(),
        skill=_skill(),
        index_statuses={"doc-1": {"status": "indexed"}},
    )

    assert decision.enabled is False
    assert decision.safe_reason_code == "serial_fallback"


@pytest.mark.parametrize("invalid_max_branches", ["many", None, float("nan"), float("inf")])
def test_expert_gate_enabled_config_invalid_max_branches_uses_serial_fallback(
    invalid_max_branches,
):
    config = ExpertCollaborationConfig(
        enabled=True,
        max_branches=invalid_max_branches,  # type: ignore[arg-type]
    )

    decision = ExpertEligibilityService(config).decide(
        policy_decision=_policy(),
        skill=_skill(),
        index_statuses={"doc-1": {"status": "indexed"}},
    )

    assert decision.enabled is False
    assert decision.safe_reason_code == "serial_fallback"


def test_expert_gate_allows_eligible_policy_skill_and_index():
    config = ExpertCollaborationConfig(enabled=True, max_branches=3, branch_timeout_seconds=0.1)
    decision = ExpertEligibilityService(config).decide(
        policy_decision=_policy(),
        skill=_skill(),
        index_statuses={"doc-1": {"status": "indexed"}},
    )

    assert decision.enabled is True
    assert decision.safe_reason_code is None
    assert decision.max_branches == 3
    assert decision.branch_timeout_seconds == 0.1


def test_expert_gate_clamps_valid_config_ranges():
    config = ExpertCollaborationConfig(enabled=True, max_branches=99, branch_timeout_seconds=0.001)

    decision = ExpertEligibilityService(config).decide(
        policy_decision=_policy(),
        skill=_skill(),
        index_statuses={"doc-1": {"status": "indexed"}},
    )

    assert decision.enabled is True
    assert decision.safe_reason_code is None
    assert decision.max_branches == 4
    assert decision.branch_timeout_seconds == 0.01


def test_expert_gate_blocks_non_eligible_category_policy_and_skill_mode():
    service = ExpertEligibilityService(ExpertCollaborationConfig(enabled=True))

    assert service.decide(
        policy_decision=_policy(category="definition"),
        skill=_skill(),
        index_statuses={"doc-1": {"status": "indexed"}},
    ).safe_reason_code == "category_not_eligible"
    assert service.decide(
        policy_decision=_policy(status="blocked_by_budget"),
        skill=_skill(),
        index_statuses={"doc-1": {"status": "indexed"}},
    ).safe_reason_code == "policy_not_allowed"
    assert service.decide(
        policy_decision=_policy(selected_mode=RetrievalMode.AGENTIC),
        skill=_skill(modes=(RetrievalMode.SIMPLE,)),
        index_statuses={"doc-1": {"status": "indexed"}},
    ).safe_reason_code == "mode_not_allowed_by_skill"


def test_expert_gate_blocks_unhealthy_index():
    service = ExpertEligibilityService(ExpertCollaborationConfig(enabled=True))
    decision = service.decide(
        policy_decision=_policy(),
        skill=_skill(),
        index_statuses={"doc-1": {"status": "fallback_available"}},
    )

    assert decision.enabled is False
    assert decision.safe_reason_code == "index_not_ready"
