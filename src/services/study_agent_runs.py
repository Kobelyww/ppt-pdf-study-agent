from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any
from uuid import uuid4
import re

from sqlalchemy import desc, select

from src.db import StudyAgentRunRecord


RUN_STATUSES = {
    "queued",
    "running",
    "paused",
    "completed",
    "needs_review",
    "failed",
    "cancelled",
    "timed_out",
    "archived",
}
TERMINAL_STATUSES = {
    "completed",
    "needs_review",
    "failed",
    "cancelled",
    "timed_out",
    "archived",
}
RETRYABLE_STATUSES = {"failed", "cancelled", "timed_out", "needs_review"}
RESULT_SUMMARY_KEYS = {
    "trace_id",
    "workflow_id",
    "review_task_id",
    "selected_mode",
    "policy_status",
    "category",
    "source_count",
    "used_chunk_count",
    "confidence",
    "source_recall",
    "answer_term_recall",
    "needs_review",
    "latency_ms",
    "stage_count",
    "expert_enabled",
    "expert_branch_count",
    "expert_timeout_count",
    "expert_failure_count",
}
SAFE_ERROR_LABELS = {
    "authentication_required",
    "document_evidence_missing",
    "unsupported_study_target",
    "unsupported_retrieval_mode",
    "forbidden_document",
    "bad_study_request",
    "run_conflict",
    "run_cancelled",
    "run_timed_out",
    "run_failed",
    "unknown",
}
_ALLOWED_TRANSITIONS = {
    "queued": {"running", "paused", "cancelled"},
    "running": {"completed", "needs_review", "failed", "paused", "cancelled", "timed_out"},
    "paused": {"queued", "cancelled"},
    "completed": {"archived"},
    "needs_review": {"archived"},
    "failed": {"archived"},
    "cancelled": {"archived"},
    "timed_out": {"archived"},
    "archived": set(),
}


class StudyAgentRunNotFound(Exception):
    pass


class StudyAgentRunConflict(Exception):
    pass


class StudyAgentRunService:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    def create_run(
        self,
        *,
        owner_id: str,
        request_id: str,
        payload: dict,
        retry_of_run_id: str | None = None,
        attempt: int = 1,
    ) -> dict:
        safe_payload = _safe_request_payload(payload)
        record = StudyAgentRunRecord(
            id=f"run-{uuid4().hex}",
            owner_id=owner_id,
            request_id=request_id,
            status="queued",
            query_hash=_query_hash(str(payload.get("query") or "")),
            target=safe_payload["target"],
            document_ids=safe_payload["document_ids"],
            preferred_mode=safe_payload["preferred_mode"],
            budget=safe_payload["budget"],
            skill_name=safe_payload["skill_name"],
            skill_version=safe_payload["skill_version"],
            expected_term_count=safe_payload["expected_term_count"],
            retry_of_run_id=retry_of_run_id,
            attempt=max(1, int(attempt or 1)),
            result_summary={},
            lifecycle_metadata={},
        )

        with self.session_factory() as session:
            session.add(record)
            session.commit()
            return _serialize_run(record)

    def create_retry_run(
        self,
        *,
        owner_id: str,
        request_id: str,
        parent_run_id: str,
        payload: dict,
    ) -> dict:
        with self.session_factory() as session:
            parent = self._get_owned_record(session, owner_id, parent_run_id)
            if parent.status not in RETRYABLE_STATUSES:
                raise StudyAgentRunConflict(
                    f"Cannot retry run {parent.id} from status {parent.status}."
                )
            attempt = parent.attempt + 1

        return self.create_run(
            owner_id=owner_id,
            request_id=request_id,
            payload=payload,
            retry_of_run_id=parent_run_id,
            attempt=attempt,
        )

    def list_runs(
        self,
        *,
        owner_id: str,
        status: str | None = None,
        include_archived: bool = False,
        limit: int = 20,
    ) -> list[dict]:
        with self.session_factory() as session:
            query = select(StudyAgentRunRecord).where(StudyAgentRunRecord.owner_id == owner_id)
            if status is not None:
                if status not in RUN_STATUSES:
                    raise StudyAgentRunConflict(f"Unknown run status: {status}")
                query = query.where(StudyAgentRunRecord.status == status)
            elif not include_archived:
                query = query.where(StudyAgentRunRecord.status != "archived")

            records = session.scalars(
                query.order_by(desc(StudyAgentRunRecord.created_at)).limit(_safe_limit(limit))
            ).all()
            return [_serialize_run(record) for record in records]

    def get_run(self, *, owner_id: str, run_id: str) -> dict | None:
        with self.session_factory() as session:
            record = session.scalar(
                select(StudyAgentRunRecord).where(
                    StudyAgentRunRecord.owner_id == owner_id,
                    StudyAgentRunRecord.id == run_id,
                )
            )
            return _serialize_run(record) if record is not None else None

    def run_exists(self, run_id: str) -> bool:
        with self.session_factory() as session:
            return session.get(StudyAgentRunRecord, run_id) is not None

    def mark_running(self, *, owner_id: str, run_id: str) -> dict:
        with self.session_factory() as session:
            record = self._transition(session, owner_id, run_id, "running")
            record.started_at = record.started_at or _utc_now()
            session.commit()
            return _serialize_run(record)

    def mark_terminal(
        self,
        *,
        owner_id: str,
        run_id: str,
        status: str,
        result_summary: dict | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> dict:
        if status not in {"completed", "needs_review", "failed", "timed_out"}:
            raise StudyAgentRunConflict(f"Unsupported terminal status: {status}")

        safe_summary = _sanitize_result_summary(result_summary or {})
        with self.session_factory() as session:
            record = self._transition(session, owner_id, run_id, status)
            record.result_summary = safe_summary
            record.trace_id = safe_summary.get("trace_id")
            record.workflow_id = safe_summary.get("workflow_id")
            record.review_task_id = safe_summary.get("review_task_id")
            record.selected_mode = safe_summary.get("selected_mode") or record.selected_mode
            safe_error_code = _safe_error_label(error_code)
            safe_error_message = _safe_error_label(error_message)
            if safe_error_message == "unknown" and safe_error_code is not None:
                safe_error_message = safe_error_code
            record.error_code = safe_error_code
            record.error_message = safe_error_message
            record.completed_at = _utc_now()
            session.commit()
            return _serialize_run(record)

    def cancel(self, *, owner_id: str, run_id: str) -> dict:
        with self.session_factory() as session:
            record = self._transition(session, owner_id, run_id, "cancelled")
            record.cancelled_at = _utc_now()
            session.commit()
            return _serialize_run(record)

    def pause(self, *, owner_id: str, run_id: str) -> dict:
        with self.session_factory() as session:
            record = self._transition(session, owner_id, run_id, "paused")
            record.paused_at = _utc_now()
            session.commit()
            return _serialize_run(record)

    def resume(self, *, owner_id: str, run_id: str) -> dict:
        with self.session_factory() as session:
            record = self._transition(session, owner_id, run_id, "queued")
            record.paused_at = None
            session.commit()
            return _serialize_run(record)

    def archive(self, *, owner_id: str, run_id: str) -> dict:
        with self.session_factory() as session:
            record = self._transition(session, owner_id, run_id, "archived")
            record.archived_at = _utc_now()
            session.commit()
            return _serialize_run(record)

    def _get_owned_record(self, session, owner_id: str, run_id: str) -> StudyAgentRunRecord:
        record = session.scalar(
            select(StudyAgentRunRecord).where(
                StudyAgentRunRecord.owner_id == owner_id,
                StudyAgentRunRecord.id == run_id,
            )
        )
        if record is None:
            raise StudyAgentRunNotFound(f"Study Agent run not found: {run_id}")
        return record

    def _transition(
        self,
        session,
        owner_id: str,
        run_id: str,
        next_status: str,
    ) -> StudyAgentRunRecord:
        if next_status not in RUN_STATUSES:
            raise StudyAgentRunConflict(f"Unknown run status: {next_status}")

        record = self._get_owned_record(session, owner_id, run_id)
        if next_status not in _ALLOWED_TRANSITIONS.get(record.status, set()):
            raise StudyAgentRunConflict(
                f"Cannot transition run {record.id} from {record.status} to {next_status}."
            )

        record.status = next_status
        metadata = dict(record.lifecycle_metadata or {})
        metadata["transition_count"] = int(metadata.get("transition_count") or 0) + 1
        metadata["last_transition"] = next_status
        record.lifecycle_metadata = metadata
        return record


def _safe_request_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    expected_terms = payload.get("expected_terms")
    if isinstance(expected_terms, list):
        expected_term_count = len(expected_terms)
    else:
        expected_term_count = _safe_int(payload.get("expected_term_count"))

    return {
        "target": _safe_string(payload.get("target"), default="answer"),
        "document_ids": _safe_document_ids(payload.get("document_ids")),
        "preferred_mode": _safe_optional_string(payload.get("preferred_mode")),
        "budget": _safe_optional_string(payload.get("budget")),
        "skill_name": _safe_optional_string(payload.get("skill_name")),
        "skill_version": _safe_optional_string(payload.get("skill_version")),
        "expected_term_count": expected_term_count,
    }


def _sanitize_result_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key in RESULT_SUMMARY_KEYS:
        if key not in summary:
            continue
        value = summary[key]
        if key in {
            "source_count",
            "used_chunk_count",
            "stage_count",
            "expert_branch_count",
            "expert_timeout_count",
            "expert_failure_count",
        }:
            safe[key] = _safe_int(value)
        elif key in {
            "confidence",
            "source_recall",
            "answer_term_recall",
            "latency_ms",
        }:
            safe[key] = _safe_float(value)
        elif key in {"needs_review", "expert_enabled"}:
            if isinstance(value, bool):
                safe[key] = value
        else:
            label = _safe_optional_string(value)
            if label is not None:
                safe[key] = label
    return safe


def _serialize_run(record: StudyAgentRunRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "request_id": record.request_id,
        "status": record.status,
        "query_hash": record.query_hash,
        "target": record.target,
        "document_ids": list(record.document_ids or []),
        "preferred_mode": record.preferred_mode,
        "selected_mode": record.selected_mode,
        "budget": record.budget,
        "skill_name": record.skill_name,
        "skill_version": record.skill_version,
        "expected_term_count": record.expected_term_count,
        "workflow_id": record.workflow_id,
        "trace_id": record.trace_id,
        "review_task_id": record.review_task_id,
        "retry_of_run_id": record.retry_of_run_id,
        "attempt": record.attempt,
        "result_summary": _sanitize_result_summary(record.result_summary or {}),
        "error_code": record.error_code,
        "error_message": record.error_message,
        "lifecycle_metadata": dict(record.lifecycle_metadata or {}),
        "created_at": _isoformat(record.created_at),
        "updated_at": _isoformat(record.updated_at),
        "started_at": _isoformat(record.started_at),
        "completed_at": _isoformat(record.completed_at),
        "cancelled_at": _isoformat(record.cancelled_at),
        "paused_at": _isoformat(record.paused_at),
        "archived_at": _isoformat(record.archived_at),
    }


def _query_hash(query: str) -> str:
    normalized = re.sub(r"\s+", " ", query.strip().lower())
    return "sha256:" + sha256(normalized.encode("utf-8")).hexdigest()


def _safe_document_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    ids: list[str] = []
    for item in value:
        label = _safe_optional_string(item)
        if label is not None:
            ids.append(label)
    return ids


def _safe_string(value: Any, *, default: str) -> str:
    safe = _safe_optional_string(value)
    return safe if safe is not None else default


def _safe_optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped or len(stripped) > 255:
        return None
    if "\n" in stripped or "\r" in stripped:
        return None
    return stripped


def _safe_short_label(value: Any) -> str | None:
    label = _safe_optional_string(value)
    if label is None:
        return None
    return label[:128]


def _safe_error_label(value: Any) -> str | None:
    label = _safe_optional_string(value)
    if label is None:
        return None
    normalized = label.strip().lower()
    if normalized in SAFE_ERROR_LABELS:
        return normalized
    return "unknown"


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_limit(value: int) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return 20
    return min(max(limit, 1), 100)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
