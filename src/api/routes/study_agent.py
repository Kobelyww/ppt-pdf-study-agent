from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
from time import perf_counter
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import sessionmaker

from src.api.request_context import get_user_context
from src.security.audit import record_audit_event
from src.services.study_agent_documents import StudyAgentDocumentError
from src.services.study_agent_index import StudyDocumentIndexService
from src.services.study_agent_memory import StudyAgentMemoryService
from src.services.study_agent_runtime import StudyAgentRuntimeService
from src.services.study_agent_skill_performance import StudyAgentSkillPerformanceService
from src.services.study_agent_skills import StudySkillRegistry
from src.services.study_agent_trace import (
    StudyAgentTraceService,
    safe_expert_metadata,
    safe_policy_metadata,
    safe_skill_metadata,
)
from src.services.study_agent_review_tasks import StudyAgentReviewTaskService
from src.services.study_agent_runs import (
    StudyAgentRunConflict,
    StudyAgentRunNotFound,
    StudyAgentRunService,
)
from src.services.study_agent_workflow import sanitize_workflow_payload


class StudyAgentQueryRequest(BaseModel):
    query: str = Field(min_length=1)
    target: str | None = None
    document_ids: list[str] | None = None
    preferred_mode: str | None = None
    budget: str | None = None
    expected_terms: list[str] | None = None
    skill_name: str | None = None
    skill_version: str | None = None

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
    return await _execute_study_agent_query(request, payload, context=context)


@router.post("/runs")
async def create_study_agent_run(
    payload: StudyAgentQueryRequest,
    request: Request,
) -> dict[str, Any]:
    context = get_user_context(request)
    service = _study_agent_run_service(request)
    if _study_agent_runner(request) is None:
        raise HTTPException(status_code=503, detail="Study agent is not configured")
    payload_data = payload.model_dump(exclude_none=True)
    run = service.create_run(
        owner_id=context.user_id,
        request_id=context.request_id,
        payload=payload_data,
    )
    _record_study_agent_run_audit(
        request,
        actor_id=context.user_id,
        request_id=context.request_id,
        action="study_agent_run.created",
        run=run,
    )
    return await _execute_study_agent_run(
        request,
        payload,
        context=context,
        service=service,
        run=run,
    )


@router.get("/runs")
def list_study_agent_runs(
    request: Request,
    status: str | None = None,
    include_archived: bool = False,
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    context = get_user_context(request)
    service = _study_agent_run_service(request)
    try:
        runs = service.list_runs(
            owner_id=context.user_id,
            status=status,
            include_archived=include_archived,
            limit=limit,
        )
    except StudyAgentRunConflict as exc:
        raise HTTPException(status_code=409, detail="Invalid run transition") from exc
    return {"runs": runs}


@router.get("/runs/{run_id}")
def get_study_agent_run(request: Request, run_id: str) -> dict[str, Any]:
    context = get_user_context(request)
    service = _study_agent_run_service(request)
    run = service.get_run(owner_id=context.user_id, run_id=run_id)
    if run is None:
        _raise_run_not_found_or_forbidden(service, run_id)
    return run


@router.post("/runs/{run_id}/cancel")
def cancel_study_agent_run(request: Request, run_id: str) -> dict[str, Any]:
    context = get_user_context(request)
    service = _study_agent_run_service(request)
    run = _apply_run_control(
        service,
        owner_id=context.user_id,
        run_id=run_id,
        action="cancel",
    )
    _record_study_agent_run_audit(
        request,
        actor_id=context.user_id,
        request_id=context.request_id,
        action="study_agent_run.cancel_requested",
        run=run,
    )
    return run


@router.post("/runs/{run_id}/pause")
def pause_study_agent_run(request: Request, run_id: str) -> dict[str, Any]:
    context = get_user_context(request)
    service = _study_agent_run_service(request)
    run = _apply_run_control(
        service,
        owner_id=context.user_id,
        run_id=run_id,
        action="pause",
    )
    _record_study_agent_run_audit(
        request,
        actor_id=context.user_id,
        request_id=context.request_id,
        action="study_agent_run.pause_requested",
        run=run,
    )
    return run


@router.post("/runs/{run_id}/resume")
def resume_study_agent_run(request: Request, run_id: str) -> dict[str, Any]:
    context = get_user_context(request)
    service = _study_agent_run_service(request)
    run = _apply_run_control(
        service,
        owner_id=context.user_id,
        run_id=run_id,
        action="resume",
    )
    _record_study_agent_run_audit(
        request,
        actor_id=context.user_id,
        request_id=context.request_id,
        action="study_agent_run.resume_requested",
        run=run,
    )
    return run


@router.post("/runs/{run_id}/archive")
def archive_study_agent_run(request: Request, run_id: str) -> dict[str, Any]:
    context = get_user_context(request)
    service = _study_agent_run_service(request)
    run = _apply_run_control(
        service,
        owner_id=context.user_id,
        run_id=run_id,
        action="archive",
    )
    _record_study_agent_run_audit(
        request,
        actor_id=context.user_id,
        request_id=context.request_id,
        action="study_agent_run.archived",
        run=run,
    )
    return run


@router.post("/runs/{run_id}/retry")
async def retry_study_agent_run(
    run_id: str,
    payload: StudyAgentQueryRequest,
    request: Request,
) -> dict[str, Any]:
    context = get_user_context(request)
    service = _study_agent_run_service(request)
    if _study_agent_runner(request) is None:
        raise HTTPException(status_code=503, detail="Study agent is not configured")
    try:
        run = service.create_retry_run(
            owner_id=context.user_id,
            request_id=context.request_id,
            parent_run_id=run_id,
            payload=payload.model_dump(exclude_none=True),
        )
    except StudyAgentRunNotFound as exc:
        _raise_run_not_found_or_forbidden(service, run_id, cause=exc)
    except StudyAgentRunConflict as exc:
        raise HTTPException(status_code=409, detail="Invalid run transition") from exc
    _record_study_agent_run_audit(
        request,
        actor_id=context.user_id,
        request_id=context.request_id,
        action="study_agent_run.retry_requested",
        run={"id": run_id, "status": "retry_requested", "attempt": run.get("attempt")},
        extra={"child_run_id": run["id"]},
    )
    return await _execute_study_agent_run(
        request,
        payload,
        context=context,
        service=service,
        run=run,
    )


async def _execute_study_agent_query(
    request: Request,
    payload: StudyAgentQueryRequest,
    *,
    context: Any,
) -> dict[str, Any]:
    try:
        result, payload_data, latency_ms = await _run_study_agent_runner(
            request,
            payload,
            context=context,
        )
    except StudyAgentDocumentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="bad_study_request") from exc
    return _build_study_agent_response(
        request,
        context=context,
        result=result,
        payload_data=payload_data,
        latency_ms=latency_ms,
    )


async def _run_study_agent_runner(
    request: Request,
    payload: StudyAgentQueryRequest,
    *,
    context: Any,
) -> tuple[Any, dict[str, Any], int | float]:
    runner = _study_agent_runner(request)
    if runner is None:
        raise HTTPException(status_code=503, detail="Study agent is not configured")
    payload_data = payload.model_dump(exclude_none=True)
    payload_data["authenticated_user_id"] = context.user_id
    payload_data["request_id"] = context.request_id
    started_at = perf_counter()
    result = await runner.run(payload_data)
    latency_ms = getattr(result, "audit_metadata", {}).get("latency_ms")
    if latency_ms is None:
        latency_ms = round((perf_counter() - started_at) * 1000, 3)
    return result, payload_data, latency_ms


def _build_study_agent_response(
    request: Request,
    *,
    context: Any,
    result: Any,
    payload_data: dict[str, Any],
    latency_ms: int | float,
) -> dict[str, Any]:
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
    skill = safe_skill_metadata(audit_metadata.get("skill"))
    if skill is not None:
        response_payload["skill"] = skill
    expert = safe_expert_metadata(audit_metadata.get("expert"))
    if expert is not None:
        response_payload["expert"] = expert
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


async def _execute_study_agent_run(
    request: Request,
    payload: StudyAgentQueryRequest,
    *,
    context: Any,
    service: StudyAgentRunService,
    run: dict[str, Any],
) -> dict[str, Any]:
    try:
        service.mark_running(owner_id=context.user_id, run_id=run["id"])
        result, payload_data, latency_ms = await _run_study_agent_runner(
            request,
            payload,
            context=context,
        )
        response_payload = _build_study_agent_response(
            request,
            context=context,
            result=result,
            payload_data=payload_data,
            latency_ms=latency_ms,
        )
    except StudyAgentDocumentError as exc:
        error_code = _safe_exception_code(exc)
        failed = _mark_study_agent_run_failed_safely(
            request,
            context=context,
            service=service,
            run=run,
            error_code=error_code,
        )
        raise HTTPException(status_code=exc.status_code, detail=failed["error_code"]) from exc
    except ValueError as exc:
        _mark_study_agent_run_failed_safely(
            request,
            context=context,
            service=service,
            run=run,
            error_code="bad_study_request",
        )
        raise HTTPException(status_code=422, detail="bad_study_request") from exc
    except HTTPException:
        raise
    except Exception as exc:
        _mark_study_agent_run_failed_safely(
            request,
            context=context,
            service=service,
            run=run,
            error_code="run_failed",
        )
        raise HTTPException(status_code=500, detail="Study agent run failed") from exc

    terminal_status = _terminal_status_for_response(response_payload)
    completed = service.mark_terminal(
        owner_id=context.user_id,
        run_id=run["id"],
        status=terminal_status,
        result_summary=_run_result_summary(response_payload),
    )
    _record_study_agent_run_audit(
        request,
        actor_id=context.user_id,
        request_id=context.request_id,
        action="study_agent_run.completed",
        run=completed,
    )
    response_payload["run"] = completed
    return response_payload


@router.get("/skills")
def list_study_agent_skills(_request: Request) -> list[dict[str, Any]]:
    return StudySkillRegistry().list_skills()


@router.get("/skills/performance")
def get_study_agent_skill_performance(
    request: Request,
    skill_name: str | None = None,
    skill_version: str | None = None,
) -> dict[str, Any]:
    context = get_user_context(request)
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        return {"skills": []}
    return StudyAgentSkillPerformanceService(
        _non_expiring_session_factory(session_factory)
    ).summary(
        owner_id=context.user_id,
        skill_name=skill_name,
        skill_version=skill_version,
    )


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


def _study_agent_run_service(request: Request) -> StudyAgentRunService:
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        raise HTTPException(
            status_code=503,
            detail="Study agent run store is not configured",
        )
    return StudyAgentRunService(_non_expiring_session_factory(session_factory))


def _apply_run_control(
    service: StudyAgentRunService,
    *,
    owner_id: str,
    run_id: str,
    action: str,
) -> dict[str, Any]:
    try:
        if action == "cancel":
            return service.cancel(owner_id=owner_id, run_id=run_id)
        if action == "pause":
            return service.pause(owner_id=owner_id, run_id=run_id)
        if action == "resume":
            return service.resume(owner_id=owner_id, run_id=run_id)
        if action == "archive":
            return service.archive(owner_id=owner_id, run_id=run_id)
    except StudyAgentRunNotFound as exc:
        _raise_run_not_found_or_forbidden(service, run_id, cause=exc)
    except StudyAgentRunConflict as exc:
        raise HTTPException(status_code=409, detail="Invalid run transition") from exc
    raise HTTPException(status_code=409, detail="Invalid run transition")


def _raise_run_not_found_or_forbidden(
    service: StudyAgentRunService,
    run_id: str,
    *,
    cause: Exception | None = None,
) -> None:
    if service.run_exists(run_id):
        raise HTTPException(status_code=403, detail="Forbidden") from cause
    raise HTTPException(status_code=404, detail="Run not found") from cause


def _terminal_status_for_response(response_payload: dict[str, Any]) -> str:
    workflow = response_payload.get("workflow")
    verification = response_payload.get("verification")
    workflow_needs_review = isinstance(workflow, dict) and (
        workflow.get("needs_review") is True or workflow.get("status") == "needs_review"
    )
    verification_needs_review = isinstance(verification, dict) and (
        verification.get("needs_review") is True
    )
    if workflow_needs_review or verification_needs_review or response_payload.get("review_task"):
        return "needs_review"
    return "completed"


def _run_result_summary(response_payload: dict[str, Any]) -> dict[str, Any]:
    trace = response_payload.get("trace") if isinstance(response_payload.get("trace"), dict) else {}
    workflow = (
        response_payload.get("workflow")
        if isinstance(response_payload.get("workflow"), dict)
        else {}
    )
    review_task = (
        response_payload.get("review_task")
        if isinstance(response_payload.get("review_task"), dict)
        else {}
    )
    policy = response_payload.get("policy") if isinstance(response_payload.get("policy"), dict) else {}
    expert = response_payload.get("expert") if isinstance(response_payload.get("expert"), dict) else {}
    evidence = (
        response_payload.get("evidence")
        if isinstance(response_payload.get("evidence"), dict)
        else {}
    )
    draft = response_payload.get("draft") if isinstance(response_payload.get("draft"), dict) else {}
    verification = (
        response_payload.get("verification")
        if isinstance(response_payload.get("verification"), dict)
        else {}
    )

    workflow_id = workflow.get("workflow_id") or trace.get("workflow", {}).get("workflow_id")
    summary = {
        "trace_id": trace.get("trace_id"),
        "workflow_id": workflow_id,
        "review_task_id": review_task.get("id"),
        "selected_mode": (
            policy.get("selected_mode")
            or trace.get("selected_mode")
            or evidence.get("mode")
        ),
        "policy_status": policy.get("status") or "not_applied",
        "category": policy.get("category") or "unknown",
        "source_count": trace.get("source_count") or len(evidence.get("sources") or []),
        "used_chunk_count": trace.get("used_chunk_count") or draft.get("used_chunk_count"),
        "confidence": trace.get("confidence") or verification.get("confidence"),
        "source_recall": trace.get("source_recall") or verification.get("source_recall"),
        "answer_term_recall": trace.get("answer_term_recall")
        or verification.get("answer_term_recall"),
        "needs_review": _terminal_status_for_response(response_payload) == "needs_review",
        "latency_ms": trace.get("latency_ms"),
        "stage_count": workflow.get("stage_count")
        or trace.get("workflow", {}).get("stage_count"),
        "expert_enabled": expert.get("enabled"),
        "expert_branch_count": expert.get("branch_count"),
        "expert_timeout_count": expert.get("timeout_count"),
        "expert_failure_count": expert.get("failure_count"),
    }
    return {key: value for key, value in summary.items() if value is not None}


def _safe_exception_code(exc: StudyAgentDocumentError) -> str:
    if exc.code in {
        "authentication_required",
        "document_evidence_missing",
        "unsupported_study_target",
        "unsupported_retrieval_mode",
        "forbidden_document",
        "bad_study_request",
    }:
        return exc.code
    if exc.status_code == 404:
        return "forbidden_document"
    return "bad_study_request"


def _mark_study_agent_run_failed_safely(
    request: Request,
    *,
    context: Any,
    service: StudyAgentRunService,
    run: dict[str, Any],
    error_code: str,
) -> dict[str, Any]:
    failed = service.mark_terminal(
        owner_id=context.user_id,
        run_id=run["id"],
        status="failed",
        error_code=error_code,
        error_message=error_code,
    )
    _record_study_agent_run_audit(
        request,
        actor_id=context.user_id,
        request_id=context.request_id,
        action="study_agent_run.failed",
        run=failed,
        extra={"reason": failed.get("error_code") or error_code},
    )
    return failed


def _record_study_agent_run_audit(
    request: Request,
    *,
    actor_id: str,
    request_id: str,
    action: str,
    run: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> None:
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        return

    summary = run.get("result_summary") if isinstance(run.get("result_summary"), dict) else {}
    metadata = {
        "run_id": run.get("id"),
        "workflow_id": run.get("workflow_id") or summary.get("workflow_id"),
        "trace_id": run.get("trace_id") or summary.get("trace_id"),
        "status": run.get("status"),
        "selected_mode": run.get("selected_mode") or summary.get("selected_mode"),
        "policy_status": summary.get("policy_status"),
        "needs_review": summary.get("needs_review"),
        "reason": run.get("error_code") or (extra or {}).get("reason"),
        "attempt": run.get("attempt"),
    }
    if extra:
        metadata.update(extra)
    record_audit_event(
        session_factory=_non_expiring_session_factory(session_factory),
        actor_id=actor_id,
        action=action,
        resource_type="study_agent_run",
        resource_id=str(run.get("id") or "study-agent-run"),
        request_id=request_id,
        metadata={
            key: value
            for key, value in metadata.items()
            if isinstance(value, (str, int, float, bool)) or value is None
        },
    )


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
    skill = safe_skill_metadata(audit_metadata.get("skill"))
    if skill is not None:
        trace_payload["skill"] = skill
    expert = safe_expert_metadata(audit_metadata.get("expert"))
    if expert is not None:
        trace_payload["expert"] = expert
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
