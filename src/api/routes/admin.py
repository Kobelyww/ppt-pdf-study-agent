from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from src.api.request_context import get_user_context
from src.db.models import RAGEvaluationRunRecord
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
    storage = _configured_storage(request)
    fixture_path = Path("tests/fixtures/rag_eval_set.json")
    modes = payload.get("modes") or ["simple_rag", "graph_rag_lite", "agentic_rag"]
    service = RAGQualityEvaluationService(
        report_dir=payload.get("report_dir") or "docs/evaluation",
        session_factory=session_factory,
        storage=storage,
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
        "report_uri": run.report_markdown_uri or str(run.report_markdown_path),
    }


@router.get("/rag-evaluations/{run_id}")
def get_rag_evaluation(request: Request, run_id: str) -> dict[str, Any]:
    _require_admin(request)
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        raise HTTPException(status_code=503, detail="RAG evaluation storage is not configured")

    with session_factory() as session:
        record = session.get(RAGEvaluationRunRecord, run_id)
        if record is None:
            raise HTTPException(status_code=404, detail="RAG evaluation run not found")
        return {
            "id": record.id,
            "created_by": record.created_by,
            "fixture_version": record.fixture_version,
            "modes": record.modes,
            "case_count": record.case_count,
            "status": record.status,
            "summary": record.summary,
            "readiness": {},
            "report_uri": record.report_uri,
            "created_at": record.created_at.isoformat(),
            "completed_at": (
                record.completed_at.isoformat() if record.completed_at else None
            ),
        }


def _configured_storage(request: Request):
    document_service = getattr(request.app.state, "document_service", None)
    storage = getattr(document_service, "storage", None)
    if storage is not None:
        return storage

    export_service = getattr(request.app.state, "export_service", None)
    return getattr(export_service, "storage", None)
