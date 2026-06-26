from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from src.api.request_context import get_user_context
from src.db.models import RAGEvaluationRunRecord
from src.services.rag_evaluation import RAGQualityEvaluationService
from src.services.rag_route_policy import (
    RAGReadinessSnapshot,
    RAGRoutePolicyConfig,
    RAGRoutePolicyService,
)
from src.services.rag_router import RAGStrategyRouter, RetrievalMode


router = APIRouter(prefix="/api/admin", tags=["admin"])
_READINESS_MODES = {"simple_rag", "graph_rag_lite", "agentic_rag"}
_READINESS_CATEGORIES = {
    "direct_lookup",
    "definition",
    "concept_relation",
    "learning_path",
    "multi_document_synthesis",
    "question_generation",
    "outline_fragment",
    "unknown",
}
_READINESS_STATUSES = {"baseline", "candidate", "hold", "blocked"}


def _require_admin(request: Request) -> None:
    context = get_user_context(request)
    if context.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")


def _route_policy_config(request: Request) -> RAGRoutePolicyConfig:
    return getattr(request.app.state, "rag_route_policy_config", RAGRoutePolicyConfig())


def _readiness_snapshot(request: Request) -> RAGReadinessSnapshot | None:
    provider = getattr(request.app.state, "rag_readiness_provider", None)
    return provider() if provider is not None else None


@router.get("/rag-route-policy")
def get_rag_route_policy(request: Request) -> dict[str, Any]:
    _require_admin(request)
    config = _route_policy_config(request)
    return {
        "policy_version": config.policy_version,
        "advanced_routing_enabled": config.advanced_routing_enabled,
        "graph_rag_enabled": config.graph_rag_enabled,
        "agentic_rag_enabled": config.agentic_rag_enabled,
        "enabled_categories": (
            sorted(config.enabled_categories)
            if config.enabled_categories is not None
            else None
        ),
        "graph_candidate_required": config.graph_candidate_required,
        "agentic_candidate_required": config.agentic_candidate_required,
        "allow_user_preferred_mode": config.allow_user_preferred_mode,
        "max_budget_for_agentic": config.max_budget_for_agentic,
        "require_persisted_chunks_for_advanced": (
            config.require_persisted_chunks_for_advanced
        ),
        "fallback_to_simple_on_block": config.fallback_to_simple_on_block,
    }


@router.get("/rag-route-readiness")
def get_rag_route_readiness(request: Request) -> dict[str, Any]:
    _require_admin(request)
    snapshot = _readiness_snapshot(request)
    if snapshot is None:
        return {"available": False, "modes": {}}
    return {
        "available": True,
        "policy_version": snapshot.policy_version,
        "fixture_version": snapshot.fixture_version,
        "created_at": snapshot.created_at,
        "modes": _safe_readiness_modes(snapshot.modes),
    }


@router.post("/rag-route-policy/simulate")
def simulate_rag_route_policy(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    _require_admin(request)
    query = str(payload.get("query", "")).strip()
    if not query:
        raise HTTPException(status_code=422, detail="query is required")

    router_decision = RAGStrategyRouter().route(query, target=payload.get("target"))
    preferred_mode = _preferred_mode(payload.get("preferred_mode"))
    policy_decision = RAGRoutePolicyService(_route_policy_config(request)).decide(
        router_decision=router_decision,
        readiness=_readiness_snapshot(request),
        index_statuses=_safe_index_statuses(payload.get("index_statuses") or {}),
        budget=str(payload.get("budget") or "balanced"),
        preferred_mode=preferred_mode,
    )
    return policy_decision.to_safe_dict()


def _preferred_mode(value: Any) -> RetrievalMode | None:
    if value in {mode.value for mode in RetrievalMode}:
        return RetrievalMode(value)
    return None


def _safe_readiness_modes(modes: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    safe_modes: dict[str, dict[str, Any]] = {}
    for mode, payload in modes.items():
        if mode not in _READINESS_MODES or not isinstance(payload, dict):
            continue
        safe_payload: dict[str, Any] = {}
        overall = payload.get("overall")
        if overall in _READINESS_STATUSES:
            safe_payload["overall"] = overall
        by_category = payload.get("by_category")
        if isinstance(by_category, dict):
            safe_categories = {
                category: status
                for category, status in by_category.items()
                if category in _READINESS_CATEGORIES and status in _READINESS_STATUSES
            }
            safe_payload["by_category"] = safe_categories
        if safe_payload:
            safe_modes[mode] = safe_payload
    return safe_modes


def _safe_index_statuses(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        raise HTTPException(
            status_code=422,
            detail="index_statuses must map document ids to objects",
        )
    safe_statuses: dict[str, dict[str, Any]] = {}
    for document_id, payload in value.items():
        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=422,
                detail="index_statuses must map document ids to objects",
            )
        safe_statuses[str(document_id)] = payload
    return safe_statuses


@router.post("/rag-evaluations")
def create_rag_evaluation(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    _require_admin(request)
    context = get_user_context(request)
    session_factory = getattr(request.app.state, "session_factory", None)
    storage = _configured_storage(request)
    fixture_path = Path("tests/fixtures/rag_eval_set.json")
    modes = payload.get("modes") or ["simple_rag", "graph_rag_lite", "agentic_rag"]
    service = RAGQualityEvaluationService(
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
