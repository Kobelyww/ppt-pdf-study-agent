from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from typing import Any
from uuid import uuid4
import re

from sqlalchemy import select

from src.db import StudyAgentTraceRecord
from src.services.study_agent import StudyAgentResult
from src.services.study_agent_workflow import sanitize_workflow_payload


_SAFE_POLICY_KEYS = {
    "selected_mode",
    "router_mode",
    "effective_mode",
    "category",
    "status",
    "reason",
    "fallback_chain",
    "readiness_status",
    "blocked_reason",
    "estimated_cost",
    "experiment_enabled",
    "policy_version",
}
_RETRIEVAL_MODES = {"simple_rag", "graph_rag_lite", "agentic_rag"}
_QUERY_CATEGORIES = {
    "direct_lookup",
    "definition",
    "concept_relation",
    "learning_path",
    "multi_document_synthesis",
    "question_generation",
    "outline_fragment",
    "unknown",
}
_POLICY_STATUSES = {
    "allowed",
    "blocked_by_flag",
    "blocked_by_category",
    "blocked_by_readiness",
    "blocked_by_budget",
    "blocked_by_index_health",
}
_READINESS_STATUSES = {"baseline", "candidate", "hold", "blocked"}
_ESTIMATED_COSTS = {"low", "medium", "balanced", "high"}
_POLICY_VERSIONS = {"rag-policy-v1"}
_POLICY_REASONS = {
    "simple_rag is always allowed",
    "advanced routing is disabled",
    "graph_rag_lite is disabled",
    "agentic_rag is disabled",
    "persisted chunks are required for advanced routing",
    "readiness snapshot is unavailable",
}


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
        safe_policy = safe_policy_metadata(result.audit_metadata.get("policy"))
        trace_metadata: dict[str, Any] = {
            "expected_term_count": len(result.request.expected_terms),
            "index_statuses": _safe_index_statuses(index_statuses or {}),
        }
        if safe_policy is not None:
            trace_metadata["policy"] = safe_policy
        workflow = sanitize_workflow_payload(result.audit_metadata.get("workflow"))
        if workflow is not None:
            trace_metadata["workflow"] = workflow

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
            trace_metadata=trace_metadata,
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

    def get_workflow(self, owner_id: str, workflow_id: str) -> dict[str, Any] | None:
        with self.session_factory() as session:
            records = session.scalars(
                select(StudyAgentTraceRecord).where(
                    StudyAgentTraceRecord.owner_id == owner_id,
                )
            )
            for record in records:
                workflow = sanitize_workflow_payload(
                    (record.trace_metadata or {}).get("workflow")
                )
                if workflow is not None and workflow.get("workflow_id") == workflow_id:
                    return workflow
        return None


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


def safe_policy_metadata(policy: Any) -> dict[str, Any] | None:
    if not isinstance(policy, Mapping):
        return None
    safe: dict[str, Any] = {}
    for key in _SAFE_POLICY_KEYS:
        if key not in policy:
            continue
        value = _safe_policy_value(key, policy.get(key))
        if value is not None:
            safe[key] = value
    return safe or None


def _safe_policy_value(key: str, value: Any) -> Any:
    if key in {"selected_mode", "router_mode", "effective_mode"}:
        return _allowed_string(value, _RETRIEVAL_MODES)
    if key == "category":
        return _allowed_string(value, _QUERY_CATEGORIES)
    if key == "status":
        return _allowed_string(value, _POLICY_STATUSES)
    if key in {"reason", "blocked_reason"}:
        return _safe_policy_reason(value)
    if key == "fallback_chain":
        return _safe_fallback_chain(value)
    if key == "readiness_status":
        return _allowed_string(value, _READINESS_STATUSES)
    if key == "estimated_cost":
        return _allowed_string(value, _ESTIMATED_COSTS)
    if key == "experiment_enabled":
        return value if isinstance(value, bool) else None
    if key == "policy_version":
        return _allowed_string(value, _POLICY_VERSIONS)
    return None


def _allowed_string(value: Any, allowed: set[str]) -> str | None:
    if not isinstance(value, str):
        return None
    return value if value in allowed else None


def _safe_policy_reason(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    if value in _POLICY_REASONS:
        return value
    for mode in _RETRIEVAL_MODES:
        if value == f"{mode} is allowed by route policy":
            return value
    for mode in _RETRIEVAL_MODES:
        for category in _QUERY_CATEGORIES:
            if value == f"{mode} is not candidate for {category}":
                return value
    for budget in _ESTIMATED_COSTS:
        if value == f"agentic_rag requires {budget} budget":
            return value
    for category in _QUERY_CATEGORIES:
        if value == f"{category} is not enabled":
            return value
    return None


def _safe_fallback_chain(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    modes = [item for item in value if isinstance(item, str) and item in _RETRIEVAL_MODES]
    return modes or None


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
    policy = safe_policy_metadata((record.trace_metadata or {}).get("policy"))
    if policy is not None:
        payload["policy"] = policy
    workflow = sanitize_workflow_payload((record.trace_metadata or {}).get("workflow"))
    if workflow is not None:
        payload["workflow"] = workflow
    return payload
