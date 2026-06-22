from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.api.request_context import get_user_context
from src.security.audit import record_audit_event
from src.services.export_service import ExportFormat, ExportService
from src.services.version_service import ContentVersion


class ExportRequest(BaseModel):
    version_id: str
    format: ExportFormat
    content: str = ""


router = APIRouter(prefix="/api/exports", tags=["exports"])


@router.post("/{document_id}")
def create_export(
    request: Request,
    document_id: str,
    export_request: ExportRequest,
) -> dict[str, Any]:
    document_service = request.app.state.document_service
    export_service = request.app.state.export_service
    context = get_user_context(request)

    if hasattr(document_service, "get_document"):
        document = document_service.get_document(
            document_id=document_id,
            owner_id=context.user_id,
        )
        if document is None:
            if hasattr(document_service, "document_exists") and document_service.document_exists(
                document_id=document_id,
            ):
                raise HTTPException(status_code=403, detail="Forbidden")
            raise HTTPException(status_code=404, detail="Document not found")

    if hasattr(export_service, "create_export_job") and export_service.session_factory is not None:
        job = export_service.create_export_job(
            owner_id=context.user_id,
            document_id=document_id,
            version_id=export_request.version_id,
            export_format=export_request.format,
        )
        record_audit_event(
            session_factory=export_service.session_factory,
            actor_id=context.user_id,
            action="export.created",
            resource_type="export",
            resource_id=job.id,
            request_id=context.request_id,
            metadata={
                "document_id": document_id,
                "version_id": export_request.version_id,
                "format": export_request.format.value,
            },
        )
        return _export_payload(job)

    version = ContentVersion(
        id=export_request.version_id,
        target_type="outline",
        target_id=document_id,
        version=1,
        content=export_request.content,
        created_by="api",
        created_at=datetime.now(timezone.utc),
        change_summary="export request",
    )
    job = ExportService().create_export(
        document_id=document_id,
        version=version,
        export_format=export_request.format,
    )
    return {
        "id": job.id,
        "format": job.format.value,
        "status": job.status,
    }


@router.get("/{export_id}")
def get_export(request: Request, export_id: str) -> dict[str, Any]:
    export_service = request.app.state.export_service
    context = get_user_context(request)
    if not hasattr(export_service, "get_export_job"):
        raise HTTPException(status_code=404, detail="Export job not found")

    job = export_service.get_export_job(owner_id=context.user_id, export_job_id=export_id)
    if job is None:
        if hasattr(export_service, "export_job_exists") and export_service.export_job_exists(
            export_job_id=export_id
        ):
            raise HTTPException(status_code=403, detail="Forbidden")
        raise HTTPException(status_code=404, detail="Export job not found")
    return _export_payload(job)


def _export_payload(job: Any) -> dict[str, Any]:
    return {
        "id": job.id,
        "document_id": job.document_id,
        "version_id": job.version_id,
        "format": job.format,
        "status": job.status,
        "storage_uri": job.storage_uri,
        "error_message": job.error_message,
    }
