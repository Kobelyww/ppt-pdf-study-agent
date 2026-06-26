from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.services.rag_router import QueryCategory, RetrievalDecision, RetrievalMode


@dataclass(frozen=True)
class RAGRoutePolicyConfig:
    policy_version: str = "rag-policy-v1"
    advanced_routing_enabled: bool = False
    graph_rag_enabled: bool = False
    agentic_rag_enabled: bool = False
    enabled_categories: frozenset[str] | None = None
    graph_candidate_required: bool = True
    agentic_candidate_required: bool = True
    allow_user_preferred_mode: bool = False
    max_budget_for_agentic: str = "high"
    require_persisted_chunks_for_advanced: bool = True
    fallback_to_simple_on_block: bool = True


@dataclass(frozen=True)
class RAGReadinessSnapshot:
    policy_version: str
    fixture_version: str
    modes: dict[str, dict[str, Any]]
    created_at: str | None = None

    def status_for(self, mode: RetrievalMode, category: QueryCategory) -> str | None:
        mode_status = self.modes.get(mode.value, {})
        by_category = mode_status.get("by_category", {})
        return by_category.get(category.value) or mode_status.get("overall")


@dataclass(frozen=True)
class RAGRoutePolicyDecision:
    selected_mode: RetrievalMode
    router_mode: RetrievalMode
    category: str
    status: str
    reason: str
    fallback_chain: list[RetrievalMode]
    readiness_status: str | None
    blocked_reason: str | None
    estimated_cost: str
    experiment_enabled: bool
    policy_version: str

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "selected_mode": self.selected_mode.value,
            "router_mode": self.router_mode.value,
            "category": self.category,
            "status": self.status,
            "reason": self.reason,
            "fallback_chain": [mode.value for mode in self.fallback_chain],
            "readiness_status": self.readiness_status,
            "blocked_reason": self.blocked_reason,
            "estimated_cost": self.estimated_cost,
            "experiment_enabled": self.experiment_enabled,
            "policy_version": self.policy_version,
        }


class RAGRoutePolicyService:
    def __init__(self, config: RAGRoutePolicyConfig | None = None) -> None:
        self.config = config or RAGRoutePolicyConfig()

    def decide(
        self,
        *,
        router_decision: RetrievalDecision,
        readiness: RAGReadinessSnapshot | None,
        index_statuses: dict[str, dict[str, Any]] | None,
        budget: str,
        preferred_mode: RetrievalMode | None = None,
    ) -> RAGRoutePolicyDecision:
        router_mode = self._effective_router_mode(router_decision.mode, preferred_mode)
        category = router_decision.category
        fallback_chain = self._fallback_chain(router_mode)

        if router_mode == RetrievalMode.SIMPLE:
            return self._decision(
                selected_mode=RetrievalMode.SIMPLE,
                router_mode=router_mode,
                category=category,
                status="allowed",
                reason="simple_rag is always allowed",
                fallback_chain=fallback_chain,
                readiness_status=None,
                blocked_reason=None,
                estimated_cost=router_decision.estimated_cost,
                experiment_enabled=False,
            )

        blocked = self._blocked_reason(
            mode=router_mode,
            category=category,
            readiness=readiness,
            index_statuses=index_statuses,
            budget=budget,
        )
        readiness_status = readiness.status_for(router_mode, category) if readiness else None

        if blocked is not None:
            status, reason = blocked
            selected_mode = (
                RetrievalMode.SIMPLE
                if self.config.fallback_to_simple_on_block
                else router_mode
            )
            return self._decision(
                selected_mode=selected_mode,
                router_mode=router_mode,
                category=category,
                status=status,
                reason=reason,
                fallback_chain=fallback_chain,
                readiness_status=readiness_status,
                blocked_reason=reason,
                estimated_cost=router_decision.estimated_cost,
                experiment_enabled=False,
            )

        return self._decision(
            selected_mode=router_mode,
            router_mode=router_mode,
            category=category,
            status="allowed",
            reason=f"{router_mode.value} is allowed by route policy",
            fallback_chain=fallback_chain,
            readiness_status=readiness_status,
            blocked_reason=None,
            estimated_cost=router_decision.estimated_cost,
            experiment_enabled=True,
        )

    def _effective_router_mode(
        self,
        router_mode: RetrievalMode,
        preferred_mode: RetrievalMode | None,
    ) -> RetrievalMode:
        if self.config.allow_user_preferred_mode and preferred_mode is not None:
            return preferred_mode
        return router_mode

    def _blocked_reason(
        self,
        *,
        mode: RetrievalMode,
        category: QueryCategory,
        readiness: RAGReadinessSnapshot | None,
        index_statuses: dict[str, dict[str, Any]] | None,
        budget: str,
    ) -> tuple[str, str] | None:
        if not self.config.advanced_routing_enabled:
            return ("blocked_by_flag", "advanced routing is disabled")

        if mode == RetrievalMode.GRAPH and not self.config.graph_rag_enabled:
            return ("blocked_by_flag", "graph_rag_lite is disabled")

        if mode == RetrievalMode.AGENTIC and not self.config.agentic_rag_enabled:
            return ("blocked_by_flag", "agentic_rag is disabled")

        if (
            self.config.enabled_categories is not None
            and category.value not in self.config.enabled_categories
        ):
            return ("blocked_by_category", f"{category.value} is not enabled")

        if readiness is None:
            return ("blocked_by_readiness", "readiness snapshot is unavailable")

        readiness_status = readiness.status_for(mode, category)
        if self._requires_candidate(mode) and readiness_status != "candidate":
            return (
                "blocked_by_readiness",
                f"{mode.value} is not candidate for {category.value}",
            )

        if mode == RetrievalMode.AGENTIC and budget != self.config.max_budget_for_agentic:
            return (
                "blocked_by_budget",
                f"agentic_rag requires {self.config.max_budget_for_agentic} budget",
            )

        index_statuses = index_statuses or {}
        unhealthy = [
            payload.get("status")
            for payload in index_statuses.values()
            if payload.get("status") != "indexed"
        ]
        if self.config.require_persisted_chunks_for_advanced and unhealthy:
            return (
                "blocked_by_index_health",
                "persisted chunks are required for advanced routing",
            )

        return None

    def _requires_candidate(self, mode: RetrievalMode) -> bool:
        if mode == RetrievalMode.GRAPH:
            return self.config.graph_candidate_required
        if mode == RetrievalMode.AGENTIC:
            return self.config.agentic_candidate_required
        return False

    def _decision(
        self,
        *,
        selected_mode: RetrievalMode,
        router_mode: RetrievalMode,
        category: QueryCategory,
        status: str,
        reason: str,
        fallback_chain: list[RetrievalMode],
        readiness_status: str | None,
        blocked_reason: str | None,
        estimated_cost: str,
        experiment_enabled: bool,
    ) -> RAGRoutePolicyDecision:
        return RAGRoutePolicyDecision(
            selected_mode=selected_mode,
            router_mode=router_mode,
            category=category.value,
            status=status,
            reason=reason,
            fallback_chain=fallback_chain,
            readiness_status=readiness_status,
            blocked_reason=blocked_reason,
            estimated_cost=estimated_cost,
            experiment_enabled=experiment_enabled,
            policy_version=self.config.policy_version,
        )

    def _fallback_chain(self, mode: RetrievalMode) -> list[RetrievalMode]:
        if mode == RetrievalMode.AGENTIC:
            return [RetrievalMode.GRAPH, RetrievalMode.SIMPLE]
        if mode == RetrievalMode.GRAPH:
            return [RetrievalMode.SIMPLE]
        return []
