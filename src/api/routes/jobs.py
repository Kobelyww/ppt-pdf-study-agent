from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.api.request_context import get_user_context
from src.api.routes.documents import ALLOWED_JOB_STATUSES
from src.security.audit import record_audit_event


class JobResponse(BaseModel):
    job_id: str
    document_id: str
    status: Literal[
        "queued",
        "running",
        "completed",
        "succeeded",
        "failed",
        "cancelled",
        "canceled",
    ]


router = APIRouter(tags=["jobs"])


def _format_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _job_payload(job: Any) -> dict[str, Any]:
    if isinstance(job, dict):
        return job
    return {
        "id": job.id,
        "job_id": job.id,
        "document_id": job.document_id,
        "owner_id": job.owner_id,
        "job_type": job.job_type,
        "status": job.status,
        "progress": job.progress,
        "error_message": job.error_message,
        "created_at": _format_datetime(job.created_at),
        "updated_at": _format_datetime(job.updated_at),
    }


@router.get("/jobs/{job_id}")
def get_job(request: Request, job_id: str) -> dict[str, Any]:
    document_service = request.app.state.document_service
    if _uses_owner_scoped_jobs(document_service):
        context = get_user_context(request)
        job = document_service.get_job(job_id=job_id, owner_id=context.user_id)
        if job is None:
            if document_service.job_exists(job_id=job_id):
                raise HTTPException(status_code=403, detail="Forbidden")
            raise HTTPException(status_code=404, detail="Job not found")
        return _job_payload(job)

    job = document_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") not in ALLOWED_JOB_STATUSES:
        raise HTTPException(
            status_code=502,
            detail="Invalid job status from document service",
        )
    return job


@router.post("/jobs/{job_id}/retry")
def retry_job(request: Request, job_id: str) -> dict[str, Any]:
    document_service = request.app.state.document_service
    if not hasattr(document_service, "retry_job"):
        raise HTTPException(status_code=404, detail="Job not found")
    context = get_user_context(request)
    job = document_service.get_job(job_id=job_id, owner_id=context.user_id)
    if job is None:
        if hasattr(document_service, "job_exists") and document_service.job_exists(job_id=job_id):
            raise HTTPException(status_code=403, detail="Forbidden")
        raise HTTPException(status_code=404, detail="Job not found")
    retried = document_service.retry_job(job_id=job_id, owner_id=context.user_id)
    if hasattr(document_service, "session_factory"):
        record_audit_event(
            session_factory=document_service.session_factory,
            actor_id=context.user_id,
            action="job.retry_requested",
            resource_type="job",
            resource_id=job_id,
            request_id=context.request_id,
            metadata={"document_id": retried.document_id},
        )
    return _job_payload(retried)


def _uses_owner_scoped_jobs(document_service: Any) -> bool:
    return hasattr(document_service, "retry_job") and hasattr(document_service, "job_exists")
