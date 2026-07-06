from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
from time import perf_counter
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import sessionmaker

from src.api.request_context import get_user_context
from src.security.audit import record_audit_event
from src.services.study_agent_documents import StudyAgentDocumentError
from src.services.study_agent_index import StudyDocumentIndexService
from src.services.study_agent_memory import StudyAgentMemoryService
from src.services.study_agent_runtime import StudyAgentRuntimeService
from src.services.study_agent_trace import StudyAgentTraceService, safe_policy_metadata
from src.services.study_agent_review_tasks import StudyAgentReviewTaskService
from src.services.study_agent_workflow import sanitize_workflow_payload


class StudyAgentQueryRequest(BaseModel):
    query: str = Field(min_length=1)
    target: str | None = None
    document_ids: list[str] | None = None
    preferred_mode: str | None = None
    budget: str | None = None
    expected_terms: list[str] | None = None

    @field_validator("query")
    @classmethod
    def query_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be empty")
        return value


router = APIRouter(prefix="/api/study-agent", tags=["study-agent"])


@router.post("/query")
async def query_study_agent(
    payload: StudyAgentQueryRequest,
    request: Request,
) -> dict[str, Any]:
    context = get_user_context(request)
    runner = _study_agent_runner(request)
    if runner is None:
        raise HTTPException(status_code=503, detail="Study agent is not configured")
    payload_data = payload.model_dump(exclude_none=True)
    payload_data["authenticated_user_id"] = context.user_id
    payload_data["request_id"] = context.request_id
    started_at = perf_counter()
    try:
        result = await runner.run(payload_data)
        latency_ms = getattr(result, "audit_metadata", {}).get("latency_ms")
        if latency_ms is None:
            latency_ms = round((perf_counter() - started_at) * 1000, 3)
    except StudyAgentDocumentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    trace_payload = _record_study_agent_trace(
        request,
        actor_id=context.user_id,
        request_id=context.request_id,
        result=result,
        latency_ms=latency_ms,
    )
    _record_study_agent_audit(
        request,
        actor_id=context.user_id,
        request_id=context.request_id,
        result=result,
        payload=payload_data,
        trace_payload=trace_payload,
    )
    response_payload = _to_jsonable(result)
    if isinstance(response_payload, dict):
        response_payload.pop("audit_metadata", None)
    audit_metadata = getattr(result, "audit_metadata", {}) or {}
    policy = safe_policy_metadata(audit_metadata.get("policy"))
    if policy is not None:
        response_payload["policy"] = policy
    workflow = sanitize_workflow_payload(audit_metadata.get("workflow"))
    if workflow is not None:
        response_payload["workflow"] = workflow
        review_task = _ensure_study_agent_review_task(
            request,
            actor_id=context.user_id,
            request_id=context.request_id,
            workflow=workflow,
            trace_payload=trace_payload,
            audit_metadata=audit_metadata,
        )
        if review_task is not None:
            response_payload["review_task"] = review_task
    if trace_payload is not None:
        response_payload["trace"] = trace_payload
    return response_payload


@router.get("/traces/{trace_id}")
def get_study_agent_trace(request: Request, trace_id: str) -> dict[str, Any]:
    context = get_user_context(request)
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        raise HTTPException(
            status_code=503,
            detail="Study agent trace store is not configured",
        )
    trace = StudyAgentTraceService(session_factory).get_trace(
        owner_id=context.user_id,
        trace_id=trace_id,
    )
    if trace is None:
        raise HTTPException(status_code=404, detail="Trace not found")
    return trace


@router.get("/workflows/{workflow_id}")
def get_study_agent_workflow(request: Request, workflow_id: str) -> dict[str, Any]:
    context = get_user_context(request)
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        raise HTTPException(
            status_code=503,
            detail="Study agent trace store is not configured",
        )
    workflow = StudyAgentTraceService(session_factory).get_workflow(
        owner_id=context.user_id,
        workflow_id=workflow_id,
    )
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow


@router.get("/index-summary")
def get_study_agent_index_summary(request: Request) -> dict[str, Any]:
    context = get_user_context(request)
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        return {
            "owner_id": context.user_id,
            "total_documents": 0,
            "status_counts": {},
            "fallback_reason_counts": {},
            "documents": [],
        }
    return StudyDocumentIndexService(session_factory=session_factory).summary(
        owner_id=context.user_id
    )


@router.get("/memories/summary")
def get_study_agent_memory_summary(request: Request) -> dict[str, Any]:
    context = get_user_context(request)
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        return {
            "preferences": {},
            "review_reason_counts": {},
            "memory_record_count": 0,
        }
    return StudyAgentMemoryService(
        _non_expiring_session_factory(session_factory)
    ).summary(context.user_id)


@router.delete("/memories/{memory_id}")
def delete_study_agent_memory(request: Request, memory_id: str) -> dict[str, str]:
    context = get_user_context(request)
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        raise HTTPException(
            status_code=503,
            detail="Study agent memory store is not configured",
        )
    deleted = StudyAgentMemoryService(
        _non_expiring_session_factory(session_factory)
    ).delete_memory(context.user_id, memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"id": memory_id, "status": "deleted"}


def _study_agent_runner(request: Request) -> Any | None:
    orchestrator = getattr(request.app.state, "study_agent_orchestrator", None)
    if orchestrator is not None:
        return orchestrator

    runtime = getattr(request.app.state, "study_agent_runtime_service", None)
    if runtime is not None:
        return runtime

    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        return None

    runtime = StudyAgentRuntimeService(session_factory=session_factory)
    request.app.state.study_agent_runtime_service = runtime
    return runtime


def _to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {key: _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    return value


def _record_study_agent_trace(
    request: Request,
    *,
    actor_id: str,
    request_id: str,
    result: Any,
    latency_ms: int | float,
) -> dict[str, Any] | None:
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        return _trace_payload_without_persistence(
            request_id=request_id,
            result=result,
            latency_ms=latency_ms,
        )
    service = StudyAgentTraceService(_non_expiring_session_factory(session_factory))
    audit_metadata = getattr(result, "audit_metadata", {}) or {}
    return service.record_success(
        owner_id=actor_id,
        request_id=request_id,
        result=result,
        latency_ms=latency_ms,
        index_statuses=audit_metadata.get("index_statuses") or {},
    )


def _non_expiring_session_factory(session_factory: Any) -> Any:
    kwargs = getattr(session_factory, "kw", None)
    if not isinstance(kwargs, dict) or kwargs.get("expire_on_commit") is False:
        return session_factory

    return sessionmaker(**{**kwargs, "expire_on_commit": False})


def _trace_payload_without_persistence(
    *,
    request_id: str,
    result: Any,
    latency_ms: int | float,
) -> dict[str, Any]:
    audit_metadata = getattr(result, "audit_metadata", {}) or {}
    trace_payload = {
        "trace_id": "trace-unpersisted",
        "request_id": request_id,
        "selected_mode": audit_metadata.get("mode"),
        "route_reason": getattr(result.plan, "reason", None),
        "chunk_source": audit_metadata.get("chunk_source"),
        "fallback_reason": audit_metadata.get("fallback_reason"),
        "document_count": len(getattr(result.request, "document_ids", ()) or ()),
        "source_count": audit_metadata.get("source_count", len(result.evidence.sources)),
        "used_chunk_count": result.draft.used_chunk_count,
        "confidence": result.verification.confidence,
        "source_recall": result.verification.source_recall,
        "answer_term_recall": result.verification.answer_term_recall,
        "needs_review": result.verification.needs_review,
        "latency_ms": latency_ms,
    }
    policy = safe_policy_metadata(audit_metadata.get("policy"))
    if policy is not None:
        trace_payload["policy"] = policy
    workflow = sanitize_workflow_payload(audit_metadata.get("workflow"))
    if workflow is not None:
        trace_payload["workflow"] = workflow
    return trace_payload


def _record_study_agent_audit(
    request: Request,
    *,
    actor_id: str,
    request_id: str,
    result: Any,
    payload: dict[str, Any],
    trace_payload: dict[str, Any] | None = None,
) -> None:
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        return

    audit_metadata = getattr(result, "audit_metadata", {}) or {}
    policy = safe_policy_metadata(audit_metadata.get("policy")) or {}
    metadata = {
        "trace_id": trace_payload.get("trace_id") if trace_payload else None,
        "policy_version": policy.get("policy_version"),
        "category": policy.get("category"),
        "router_mode": policy.get("router_mode"),
        "selected_mode": policy.get("selected_mode") or audit_metadata.get("mode"),
        "policy_status": policy.get("status") or "not_applied",
        "needs_review": audit_metadata.get("needs_review"),
        "fallback_reason": audit_metadata.get("fallback_reason")
        or (trace_payload or {}).get("fallback_reason")
        or "none",
        "latency_ms": audit_metadata.get("latency_ms") or (trace_payload or {}).get("latency_ms"),
    }
    record_audit_event(
        session_factory=session_factory,
        actor_id=actor_id,
        action="study_agent.query",
        resource_type="study_agent",
        resource_id=request_id or "study-agent-query",
        request_id=request_id,
        metadata=metadata,
    )


def _ensure_study_agent_review_task(
    request: Request,
    *,
    actor_id: str,
    request_id: str,
    workflow: dict[str, Any],
    trace_payload: dict[str, Any] | None,
    audit_metadata: dict[str, Any],
) -> dict[str, Any] | None:
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        return None

    task = StudyAgentReviewTaskService(
        _non_expiring_session_factory(session_factory)
    ).ensure_for_workflow(
        owner_id=actor_id,
        request_id=request_id,
        workflow=workflow,
        trace_payload=trace_payload,
        result_audit_metadata=audit_metadata,
    )
    if task is None:
        return None

    created = bool(task.pop("_created", False))
    metadata = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
    trace_id = metadata.get("trace_id")
    workflow_id = metadata.get("workflow_id") or task.get("target_id")
    record_audit_event(
        session_factory=_non_expiring_session_factory(session_factory),
        actor_id=actor_id,
        action="review_task.created" if created else "review_task.linked",
        resource_type="review_task",
        resource_id=task["id"],
        request_id=request_id,
        metadata={
            "target_type": task.get("target_type"),
            "target_id": task.get("target_id"),
            "reason": task.get("reason"),
            "workflow_id": workflow_id,
            "trace_id": trace_id,
        },
    )
    return task
