from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import math
import re
from typing import Any
from uuid import uuid4

from src.services.rag_router import RetrievalMode
from src.services.study_agent import (
    EvidenceBundle,
    StudyDraft,
    StudyTarget,
    StudyVerification,
)


class WorkflowStageName(str, Enum):
    INTAKE = "intake"
    PLAN = "plan"
    SKILL_SELECT = "skill_select"
    RETRIEVE = "retrieve"
    EXPERT_GATE = "expert_gate"
    GENERATE = "generate"
    VERIFY = "verify"
    REVIEW_GATE = "review_gate"
    MEMORY_UPDATE = "memory_update"
    TRACE = "trace"


class WorkflowStageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    NEEDS_REVIEW = "needs_review"


class WorkflowStatus(str, Enum):
    COMPLETED = "completed"
    COMPLETED_WITH_FALLBACK = "completed_with_fallback"
    NEEDS_REVIEW = "needs_review"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


_SAFE_STRING_VALUES = {
    "stage": {stage.value for stage in WorkflowStageName},
    "status": {status.value for status in WorkflowStageStatus}
    | {status.value for status in WorkflowStatus},
    "target": {target.value for target in StudyTarget},
    "mode": {mode.value for mode in RetrievalMode},
    "router_mode": {mode.value for mode in RetrievalMode},
    "selected_mode": {mode.value for mode in RetrievalMode},
    "category": {
        "direct_lookup",
        "definition",
        "concept_relation",
        "learning_path",
        "multi_document_synthesis",
        "question_generation",
        "outline_fragment",
        "unknown",
    },
    "policy_status": {
        "allowed",
        "blocked_by_flag",
        "blocked_by_category",
        "blocked_by_readiness",
        "blocked_by_budget",
        "blocked_by_index_health",
        "not_applied",
    },
    "readiness_status": {"baseline", "candidate", "hold", "blocked", "insufficient_data"},
    "fallback_reason": {
        "persisted_chunks_missing",
        "persisted_chunks_stale",
        "persisted_chunks_incomplete",
        "no graph configured",
        "no graph seed matched",
        "matched graph seed but no chunks recovered",
        "low budget prevents agentic retrieval",
        "agentic step budget exhausted",
        "agentic evidence unavailable",
    },
    "review_reason": {
        "verification_failed",
        "low_confidence",
        "missing_citations",
        "empty_evidence",
        "policy_blocked_without_fallback",
        "target_used_fallback_evidence",
        "agentic_step_budget_exhausted",
    },
    "error_code": {
        "authentication_required",
        "document_evidence_missing",
        "unsupported_study_target",
        "unsupported_retrieval_mode",
        "forbidden_document",
        "bad_study_request",
    },
    "estimated_cost": {"low", "medium", "balanced", "high"},
    "chunk_source": {"persisted", "fallback"},
    "skill_name": {
        "concept_explanation",
        "practice_question",
        "outline_fragment",
        "concept_relation",
        "multi_document_synthesis",
    },
    "skill_version": {"v1"},
    "review_gate_profile": {"standard", "strict"},
    "expert_fallback_reason": {
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
    },
}

_SAFE_INT_KEYS = {
    "document_count",
    "chunk_count",
    "expected_term_count",
    "source_count",
    "concept_count",
    "issue_count",
    "stage_count",
    "used_chunk_count",
    "citation_count",
    "memory_record_count",
    "expert_branch_count",
    "expert_timeout_count",
    "expert_failure_count",
}
_SAFE_FLOAT_KEYS = {
    "confidence",
    "source_recall",
    "answer_term_recall",
    "duration_ms",
    "latency_ms",
}
_SAFE_BOOL_KEYS = {
    "needs_review",
    "fallback_used",
    "persisted_chunks_used",
    "experiment_enabled",
    "expert_enabled",
}
_SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_:\.-]{1,128}$")
_GENERATED_WORKFLOW_ID_PATTERN = re.compile(r"^workflow-[0-9a-f]{32}$")
_BLOCKED_POLICY_STATUSES = _SAFE_STRING_VALUES["policy_status"] & {
    "blocked_by_flag",
    "blocked_by_category",
    "blocked_by_readiness",
    "blocked_by_budget",
    "blocked_by_index_health",
}


@dataclass(frozen=True)
class WorkflowStageResult:
    stage_name: WorkflowStageName
    status: WorkflowStageStatus
    input_summary: dict[str, Any]
    output_summary: dict[str, Any]
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    duration_ms: float | None = None
    error_code: str | None = None
    review_reason: str | None = None
    trace_metadata: dict[str, Any] = field(default_factory=dict)

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage_name.value,
            "status": self.status.value,
            "duration_ms": None if self.duration_ms is None else _safe_float(self.duration_ms),
            "input_summary": sanitize_stage_summary(self.input_summary),
            "output_summary": sanitize_stage_summary(self.output_summary),
            "error_code": _safe_string("error_code", self.error_code),
            "review_reason": _safe_string("review_reason", self.review_reason),
        }


@dataclass(frozen=True)
class ReviewGateDecision:
    status: WorkflowStageStatus
    review_reasons: tuple[str, ...] = ()


class ReviewGate:
    def __init__(self, confidence_threshold: float = 0.5) -> None:
        self.confidence_threshold = confidence_threshold

    def evaluate(
        self,
        *,
        target: StudyTarget,
        evidence: EvidenceBundle,
        draft: StudyDraft,
        verification: StudyVerification,
        policy_status: str | None,
    ) -> ReviewGateDecision:
        reasons: list[str] = []
        if verification.needs_review:
            reasons.append("verification_failed")
        if verification.confidence < self.confidence_threshold:
            reasons.append("low_confidence")
        if not draft.citations:
            reasons.append("missing_citations")
        if not evidence.chunks:
            reasons.append("empty_evidence")
        if policy_status in _BLOCKED_POLICY_STATUSES and not evidence.fallback_reason:
            reasons.append("policy_blocked_without_fallback")
        if (
            evidence.fallback_reason
            and target in {StudyTarget.QUESTION, StudyTarget.OUTLINE_FRAGMENT}
        ):
            reasons.append("target_used_fallback_evidence")
        if evidence.metadata.get("step_budget_exhausted") is True:
            reasons.append("agentic_step_budget_exhausted")

        if reasons:
            return ReviewGateDecision(
                status=WorkflowStageStatus.NEEDS_REVIEW,
                review_reasons=tuple(dict.fromkeys(reasons)),
            )
        return ReviewGateDecision(status=WorkflowStageStatus.PASSED)


def new_workflow_id() -> str:
    return f"workflow-{uuid4().hex}"


def is_safe_workflow_id(value: Any) -> bool:
    return _safe_workflow_id(value) is not None


def sanitize_stage_summary(summary: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in summary.items():
        if key in _SAFE_STRING_VALUES:
            safe[key] = _safe_string(key, value)
        elif key in _SAFE_INT_KEYS:
            safe[key] = _safe_int(value)
        elif key in _SAFE_FLOAT_KEYS:
            safe[key] = _safe_float(value)
        elif key in _SAFE_BOOL_KEYS and isinstance(value, bool):
            safe[key] = value
        elif key == "workflow_id":
            safe_id = _safe_workflow_id(value)
            if safe_id is not None:
                safe[key] = safe_id
        elif key in {"request_id", "owner_id"}:
            safe_id = _safe_id(value)
            if safe_id is not None:
                safe[key] = safe_id
        elif key == "document_ids" and isinstance(value, (list, tuple)):
            safe_ids = [_safe_id(item) for item in value]
            safe[key] = [safe_id for safe_id in safe_ids if safe_id is not None]
        elif value is None and key in _SAFE_STRING_VALUES:
            safe[key] = None
    return safe


def summarize_workflow_status(stages: list[WorkflowStageResult]) -> WorkflowStatus:
    if any(stage.status == WorkflowStageStatus.FAILED for stage in stages):
        return WorkflowStatus.FAILED
    if any(stage.status == WorkflowStageStatus.NEEDS_REVIEW for stage in stages):
        return WorkflowStatus.NEEDS_REVIEW
    if any(
        stage.status
        in {
            WorkflowStageStatus.PENDING,
            WorkflowStageStatus.RUNNING,
            WorkflowStageStatus.SKIPPED,
        }
        for stage in stages
    ):
        return WorkflowStatus.PARTIAL
    if any(
        sanitize_stage_summary(stage.output_summary or {}).get("fallback_reason")
        not in {None, "unknown"}
        for stage in stages
    ):
        return WorkflowStatus.COMPLETED_WITH_FALLBACK
    if stages:
        return WorkflowStatus.COMPLETED
    return WorkflowStatus.PARTIAL


def build_workflow_payload(
    *,
    workflow_id: str,
    stages: list[WorkflowStageResult],
    needs_review: bool,
) -> dict[str, Any]:
    status = summarize_workflow_status(stages)
    current_stage = stages[-1].stage_name.value if stages else None
    return {
        "workflow_id": _safe_workflow_id(workflow_id),
        "status": status.value,
        "current_stage": current_stage,
        "needs_review": needs_review or status == WorkflowStatus.NEEDS_REVIEW,
        "stage_count": len(stages),
        "stages": [stage.to_safe_dict() for stage in stages],
    }


def sanitize_workflow_payload(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None

    workflow_id = _safe_workflow_id(payload.get("workflow_id"))
    if workflow_id is None:
        return None

    safe: dict[str, Any] = {"workflow_id": workflow_id}
    status = _allowed_safe_string("status", payload.get("status"))
    if status is not None:
        safe["status"] = status

    current_stage = _allowed_safe_string("stage", payload.get("current_stage"))
    if current_stage is not None:
        safe["current_stage"] = current_stage

    if isinstance(payload.get("needs_review"), bool):
        safe["needs_review"] = payload["needs_review"]

    safe_stages = _sanitize_workflow_stages(payload.get("stages"))
    safe["stage_count"] = len(safe_stages)
    safe["stages"] = safe_stages
    return safe


def _sanitize_workflow_stages(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    safe_stages: list[dict[str, Any]] = []
    for raw_stage in value:
        if not isinstance(raw_stage, dict):
            continue

        stage = _allowed_safe_string("stage", raw_stage.get("stage"))
        status = _allowed_safe_string("status", raw_stage.get("status"))
        if stage is None or status is None:
            continue

        safe_stage = {
            "stage": stage,
            "status": status,
            "duration_ms": _safe_float(raw_stage.get("duration_ms")),
            "input_summary": _sanitize_stage_summary_value(
                raw_stage.get("input_summary")
            ),
            "output_summary": _sanitize_stage_summary_value(
                raw_stage.get("output_summary")
            ),
            "error_code": _safe_string("error_code", raw_stage.get("error_code")),
            "review_reason": _safe_string("review_reason", raw_stage.get("review_reason")),
        }
        safe_stages.append(safe_stage)
    return safe_stages


def _sanitize_stage_summary_value(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return sanitize_stage_summary(value)


def _allowed_safe_string(key: str, value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value if value in _SAFE_STRING_VALUES[key] else None


def _safe_string(key: str, value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return "unknown"
    return value if value in _SAFE_STRING_VALUES[key] else "unknown"


def _safe_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        if isinstance(value, float) and not math.isfinite(value):
            return 0
        return int(value or 0)
    except (OverflowError, TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    try:
        safe_value = float(value or 0.0)
    except (OverflowError, TypeError, ValueError):
        return 0.0
    return safe_value if math.isfinite(safe_value) else 0.0


def _safe_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value if _SAFE_ID_PATTERN.fullmatch(value) else None


def _safe_workflow_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value if _GENERATED_WORKFLOW_ID_PATTERN.fullmatch(value) else None
