from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from src.api.request_context import get_user_context


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
    get_user_context(request)
    orchestrator = getattr(request.app.state, "study_agent_orchestrator", None)
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Study agent is not configured")
    try:
        result = await orchestrator.run(payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _to_jsonable(result)


def _to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {key: _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    return value
