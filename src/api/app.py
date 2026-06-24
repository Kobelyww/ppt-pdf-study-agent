from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from src.api.request_context import authenticate_request
from src.api.routes.audit import router as audit_router
from src.api.routes.auth import router as auth_router
from src.api.routes.documents import router as documents_router
from src.api.routes.exports import router as exports_router
from src.api.routes.feedback import router as feedback_router
from src.api.routes.jobs import router as jobs_router
from src.api.routes.review import router as review_router
from src.api.routes.study_agent import router as study_agent_router
from src.config import load_product_config
from src.db.models import Base, UserRecord
from src.db.session import create_session_factory, get_engine
from src.observability.health import HealthCheckService
from src.services.document_service import DocumentService
from src.services.export_service import ExportService
from src.services.feedback_service import FeedbackService
from src.security.auth import hash_password
from src.storage.backend import create_storage_backend
from src.workers.queue import create_job_queue


@dataclass
class InMemoryDocumentService:
    """Minimal deterministic service until storage/workers are available."""

    jobs: dict[str, dict[str, Any]] = field(default_factory=dict)

    def create_document(self, metadata: dict[str, Any]) -> dict[str, Any]:
        document_id = f"doc-{uuid4().hex}"
        job_id = f"job-{uuid4().hex}"
        job = {
            "job_id": job_id,
            "document_id": document_id,
            "status": "queued",
        }
        self.jobs[job_id] = job
        return {
            "document_id": document_id,
            "job_id": job_id,
            "status": "queued",
            "metadata": metadata,
        }

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        return self.jobs.get(job_id)

    def update_job_status(
        self,
        job_id: str,
        status: str,
        error_message: str | None = None,
        **metadata,
    ) -> None:
        job = self.jobs.setdefault(job_id, {"job_id": job_id})
        job["status"] = status
        job["error_message"] = error_message
        job.update(metadata)

    def record_job_stage(
        self,
        job_id: str,
        stage: str,
        status: str,
        error_message: str | None = None,
    ) -> None:
        job = self.jobs.setdefault(job_id, {"job_id": job_id})
        job["current_stage"] = stage
        job["stage_status"] = status
        if error_message:
            job["error_message"] = error_message


class DatabaseReadinessCheck:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    def healthcheck(self) -> bool:
        with self.session_factory() as session:
            session.execute(text("SELECT 1"))
        return True


@dataclass(frozen=True)
class ProductRuntime:
    document_service: DocumentService
    export_service: ExportService
    job_queue: Any
    session_factory: Any
    readiness_checks: dict[str, Any]


def build_product_runtime(config) -> ProductRuntime:
    engine = get_engine(config.database_url)
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    _bootstrap_first_admin(session_factory, config)
    storage = create_storage_backend(config)
    document_service = DocumentService(session_factory=session_factory, storage=storage)
    job_queue = create_job_queue(
        job_service=document_service,
        backend=config.queue_backend,
        redis_url=config.redis_url,
    )
    return ProductRuntime(
        document_service=document_service,
        export_service=ExportService(session_factory=session_factory, storage=storage),
        job_queue=job_queue,
        session_factory=session_factory,
        readiness_checks={
            "database": DatabaseReadinessCheck(session_factory),
            "queue": job_queue,
            "storage": storage,
        },
    )


def create_app(
    document_service: Any | None = None,
    job_queue: Any | None = None,
    *,
    session_factory: Any | None = None,
    export_service: Any | None = None,
    feedback_service: Any | None = None,
    study_agent_orchestrator: Any | None = None,
    study_agent_runtime_service: Any | None = None,
    secret_key: str | None = None,
    allow_dev_user_header: bool | None = None,
    cors_origins: list[str] | None = None,
    readiness_checks: dict[str, Any] | None = None,
) -> FastAPI:
    config = load_product_config()
    runtime: ProductRuntime | None = None
    if (
        config.app_env == "production"
        and document_service is None
        and job_queue is None
        and session_factory is None
    ):
        runtime = build_product_runtime(config)
        document_service = runtime.document_service
        job_queue = runtime.job_queue
        session_factory = runtime.session_factory
        export_service = runtime.export_service
        readiness_checks = runtime.readiness_checks

    app = FastAPI(title="PPT PDF Study Agent API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins if cors_origins is not None else config.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.document_service = document_service or InMemoryDocumentService()
    app.state.session_factory = session_factory or getattr(
        app.state.document_service,
        "session_factory",
        None,
    )
    app.state.secret_key = secret_key or config.secret_key
    app.state.allow_dev_user_header = (
        config.allow_dev_user_header
        if allow_dev_user_header is None
        else allow_dev_user_header
    )
    if hasattr(app.state.document_service, "session_factory") and hasattr(
        app.state.document_service,
        "storage",
    ):
        app.state.export_service = export_service or ExportService(
            session_factory=app.state.document_service.session_factory,
            storage=app.state.document_service.storage,
        )
    else:
        app.state.export_service = export_service or ExportService()
    app.state.feedback_service = feedback_service or FeedbackService()
    app.state.study_agent_orchestrator = study_agent_orchestrator
    app.state.study_agent_runtime_service = study_agent_runtime_service
    app.state.job_queue = job_queue
    app.state.readiness_checks = readiness_checks or {}

    @app.middleware("http")
    async def authenticate_product_requests(request: Request, call_next):
        if _auth_is_skipped(request.url.path):
            return await call_next(request)
        try:
            request.state.user = authenticate_request(request)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        return await call_next(request)

    app.include_router(auth_router)
    app.include_router(audit_router)
    app.include_router(documents_router, prefix="/api")
    app.include_router(exports_router)
    app.include_router(feedback_router)
    app.include_router(jobs_router, prefix="/api")
    app.include_router(review_router)
    app.include_router(study_agent_router)

    @app.get("/health")
    def health() -> dict[str, object]:
        checks = _evaluate_readiness_checks(app.state.readiness_checks)
        components = {"api": True, **checks} if checks else {"api": True}
        if not checks:
            components.update({"database": True, "queue": True})
        return HealthCheckService().check(components)

    @app.get("/ready", response_model=None)
    def ready():
        checks = _evaluate_readiness_checks(app.state.readiness_checks)
        ready_state = all(checks.values()) if checks else True
        payload = {
            "status": "ready" if ready_state else "not_ready",
            "checks": checks,
        }
        if not ready_state:
            return JSONResponse(status_code=503, content=payload)
        return payload

    return app


def _auth_is_skipped(path: str) -> bool:
    if path in {"/health", "/ready"}:
        return True
    return path.startswith("/api/auth/login")


def _evaluate_readiness_checks(checks: dict[str, Any]) -> dict[str, bool]:
    results: dict[str, bool] = {}
    for name, check in checks.items():
        try:
            if hasattr(check, "healthcheck"):
                results[name] = bool(check.healthcheck())
            elif callable(check):
                results[name] = bool(check())
            else:
                results[name] = bool(check)
        except Exception:
            results[name] = False
    return results


def _bootstrap_first_admin(session_factory, config) -> None:
    if config.app_env != "production":
        return
    email = config.bootstrap_admin_email.strip()
    password = config.bootstrap_admin_password
    if not email or not password:
        return
    with session_factory() as session:
        existing_user = session.query(UserRecord.id).first()
        if existing_user is not None:
            return
        session.add(
            UserRecord(
                id="admin-bootstrap",
                email=email,
                password_hash=hash_password(password),
                role="admin",
                is_active=True,
                display_name="Bootstrap Admin",
            )
        )
        session.commit()


app = create_app()
