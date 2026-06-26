from src.services.rag_route_policy import (
    RAGReadinessSnapshot,
    RAGRoutePolicyConfig,
    RAGRoutePolicyService,
)
from src.services.rag_router import QueryCategory, RetrievalDecision, RetrievalMode


def _decision(mode, category):
    return RetrievalDecision(
        mode=mode,
        reason="router reason",
        confidence=0.8,
        estimated_cost="high" if mode == RetrievalMode.AGENTIC else "medium",
        category=category,
    )


def _snapshot(graph_status="candidate", agentic_status="hold"):
    return RAGReadinessSnapshot(
        policy_version="rag-policy-v1",
        fixture_version="rag_eval_set.json",
        modes={
            "simple_rag": {"overall": "baseline", "by_category": {}},
            "graph_rag_lite": {
                "overall": graph_status,
                "by_category": {"learning_path": graph_status},
            },
            "agentic_rag": {
                "overall": agentic_status,
                "by_category": {"question_generation": agentic_status},
            },
        },
    )


def _index_status(status="indexed"):
    return {"doc-1": {"status": status}}


def test_simple_rag_allowed_when_advanced_routing_disabled():
    service = RAGRoutePolicyService()
    decision = service.decide(
        router_decision=_decision(RetrievalMode.SIMPLE, QueryCategory.DEFINITION),
        readiness=None,
        index_statuses=_index_status("missing"),
        budget="low",
    )

    assert decision.selected_mode == RetrievalMode.SIMPLE
    assert decision.status == "allowed"
    assert decision.experiment_enabled is False
    assert decision.fallback_chain == []


def test_graph_selected_only_when_flag_and_readiness_allow_category():
    service = RAGRoutePolicyService(
        RAGRoutePolicyConfig(
            advanced_routing_enabled=True,
            graph_rag_enabled=True,
            enabled_categories=frozenset({"learning_path"}),
        )
    )

    decision = service.decide(
        router_decision=_decision(RetrievalMode.GRAPH, QueryCategory.LEARNING_PATH),
        readiness=_snapshot(),
        index_statuses=_index_status(),
        budget="medium",
    )

    assert decision.selected_mode == RetrievalMode.GRAPH
    assert decision.status == "allowed"
    assert decision.readiness_status == "candidate"
    assert decision.experiment_enabled is True
    assert decision.fallback_chain == [RetrievalMode.SIMPLE]


def test_dict_shaped_healthy_index_status_does_not_block_graph_selection():
    service = RAGRoutePolicyService(
        RAGRoutePolicyConfig(
            advanced_routing_enabled=True,
            graph_rag_enabled=True,
            enabled_categories=frozenset({"learning_path"}),
        )
    )

    decision = service.decide(
        router_decision=_decision(RetrievalMode.GRAPH, QueryCategory.LEARNING_PATH),
        readiness=_snapshot(),
        index_statuses={"doc-1": {"status": "indexed"}},
        budget="medium",
    )

    assert decision.selected_mode == RetrievalMode.GRAPH
    assert decision.status == "allowed"


def test_agentic_blocked_when_readiness_holds_category():
    service = RAGRoutePolicyService(
        RAGRoutePolicyConfig(
            advanced_routing_enabled=True,
            agentic_rag_enabled=True,
            enabled_categories=frozenset({"question_generation"}),
        )
    )

    decision = service.decide(
        router_decision=_decision(
            RetrievalMode.AGENTIC,
            QueryCategory.QUESTION_GENERATION,
        ),
        readiness=_snapshot(agentic_status="hold"),
        index_statuses=_index_status(),
        budget="high",
    )

    assert decision.selected_mode == RetrievalMode.SIMPLE
    assert decision.status == "blocked_by_readiness"
    assert decision.blocked_reason == "agentic_rag is not candidate for question_generation"
    assert decision.experiment_enabled is False
    assert decision.fallback_chain == [RetrievalMode.GRAPH, RetrievalMode.SIMPLE]


def test_no_readiness_snapshot_blocks_advanced_modes():
    service = RAGRoutePolicyService(
        RAGRoutePolicyConfig(
            advanced_routing_enabled=True,
            graph_rag_enabled=True,
            enabled_categories=frozenset({"learning_path"}),
        )
    )

    decision = service.decide(
        router_decision=_decision(RetrievalMode.GRAPH, QueryCategory.LEARNING_PATH),
        readiness=None,
        index_statuses=_index_status(),
        budget="medium",
    )

    assert decision.selected_mode == RetrievalMode.SIMPLE
    assert decision.status == "blocked_by_readiness"
    assert decision.blocked_reason == "readiness snapshot is unavailable"


def test_user_preferred_mode_cannot_override_default_policy():
    service = RAGRoutePolicyService()

    decision = service.decide(
        router_decision=_decision(RetrievalMode.GRAPH, QueryCategory.LEARNING_PATH),
        readiness=_snapshot(),
        index_statuses=_index_status(),
        budget="medium",
        preferred_mode=RetrievalMode.GRAPH,
    )

    assert decision.selected_mode == RetrievalMode.SIMPLE
    assert decision.status == "blocked_by_flag"
    assert decision.blocked_reason == "advanced routing is disabled"
    assert decision.experiment_enabled is False


def test_index_health_blocks_advanced_when_persisted_chunks_required():
    service = RAGRoutePolicyService(
        RAGRoutePolicyConfig(
            advanced_routing_enabled=True,
            graph_rag_enabled=True,
            enabled_categories=frozenset({"learning_path"}),
        )
    )

    decision = service.decide(
        router_decision=_decision(RetrievalMode.GRAPH, QueryCategory.LEARNING_PATH),
        readiness=_snapshot(),
        index_statuses={
            "doc-1": {"status": "indexed"},
            "doc-2": {"status": "stale"},
        },
        budget="medium",
    )

    assert decision.selected_mode == RetrievalMode.SIMPLE
    assert decision.status == "blocked_by_index_health"
    assert decision.blocked_reason == "persisted chunks are required for advanced routing"


def test_missing_index_health_blocks_advanced_when_persisted_chunks_required():
    service = RAGRoutePolicyService(
        RAGRoutePolicyConfig(
            advanced_routing_enabled=True,
            graph_rag_enabled=True,
            enabled_categories=frozenset({"learning_path"}),
        )
    )

    decision = service.decide(
        router_decision=_decision(RetrievalMode.GRAPH, QueryCategory.LEARNING_PATH),
        readiness=_snapshot(),
        index_statuses=None,
        budget="medium",
    )

    assert decision.selected_mode == RetrievalMode.SIMPLE
    assert decision.status == "blocked_by_index_health"
    assert decision.blocked_reason == "persisted chunks are required for advanced routing"


def test_empty_index_health_blocks_advanced_when_persisted_chunks_required():
    service = RAGRoutePolicyService(
        RAGRoutePolicyConfig(
            advanced_routing_enabled=True,
            graph_rag_enabled=True,
            enabled_categories=frozenset({"learning_path"}),
        )
    )

    decision = service.decide(
        router_decision=_decision(RetrievalMode.GRAPH, QueryCategory.LEARNING_PATH),
        readiness=_snapshot(),
        index_statuses={},
        budget="medium",
    )

    assert decision.selected_mode == RetrievalMode.SIMPLE
    assert decision.effective_mode == RetrievalMode.GRAPH
    assert decision.status == "blocked_by_index_health"
    assert decision.blocked_reason == "persisted chunks are required for advanced routing"


def test_allowed_user_preference_preserves_router_recommendation_in_diagnostics():
    service = RAGRoutePolicyService(
        RAGRoutePolicyConfig(
            advanced_routing_enabled=True,
            graph_rag_enabled=True,
            enabled_categories=frozenset({"learning_path"}),
            allow_user_preferred_mode=True,
        )
    )

    decision = service.decide(
        router_decision=_decision(RetrievalMode.SIMPLE, QueryCategory.LEARNING_PATH),
        readiness=_snapshot(),
        index_statuses=_index_status(),
        budget="medium",
        preferred_mode=RetrievalMode.GRAPH,
    )

    assert decision.selected_mode == RetrievalMode.GRAPH
    assert decision.router_mode == RetrievalMode.SIMPLE
    assert decision.effective_mode == RetrievalMode.GRAPH
    assert decision.status == "allowed"


def test_blocked_user_preference_exposes_effective_mode_in_diagnostics():
    service = RAGRoutePolicyService(
        RAGRoutePolicyConfig(
            advanced_routing_enabled=True,
            graph_rag_enabled=False,
            enabled_categories=frozenset({"learning_path"}),
            allow_user_preferred_mode=True,
        )
    )

    decision = service.decide(
        router_decision=_decision(RetrievalMode.SIMPLE, QueryCategory.LEARNING_PATH),
        readiness=_snapshot(),
        index_statuses=_index_status(),
        budget="medium",
        preferred_mode=RetrievalMode.GRAPH,
    )

    assert decision.selected_mode == RetrievalMode.SIMPLE
    assert decision.router_mode == RetrievalMode.SIMPLE
    assert decision.effective_mode == RetrievalMode.GRAPH
    assert decision.status == "blocked_by_flag"
    assert decision.blocked_reason == "graph_rag_lite is disabled"


def test_to_safe_dict_excludes_private_content_keys():
    service = RAGRoutePolicyService(
        RAGRoutePolicyConfig(
            advanced_routing_enabled=True,
            graph_rag_enabled=True,
            enabled_categories=frozenset({"learning_path"}),
        )
    )

    decision = service.decide(
        router_decision=_decision(RetrievalMode.GRAPH, QueryCategory.LEARNING_PATH),
        readiness=_snapshot(),
        index_statuses=_index_status(),
        budget="medium",
    )

    safe = decision.to_safe_dict()

    assert safe["selected_mode"] == "graph_rag_lite"
    assert safe["effective_mode"] == "graph_rag_lite"
    assert safe["fallback_chain"] == ["simple_rag"]
    assert not {"query", "content", "snippet", "secret", "password", "token"} & set(safe)


def test_agentic_allowed_when_all_policy_gates_pass():
    service = RAGRoutePolicyService(
        RAGRoutePolicyConfig(
            advanced_routing_enabled=True,
            agentic_rag_enabled=True,
            enabled_categories=frozenset({"question_generation"}),
        )
    )

    decision = service.decide(
        router_decision=_decision(
            RetrievalMode.AGENTIC,
            QueryCategory.QUESTION_GENERATION,
        ),
        readiness=_snapshot(agentic_status="candidate"),
        index_statuses=_index_status(),
        budget="high",
    )

    assert decision.selected_mode == RetrievalMode.AGENTIC
    assert decision.status == "allowed"
    assert decision.experiment_enabled is True
    assert decision.readiness_status == "candidate"
