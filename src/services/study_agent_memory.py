from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from src.db import StudyAgentMemoryRecord


SAFE_PREFERENCES = {
    "answer_style": {"concise", "detailed", "exam_focused", "bilingual"},
    "difficulty": {"basic", "intermediate", "advanced"},
    "language": {"zh", "en", "bilingual"},
}

SAFE_REVIEW_REASONS = {
    "verification_failed",
    "low_confidence",
    "missing_citations",
    "empty_evidence",
    "policy_blocked_without_fallback",
    "target_used_fallback_evidence",
    "agentic_step_budget_exhausted",
}

SAFE_REVIEW_DECISIONS = {"accepted", "rejected", "needs_revision", "resolved"}
SAFE_REVIEW_METRICS = {"confidence", "source_count", "chunk_count"}
SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_:\.-]{1,128}$")


class StudyAgentMemoryService:
    def __init__(self, session_factory: sessionmaker[Session]):
        self.session_factory = session_factory

    def store_preference(
        self,
        owner_id: str,
        key: str,
        value: str,
        source_id: str,
        expires_at: datetime | None = None,
    ) -> str:
        if key not in SAFE_PREFERENCES or value not in SAFE_PREFERENCES[key]:
            raise ValueError("unsupported preference key or value")
        self._validate_safe_id("source_id", source_id)

        memory_id = f"memory-{uuid4().hex}"
        with self.session_factory() as session:
            session.add(
                StudyAgentMemoryRecord(
                    id=memory_id,
                    owner_id=owner_id,
                    scope_type="user",
                    scope_id=owner_id,
                    category="user_preference",
                    key=key,
                    value_json={"value": value},
                    confidence=1.0,
                    source_type="explicit_preference",
                    source_id=source_id,
                    privacy_level="safe_metadata",
                    expires_at=expires_at,
                )
            )
            session.commit()
        return memory_id

    def store_review_outcome(
        self,
        owner_id: str,
        workflow_id: str,
        review_task_id: str,
        reasons: list[str],
        decision: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        self._validate_safe_id("workflow_id", workflow_id)
        self._validate_safe_id("review_task_id", review_task_id)

        safe_reasons = [reason for reason in reasons if reason in SAFE_REVIEW_REASONS]
        if not safe_reasons:
            raise ValueError("review outcome requires at least one safe reason")

        unsafe_reasons = [reason for reason in reasons if reason not in SAFE_REVIEW_REASONS]
        if unsafe_reasons:
            raise ValueError("unsupported review reason")

        safe_decision = decision if decision in SAFE_REVIEW_DECISIONS else "resolved"
        safe_metrics = self._safe_metrics(metadata or {})
        confidence = safe_metrics.get("confidence", 1.0)
        memory_id = f"memory-{uuid4().hex}"

        with self.session_factory() as session:
            session.add(
                StudyAgentMemoryRecord(
                    id=memory_id,
                    owner_id=owner_id,
                    scope_type="workflow",
                    scope_id=workflow_id,
                    category="review_outcome",
                    key=review_task_id,
                    value_json={
                        "decision": safe_decision,
                        "reasons": safe_reasons,
                        "metrics": safe_metrics,
                    },
                    confidence=float(confidence),
                    source_type="review_task",
                    source_id=review_task_id,
                    privacy_level="safe_metadata",
                )
            )
            session.commit()
        return memory_id

    def summary(self, owner_id: str) -> dict[str, Any]:
        with self.session_factory() as session:
            records = session.scalars(
                select(StudyAgentMemoryRecord)
                .where(StudyAgentMemoryRecord.owner_id == owner_id)
                .order_by(
                    StudyAgentMemoryRecord.category,
                    StudyAgentMemoryRecord.key,
                    StudyAgentMemoryRecord.created_at,
                    StudyAgentMemoryRecord.id,
                )
            ).all()

        active_records = [record for record in records if not self._is_expired(record.expires_at)]
        preferences: dict[str, str] = {}
        review_reason_counts: dict[str, int] = {}

        for record in active_records:
            value = record.value_json or {}
            if record.category == "user_preference":
                preference = value.get("value")
                if record.key in SAFE_PREFERENCES and preference in SAFE_PREFERENCES[record.key]:
                    preferences[record.key] = preference
            elif record.category == "review_outcome":
                for reason in value.get("reasons", []):
                    if reason in SAFE_REVIEW_REASONS:
                        review_reason_counts[reason] = review_reason_counts.get(reason, 0) + 1

        return {
            "preferences": dict(sorted(preferences.items())),
            "review_reason_counts": dict(sorted(review_reason_counts.items())),
            "memory_record_count": len(active_records),
        }

    def delete_memory(self, owner_id: str, memory_id: str) -> bool:
        with self.session_factory() as session:
            record = session.get(StudyAgentMemoryRecord, memory_id)
            if record is None or record.owner_id != owner_id:
                return False

            session.delete(record)
            session.commit()
            return True

    @staticmethod
    def _safe_metrics(metadata: dict[str, Any]) -> dict[str, float | int]:
        safe_metrics: dict[str, float | int] = {}
        for key in SAFE_REVIEW_METRICS:
            value = metadata.get(key)
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                safe_metrics[key] = value
        return dict(sorted(safe_metrics.items()))

    @staticmethod
    def _validate_safe_id(field_name: str, value: str) -> None:
        if not isinstance(value, str) or SAFE_ID_PATTERN.fullmatch(value) is None:
            raise ValueError(f"invalid {field_name}")

    @staticmethod
    def _is_expired(expires_at: datetime | None) -> bool:
        if expires_at is None:
            return False
        now = datetime.now(timezone.utc)
        comparable_expires_at = expires_at
        if comparable_expires_at.tzinfo is None:
            comparable_expires_at = comparable_expires_at.replace(tzinfo=timezone.utc)
        return comparable_expires_at <= now
