from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from src.api.request_context import get_user_context
from src.security.audit import record_audit_event
from src.services.study_agent_documents import StudyAgentDocumentError
from src.services.study_agent_runtime import StudyAgentRuntimeService


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
    try:
        result = await runner.run(payload_data)
    except StudyAgentDocumentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _record_study_agent_audit(
        request,
        actor_id=context.user_id,
        request_id=context.request_id,
        result=result,
        payload=payload_data,
    )
    return _to_jsonable(result)


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


def _record_study_agent_audit(
    request: Request,
    *,
    actor_id: str,
    request_id: str,
    result: Any,
    payload: dict[str, Any],
) -> None:
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        return

    audit_metadata = getattr(result, "audit_metadata", {}) or {}
    metadata = {
        "mode": audit_metadata.get("mode"),
        "target": audit_metadata.get("target"),
        "needs_review": audit_metadata.get("needs_review"),
        "source_count": audit_metadata.get("source_count"),
        "chunk_count": audit_metadata.get("chunk_count"),
        "document_count": len(payload.get("document_ids") or []),
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
