from __future__ import annotations

import math
import re
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from src.db.models import ReviewTaskRecord, utc_now


TARGET_TYPE = "study_agent_workflow"
OPEN_STATUS = "open"

_SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_:\.-]{1,128}$")
_SAFE_REASON_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_SAFE_MODE_VALUES = {"simple_rag", "graph_rag_lite", "agentic_rag"}
_SAFE_COUNT_KEYS = {
    "source_count",
    "chunk_count",
    "citation_count",
    "issue_count",
}
_TRACE_COUNT_KEY_MAP = {"used_chunk_count": "chunk_count"}
_SAFE_METRIC_KEYS = {
    "confidence",
    "source_recall",
    "answer_term_recall",
}


def workflow_needs_review(workflow: Any) -> bool:
    payload = _as_dict(workflow)
    if not payload:
        return False
    if payload.get("needs_review") is True:
        return True
    if payload.get("status") == "needs_review":
        return True

    for stage in _stage_dicts(payload):
        if stage.get("stage") == "review_gate" and stage.get("status") == "needs_review":
            return True
        output_summary = _as_dict(stage.get("output_summary"))
        if output_summary.get("needs_review") is True:
            return True
        if _safe_reason(stage.get("review_reason")) is not None:
            return True
        if _safe_reason(output_summary.get("review_reason")) is not None:
            return True
    return False


def review_reasons_from_workflow(workflow: Any) -> list[str]:
    reasons: list[str] = []
    for stage in _stage_dicts(_as_dict(workflow)):
        _append_reason(reasons, stage.get("review_reason"))
        output_summary = _as_dict(stage.get("output_summary"))
        _append_reason(reasons, output_summary.get("review_reason"))
    return reasons


def safe_review_task_metadata(
    *,
    workflow: Any,
    trace_payload: dict[str, Any] | None,
    result_audit_metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    workflow_payload = _as_dict(workflow)
    trace = trace_payload or {}
    audit = result_audit_metadata or {}
    metadata: dict[str, Any] = {}

    workflow_id = _safe_id(workflow_payload.get("workflow_id"))
    if workflow_id is not None:
        metadata["workflow_id"] = workflow_id

    trace_id = _safe_id(trace.get("trace_id"))
    if trace_id is not None:
        metadata["trace_id"] = trace_id

    selected_mode = _safe_mode(
        trace.get("selected_mode") or audit.get("selected_mode") or audit.get("mode")
    )
    if selected_mode is not None:
        metadata["selected_mode"] = selected_mode

    review_reasons = review_reasons_from_workflow(workflow_payload)
    if review_reasons:
        metadata["review_reasons"] = review_reasons

    for key in _SAFE_METRIC_KEYS:
        value = _first_present(trace, audit, workflow_payload, key)
        if value is not None:
            metadata[key] = _safe_float(value)

    for key in _SAFE_COUNT_KEYS:
        value = _first_present(trace, audit, workflow_payload, key)
        if value is not None:
            metadata[key] = _safe_int(value)

    for source_key, target_key in _TRACE_COUNT_KEY_MAP.items():
        if target_key not in metadata and source_key in trace:
            metadata[target_key] = _safe_int(trace[source_key])

    _fill_from_stage_summaries(metadata, workflow_payload)
    return metadata


class StudyAgentReviewTaskService:
    def __init__(self, session_factory: Any) -> None:
        self.session_factory = session_factory

    def ensure_for_workflow(
        self,
        *,
        owner_id: str,
        request_id: str,
        workflow: Any,
        trace_payload: dict[str, Any] | None,
        result_audit_metadata: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        workflow_payload = _as_dict(workflow)
        if not workflow_needs_review(workflow_payload):
            return None

        workflow_id = _safe_id(workflow_payload.get("workflow_id"))
        if workflow_id is None:
            return None

        metadata = safe_review_task_metadata(
            workflow=workflow_payload,
            trace_payload=trace_payload,
            result_audit_metadata=result_audit_metadata,
        )
        reason = (metadata.get("review_reasons") or ["needs_review"])[0]

        with self.session_factory() as session:
            existing = session.execute(
                select(ReviewTaskRecord).where(
                    ReviewTaskRecord.owner_id == owner_id,
                    ReviewTaskRecord.target_type == TARGET_TYPE,
                    ReviewTaskRecord.target_id == workflow_id,
                    ReviewTaskRecord.status == OPEN_STATUS,
                )
            ).scalars().first()
            if existing is not None:
                summary = _review_task_summary(existing)
                summary["_created"] = False
                return summary

            now = utc_now()
            record = ReviewTaskRecord(
                id=f"review-{uuid4().hex}",
                owner_id=owner_id,
                target_type=TARGET_TYPE,
                target_id=workflow_id,
                status=OPEN_STATUS,
                reason=reason,
                assignee=None,
                decision=None,
                comment=None,
                task_metadata=metadata,
                created_at=now,
                updated_at=now,
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            summary = _review_task_summary(record)
            summary["_created"] = True
            session.expunge(record)
            return summary


def _review_task_summary(record: ReviewTaskRecord) -> dict[str, Any]:
    metadata = record.task_metadata or {}
    return {
        "id": record.id,
        "target_type": record.target_type,
        "target_id": record.target_id,
        "status": record.status,
        "reason": record.reason,
        "metadata": metadata,
        "task_metadata": metadata,
    }


def _stage_dicts(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    stages = workflow.get("stages")
    if not isinstance(stages, list):
        return []
    return [stage for stage in stages if isinstance(stage, dict)]


def _append_reason(reasons: list[str], value: Any) -> None:
    reason = _safe_reason(value)
    if reason is not None and reason not in reasons:
        reasons.append(reason)


def _fill_from_stage_summaries(
    metadata: dict[str, Any], workflow_payload: dict[str, Any]
) -> None:
    for stage in _stage_dicts(workflow_payload):
        for summary_key in ("input_summary", "output_summary"):
            summary = _as_dict(stage.get(summary_key))
            selected_mode = _safe_mode(summary.get("selected_mode"))
            if "selected_mode" not in metadata and selected_mode is not None:
                metadata["selected_mode"] = selected_mode
            for key in _SAFE_METRIC_KEYS:
                if key not in metadata and key in summary:
                    metadata[key] = _safe_float(summary[key])
            for key in _SAFE_COUNT_KEYS:
                if key not in metadata and key in summary:
                    metadata[key] = _safe_int(summary[key])


def _first_present(
    first: dict[str, Any],
    second: dict[str, Any],
    third: dict[str, Any],
    key: str,
) -> Any:
    for source in (first, second, third):
        if key in source:
            return source[key]
    return None


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value if _SAFE_ID_PATTERN.fullmatch(value) else None


def _safe_mode(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value if value in _SAFE_MODE_VALUES else None


def _safe_reason(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value if _SAFE_REASON_PATTERN.fullmatch(value) else None


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
