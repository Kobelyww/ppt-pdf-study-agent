from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from src.api.request_context import get_user_context
from src.services.rag_evaluation import RAGQualityEvaluationService


router = APIRouter(prefix="/api/admin", tags=["admin"])


def _require_admin(request: Request) -> None:
    context = get_user_context(request)
    if context.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")


@router.post("/rag-evaluations")
def create_rag_evaluation(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    _require_admin(request)
    context = get_user_context(request)
    session_factory = getattr(request.app.state, "session_factory", None)
    fixture_path = Path("tests/fixtures/rag_eval_set.json")
    modes = payload.get("modes") or ["simple_rag", "graph_rag_lite", "agentic_rag"]
    service = RAGQualityEvaluationService(
        report_dir=payload.get("report_dir") or "docs/evaluation",
        session_factory=session_factory,
    )
    run = service.run_fixture_file(
        fixture_path,
        modes=list(modes),
        created_by=context.user_id,
    )
    return {
        "id": run.id,
        "fixture_version": run.fixture_version,
        "modes": run.modes,
        "case_count": run.case_count,
        "summary": run.summary,
        "readiness": run.readiness,
        "report_uri": str(run.report_markdown_path),
    }
