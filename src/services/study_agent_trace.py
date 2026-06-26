from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from typing import Any
from uuid import uuid4
import re

from sqlalchemy import select

from src.db import StudyAgentTraceRecord
from src.services.study_agent import StudyAgentResult


class StudyAgentTraceService:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    def record_success(
        self,
        owner_id: str,
        request_id: str,
        result: StudyAgentResult,
        latency_ms: float,
        index_statuses: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        record = StudyAgentTraceRecord(
            id=f"trace-{uuid4().hex}",
            owner_id=owner_id,
            request_id=request_id,
            query_hash=_query_hash(result.request.query),
            target=result.request.target.value,
            document_ids=list(result.request.document_ids),
            selected_mode=result.plan.mode.value,
            route_reason=result.plan.reason,
            estimated_cost=result.plan.estimated_cost,
            fallback_chain=[mode.value for mode in result.plan.fallbacks],
            chunk_source=result.audit_metadata.get("chunk_source"),
            fallback_reason=result.audit_metadata.get("fallback_reason"),
            source_count=len(result.evidence.sources),
            used_chunk_count=result.draft.used_chunk_count,
            confidence=result.verification.confidence,
            source_recall=result.verification.source_recall,
            answer_term_recall=result.verification.answer_term_recall,
            needs_review=result.verification.needs_review,
            latency_ms=latency_ms,
            trace_metadata={
                "expected_term_count": len(result.request.expected_terms),
                "index_statuses": _safe_index_statuses(index_statuses or {}),
            },
        )

        with self.session_factory() as session:
            session.add(record)
            session.commit()

        return _trace_payload(record)

    def get_trace(self, owner_id: str, trace_id: str) -> dict[str, Any] | None:
        with self.session_factory() as session:
            record = session.scalar(
                select(StudyAgentTraceRecord).where(
                    StudyAgentTraceRecord.owner_id == owner_id,
                    StudyAgentTraceRecord.id == trace_id,
                )
            )
            if record is None:
                return None
            return _trace_payload(record, include_hash=True)


def _query_hash(query: str) -> str:
    normalized = re.sub(r"\s+", " ", query.strip().lower())
    return "sha256:" + sha256(normalized.encode("utf-8")).hexdigest()


def _safe_index_statuses(index_statuses: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    safe_statuses: dict[str, dict[str, Any]] = {}
    for key, raw_status in index_statuses.items():
        if not isinstance(raw_status, Mapping):
            continue

        safe_statuses[str(key)] = {
            "status": raw_status.get("status"),
            "fallback_reason": raw_status.get("fallback_reason"),
            "chunk_count": _safe_int(raw_status.get("chunk_count")),
        }
    return safe_statuses


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _trace_payload(
    record: StudyAgentTraceRecord,
    include_hash: bool = False,
) -> dict[str, Any]:
    payload = {
        "trace_id": record.id,
        "request_id": record.request_id,
        "selected_mode": record.selected_mode,
        "route_reason": record.route_reason,
        "chunk_source": record.chunk_source,
        "fallback_reason": record.fallback_reason,
        "document_count": len(record.document_ids or []),
        "source_count": record.source_count,
        "used_chunk_count": record.used_chunk_count,
        "confidence": record.confidence,
        "source_recall": record.source_recall,
        "answer_term_recall": record.answer_term_recall,
        "needs_review": record.needs_review,
        "latency_ms": record.latency_ms,
    }
    if include_hash:
        payload["query_hash"] = record.query_hash
    return payload
