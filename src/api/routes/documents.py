from datetime import datetime
import json
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import ValidationError
from starlette.requests import ClientDisconnect
from pydantic import BaseModel, Field

from src.api.request_context import get_user_context
from src.db.models import ContentVersionRecord
from src.security.audit import record_audit_event
from src.workers.tasks import metadata_document_task


ALLOWED_JOB_STATUSES = {
    "queued",
    "running",
    "completed",
    "succeeded",
    "failed",
    "cancelled",
    "canceled",
}


class DocumentMetadata(BaseModel):
    title: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    storage_uri: str | None = None


class DocumentCreateResponse(BaseModel):
    document_id: str
    job_id: str
    status: Literal[
        "queued",
        "running",
        "completed",
        "succeeded",
        "failed",
        "cancelled",
        "canceled",
    ]
    metadata: dict[str, Any]


router = APIRouter(tags=["documents"])


def _document_payload(document) -> dict[str, Any]:
    return {
        "id": document.id,
        "owner_id": document.owner_id,
        "title": document.title,
        "source_type": document.source_type,
        "storage_uri": document.storage_uri,
        "content_hash": document.content_hash,
        "original_filename": document.original_filename,
        "status": document.status,
        "created_at": _format_datetime(document.created_at),
        "updated_at": _format_datetime(document.updated_at),
    }


def _job_payload(job) -> dict[str, Any]:
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


def _format_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


@router.post(
    "/documents",
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_document(
    request: Request,
) -> dict[str, Any]:
    document_service = request.app.state.document_service
    content_type = request.headers.get("content-type", "").lower()
    if content_type.startswith("multipart/form-data") and hasattr(
        document_service, "create_upload"
    ):
        form = await request.form()
        file = form.get("file")
        if file is None or not hasattr(file, "read"):
            raise HTTPException(status_code=422, detail="Upload file is required")
        context = get_user_context(request)
        content = await file.read()
        upload = document_service.create_upload(
            owner_id=context.user_id,
            filename=file.filename or "upload.bin",
            content=content,
            content_type=file.content_type or "application/octet-stream",
        )
        _record_api_audit(
            request,
            actor_id=context.user_id,
            request_id=context.request_id,
            action="document.uploaded",
            resource_type="document",
            resource_id=upload.document.id,
            metadata={
                "filename": upload.document.original_filename,
                "content_type": upload.document.source_type,
                "size_bytes": len(content),
            },
        )
        job_queue = getattr(request.app.state, "job_queue", None)
        if job_queue is not None:
            try:
                job_queue.enqueue(
                    metadata_document_task(
                        job_id=upload.job.id,
                        document_id=upload.document.id,
                        metadata={
                            "title": upload.document.title,
                            "source_type": upload.document.source_type,
                        },
                    )
                )
            except Exception as exc:
                _mark_job_failed(
                    document_service,
                    job_id=upload.job.id,
                    error_message=str(exc),
                    owner_id=context.user_id,
                )
                raise HTTPException(
                    status_code=503,
                    detail="Failed to enqueue document processing job",
                ) from exc
        return {
            "document_id": upload.document.id,
            "job_id": upload.job.id,
            "status": upload.job.status,
            "document": _document_payload(upload.document),
            "job": _job_payload(upload.job),
        }

    try:
        metadata = DocumentMetadata.model_validate(await request.json())
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    except (json.JSONDecodeError, UnicodeDecodeError, ClientDisconnect) as exc:
        raise HTTPException(
            status_code=422,
            detail="Document metadata or file is required",
        ) from exc

    metadata_payload = metadata.model_dump(exclude_none=True)
    result = document_service.create_document(metadata_payload)
    if result.get("status") not in ALLOWED_JOB_STATUSES:
        raise HTTPException(
            status_code=502,
            detail="Invalid job status from document service",
        )
    job_queue = getattr(request.app.state, "job_queue", None)
    if job_queue is not None:
        try:
            job_queue.enqueue(
                metadata_document_task(
                    job_id=result["job_id"],
                    document_id=result["document_id"],
                    metadata=metadata_payload,
                )
            )
        except Exception as exc:
            if hasattr(document_service, "update_job_status"):
                _mark_job_failed(
                    document_service,
                    job_id=result["job_id"],
                    error_message=str(exc),
                )
            raise HTTPException(
                status_code=503,
                detail="Failed to enqueue document processing job",
            ) from exc
    return result


def _mark_job_failed(
    document_service: Any,
    *,
    job_id: str,
    error_message: str,
    owner_id: str | None = None,
) -> None:
    try:
        document_service.update_job_status(
            job_id=job_id,
            status="failed",
            owner_id=owner_id,
            error_message=error_message,
        )
    except TypeError:
        document_service.update_job_status(
            job_id,
            "failed",
            error_message=error_message,
        )


def _record_api_audit(
    request: Request,
    *,
    actor_id: str,
    request_id: str,
    action: str,
    resource_type: str,
    resource_id: str,
    metadata: dict | None = None,
) -> None:
    document_service = request.app.state.document_service
    if hasattr(document_service, "session_factory"):
        record_audit_event(
            session_factory=document_service.session_factory,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            request_id=request_id,
            metadata=metadata,
        )


@router.get("/documents")
def list_documents(request: Request) -> list[dict[str, Any]]:
    document_service = request.app.state.document_service
    if not hasattr(document_service, "list_documents"):
        return []
    context = get_user_context(request)
    return [
        _document_payload(document)
        for document in document_service.list_documents(owner_id=context.user_id)
    ]


@router.get("/documents/{document_id}")
def get_document(request: Request, document_id: str) -> dict[str, Any]:
    document_service = request.app.state.document_service
    if not hasattr(document_service, "get_document"):
        raise HTTPException(status_code=404, detail="Document not found")
    context = get_user_context(request)
    document = document_service.get_document(document_id=document_id, owner_id=context.user_id)
    if document is None:
        if hasattr(document_service, "document_exists") and document_service.document_exists(
            document_id=document_id
        ):
            raise HTTPException(status_code=403, detail="Forbidden")
        raise HTTPException(status_code=404, detail="Document not found")
    return _document_payload(document)


@router.get("/documents/{document_id}/versions")
def list_document_versions(request: Request, document_id: str) -> list[dict[str, Any]]:
    _require_owned_document(request, document_id)
    session_factory = request.app.state.document_service.session_factory
    with session_factory() as session:
        versions = (
            session.query(ContentVersionRecord)
            .filter(ContentVersionRecord.document_id == document_id)
            .order_by(ContentVersionRecord.created_at.asc(), ContentVersionRecord.version.asc())
            .all()
        )
        return [_version_payload(version) for version in versions]


@router.get("/documents/{document_id}/outline")
def get_latest_outline(request: Request, document_id: str) -> dict[str, Any]:
    return _latest_version_payload(request, document_id, "outline")


@router.get("/documents/{document_id}/questions")
def get_latest_questions(request: Request, document_id: str) -> dict[str, Any]:
    return _latest_version_payload(request, document_id, "question_set")


def _latest_version_payload(
    request: Request,
    document_id: str,
    target_type: str,
) -> dict[str, Any]:
    _require_owned_document(request, document_id)
    session_factory = request.app.state.document_service.session_factory
    with session_factory() as session:
        version = (
            session.query(ContentVersionRecord)
            .filter(
                ContentVersionRecord.document_id == document_id,
                ContentVersionRecord.target_type == target_type,
            )
            .order_by(ContentVersionRecord.version.desc())
            .first()
        )
        if version is None:
            raise HTTPException(status_code=404, detail="Content version not found")
        return _version_payload(version)


def _require_owned_document(request: Request, document_id: str):
    document_service = request.app.state.document_service
    if not hasattr(document_service, "get_document"):
        raise HTTPException(status_code=404, detail="Document not found")
    context = get_user_context(request)
    document = document_service.get_document(document_id=document_id, owner_id=context.user_id)
    if document is None:
        if hasattr(document_service, "document_exists") and document_service.document_exists(
            document_id=document_id
        ):
            raise HTTPException(status_code=403, detail="Forbidden")
        raise HTTPException(status_code=404, detail="Document not found")
    return document


def _version_payload(version: ContentVersionRecord) -> dict[str, Any]:
    return {
        "id": version.id,
        "document_id": version.document_id,
        "target_type": version.target_type,
        "target_id": version.target_id,
        "version": version.version,
        "content": version.content,
        "created_by": version.created_by,
        "created_at": _format_datetime(version.created_at),
        "change_summary": version.change_summary,
        "content_metadata": version.content_metadata,
    }
