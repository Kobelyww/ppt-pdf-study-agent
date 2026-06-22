from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from fastapi import FastAPI

from src.api.routes.documents import router as documents_router
from src.api.routes.exports import router as exports_router
from src.api.routes.feedback import router as feedback_router
from src.api.routes.jobs import router as jobs_router
from src.api.routes.review import router as review_router
from src.observability.health import HealthCheckService
from src.services.export_service import ExportService
from src.services.feedback_service import FeedbackService


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


def create_app(document_service: Any | None = None, job_queue: Any | None = None) -> FastAPI:
    app = FastAPI(title="PPT PDF Study Agent API")
    app.state.document_service = document_service or InMemoryDocumentService()
    if hasattr(app.state.document_service, "session_factory") and hasattr(
        app.state.document_service,
        "storage",
    ):
        app.state.export_service = ExportService(
            session_factory=app.state.document_service.session_factory,
            storage=app.state.document_service.storage,
        )
    else:
        app.state.export_service = ExportService()
    app.state.feedback_service = FeedbackService()
    app.state.job_queue = job_queue
    app.include_router(documents_router, prefix="/api")
    app.include_router(exports_router)
    app.include_router(feedback_router)
    app.include_router(jobs_router, prefix="/api")
    app.include_router(review_router)

    @app.get("/health")
    def health() -> dict[str, object]:
        return HealthCheckService().check(
            {
                "api": True,
                "database": True,
                "queue": True,
            }
        )

    return app


app = create_app()
