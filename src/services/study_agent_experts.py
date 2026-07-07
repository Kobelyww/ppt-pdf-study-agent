from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from src.services.rag_route_policy import RAGRoutePolicyDecision
from src.services.rag_router import RetrievalMode
from src.services.study_agent_skills import StudySkill

ExpertBranchName = Literal[
    "retrieval_expert",
    "graph_expert",
    "question_expert",
    "synthesis_expert",
]
ExpertBranchStatus = Literal["passed", "skipped", "failed", "timeout"]

SAFE_BRANCH_NAMES = {
    "retrieval_expert",
    "graph_expert",
    "question_expert",
    "synthesis_expert",
}
SAFE_BRANCH_STATUSES = {"passed", "skipped", "failed", "timeout"}
SAFE_REASON_CODES = {
    "expert_disabled",
    "category_not_eligible",
    "policy_not_allowed",
    "mode_not_allowed_by_skill",
    "index_not_ready",
    "budget_not_allowed",
    "branch_timeout",
    "branch_error",
    "graph_unavailable",
    "serial_fallback",
}
ELIGIBLE_CATEGORIES = {"multi_document_synthesis", "question_generation"}
ADVANCED_MODES = {RetrievalMode.AGENTIC, RetrievalMode.GRAPH}
SAFE_METRIC_KEYS = {
    "source_count",
    "chunk_count",
    "concept_count",
    "graph_hop_count",
    "latency_ms",
    "fallback_used",
}
SAFE_SOURCE_ID_PATTERN = re.compile(
    r"^document:[A-Za-z0-9_-]{1,64}:chunk:[0-9]{1,10}$"
)
CREDENTIAL_LABEL_DENYLIST = (
    "secret",
    "token",
    "password",
    "passwd",
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "bearer",
    "credential",
    "credentials",
    "key",
)


@dataclass(frozen=True)
class ExpertCollaborationConfig:
    enabled: bool = False
    max_branches: int = 3
    branch_timeout_seconds: float = 1.0
    require_indexed_chunks: bool = True


@dataclass(frozen=True)
class ExpertGateDecision:
    enabled: bool
    safe_reason_code: str | None
    max_branches: int
    branch_timeout_seconds: float

    def to_safe_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "enabled": self.enabled,
            "branch_count": 0,
            "timeout_count": 0,
            "failure_count": 0,
        }
        if self.safe_reason_code in SAFE_REASON_CODES:
            payload["fallback_reason"] = self.safe_reason_code
        return payload


@dataclass(frozen=True)
class ExpertBranchResult:
    branch_name: str
    status: str
    source_ids: tuple[str, ...] = ()
    concept_ids: tuple[str, ...] = ()
    confidence: float = 0.0
    metrics: dict[str, Any] = field(default_factory=dict)
    safe_reason_code: str | None = None
    internal_payload: dict[str, Any] = field(default_factory=dict)

    def to_safe_dict(self) -> dict[str, Any]:
        safe: dict[str, Any] = {}
        if self.branch_name in SAFE_BRANCH_NAMES:
            safe["branch_name"] = self.branch_name
        if self.status in SAFE_BRANCH_STATUSES:
            safe["status"] = self.status

        source_ids = tuple(_safe_source_id(item) for item in self.source_ids)
        source_ids = tuple(item for item in source_ids if item is not None)
        concept_ids = tuple(_safe_label(item) for item in self.concept_ids)
        concept_ids = tuple(item for item in concept_ids if item is not None)

        safe["source_count"] = len(source_ids)
        safe["concept_count"] = len(concept_ids)
        safe["confidence"] = _safe_float(self.confidence)

        metrics = _safe_metrics(self.metrics)
        if metrics:
            safe["metrics"] = metrics
        if self.safe_reason_code in SAFE_REASON_CODES:
            safe["safe_reason_code"] = self.safe_reason_code
        return safe


class ExpertEligibilityService:
    def __init__(self, config: ExpertCollaborationConfig | None = None) -> None:
        self.config = config or ExpertCollaborationConfig()

    def decide(
        self,
        *,
        policy_decision: RAGRoutePolicyDecision,
        skill: StudySkill,
        index_statuses: dict[str, dict[str, Any]],
    ) -> ExpertGateDecision:
        if not self.config.enabled:
            return self._blocked("expert_disabled")
        if policy_decision.category not in ELIGIBLE_CATEGORIES:
            return self._blocked("category_not_eligible")
        if policy_decision.status != "allowed":
            return self._blocked("policy_not_allowed")
        if policy_decision.selected_mode not in ADVANCED_MODES:
            return self._blocked("policy_not_allowed")
        if policy_decision.selected_mode not in skill.allowed_retrieval_modes:
            return self._blocked("mode_not_allowed_by_skill")
        if self.config.require_indexed_chunks and not _all_indexes_ready(index_statuses):
            return self._blocked("index_not_ready")
        return ExpertGateDecision(
            enabled=True,
            safe_reason_code=None,
            max_branches=max(1, min(4, int(self.config.max_branches))),
            branch_timeout_seconds=max(0.01, float(self.config.branch_timeout_seconds)),
        )

    def _blocked(self, reason: str) -> ExpertGateDecision:
        return ExpertGateDecision(
            enabled=False,
            safe_reason_code=reason,
            max_branches=0,
            branch_timeout_seconds=max(0.01, float(self.config.branch_timeout_seconds)),
        )


def safe_expert_metadata(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None

    safe: dict[str, Any] = {}
    if isinstance(value.get("enabled"), bool):
        safe["enabled"] = value["enabled"]
    for source, target in {
        "branch_count": "branch_count",
        "timeout_count": "timeout_count",
        "failure_count": "failure_count",
    }.items():
        count = _safe_int(value.get(source))
        if count is not None:
            safe[target] = count

    reason = value.get("fallback_reason")
    if isinstance(reason, str) and reason in SAFE_REASON_CODES:
        safe["fallback_reason"] = reason

    statuses = value.get("branch_statuses")
    if isinstance(statuses, dict):
        safe_statuses = {
            key: status
            for key, status in statuses.items()
            if key in SAFE_BRANCH_NAMES and status in SAFE_BRANCH_STATUSES
        }
        if safe_statuses:
            safe["branch_statuses"] = safe_statuses
    return safe or None


def _all_indexes_ready(index_statuses: dict[str, dict[str, Any]]) -> bool:
    return bool(index_statuses) and all(
        payload.get("status") == "indexed" for payload in index_statuses.values()
    )


def _safe_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in metrics.items():
        if key not in SAFE_METRIC_KEYS:
            continue
        if isinstance(value, bool):
            safe[key] = value
        elif isinstance(value, int) and value >= 0:
            safe[key] = value
        elif isinstance(value, float) and value >= 0:
            safe[key] = round(value, 6)
    return safe


def _safe_source_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    if 1 <= len(value) <= 128 and SAFE_SOURCE_ID_PATTERN.fullmatch(value):
        return value
    return None


def _safe_label(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    if 1 <= len(value) <= 64 and all(char.isalnum() or char in {"_", "-", ":"} for char in value):
        normalized = value.lower()
        if not any(term in normalized for term in CREDENTIAL_LABEL_DENYLIST):
            return value
    return None


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _safe_float(value: Any) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return round(max(0.0, min(1.0, float(value))), 6)
    return 0.0
