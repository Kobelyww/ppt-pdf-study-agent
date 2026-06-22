from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from src.db.models import (
    ContentVersionRecord,
    Document,
    DocumentArtifactRecord,
    ExportJobRecord,
    ProcessingJob,
)
from src.services.version_service import create_persisted_version
from src.storage.backend import StorageBackend


StageCallable = Callable[[], None]


@dataclass(frozen=True)
class DocumentProcessingTask:
    job_id: str
    document_id: str
    stages: list[tuple[str, StageCallable]] = field(default_factory=list)
    task_type: str = "document_processing"
    stage_keys: list[str] = field(default_factory=list)


def run_document_processing_task(task: DocumentProcessingTask, job_service) -> None:
    job_service.update_job_status(task.job_id, "running")
    current_stage: str | None = None
    try:
        for stage_name, stage in _validated_stages(task):
            current_stage = stage_name
            _record_stage(job_service, task.job_id, current_stage, "running")
            stage()
            _record_stage(job_service, task.job_id, current_stage, "completed")
    except Exception as exc:
        if current_stage is not None:
            _record_stage(job_service, task.job_id, current_stage, "failed", error_message=str(exc))
        job_service.update_job_status(task.job_id, "failed", error_message=str(exc))
        raise

    job_service.update_job_status(task.job_id, "completed")


def metadata_document_task(
    job_id: str,
    document_id: str,
    metadata: dict | None = None,
) -> DocumentProcessingTask:
    metadata = metadata or {}

    def validate_metadata() -> None:
        if not metadata.get("title"):
            raise ValueError("document metadata must include title")
        if not metadata.get("source_type"):
            raise ValueError("document metadata must include source_type")

    return DocumentProcessingTask(
        job_id=job_id,
        document_id=document_id,
        stages=[("metadata_validation", validate_metadata)],
        stage_keys=["metadata_validation", "parse", "extract", "outline", "questions"],
    )


def empty_document_task(job_id: str, document_id: str) -> DocumentProcessingTask:
    return metadata_document_task(
        job_id=job_id,
        document_id=document_id,
        metadata={"title": "Untitled document", "source_type": "unknown"},
    )


def run_product_document_task(
    *,
    job_id: str,
    document_id: str,
    owner_id: str,
    session_factory,
    storage: StorageBackend,
) -> None:
    with session_factory() as session:
        document = session.get(Document, document_id)
        if document is None or document.owner_id != owner_id:
            raise ValueError("document not found")
        job = session.get(ProcessingJob, job_id)
        if job is None or job.document_id != document_id or job.owner_id != owner_id:
            raise ValueError("job not found")
        source_uri = document.storage_uri
        job.status = "running"
        job.progress = 10
        job.started_at = _utc_now()
        job.updated_at = job.started_at
        document.status = "processing"
        document.updated_at = job.started_at
        session.commit()

    try:
        source_text = storage.read_bytes(source_uri).decode("utf-8", errors="ignore")
        normalized = _normalize_source_text(source_text)
        outline = _build_outline(normalized)
        questions = _build_questions(normalized)

        with session_factory() as session:
            session.add(
                DocumentArtifactRecord(
                    id=f"artifact:{document_id}:normalized:{uuid4().hex}",
                    document_id=document_id,
                    artifact_type="normalized_document",
                    content=normalized,
                    artifact_metadata={"source": "deterministic_worker"},
                    created_at=_utc_now(),
                )
            )
            session.commit()

        create_persisted_version(
            session_factory=session_factory,
            document_id=document_id,
            target_type="outline",
            target_id=document_id,
            content=outline,
            created_by="worker",
            change_summary="generated outline",
            content_metadata={"generator": "deterministic_worker"},
        )
        create_persisted_version(
            session_factory=session_factory,
            document_id=document_id,
            target_type="question_set",
            target_id=document_id,
            content=questions,
            created_by="worker",
            change_summary="generated question set",
            content_metadata={"generator": "deterministic_worker"},
        )

        with session_factory() as session:
            document = session.get(Document, document_id)
            job = session.get(ProcessingJob, job_id)
            completed_at = _utc_now()
            if document is not None:
                document.status = "ready"
                document.updated_at = completed_at
            if job is not None:
                job.status = "completed"
                job.progress = 100
                job.completed_at = completed_at
                job.updated_at = completed_at
            session.commit()
    except Exception as exc:
        with session_factory() as session:
            document = session.get(Document, document_id)
            failed_at = _utc_now()
            if document is not None:
                document.status = "failed"
                document.updated_at = failed_at
            job = session.get(ProcessingJob, job_id)
            if job is not None:
                job.status = "failed"
                job.error_message = str(exc)
                job.updated_at = failed_at
                job.completed_at = failed_at
            session.commit()
        raise


def run_export_task(
    *,
    export_job_id: str,
    owner_id: str,
    session_factory,
    storage: StorageBackend,
) -> None:
    with session_factory() as session:
        export = session.get(ExportJobRecord, export_job_id)
        if export is None or export.owner_id != owner_id:
            raise ValueError("export job not found")
        version = session.get(ContentVersionRecord, export.version_id)
        if version is None:
            raise ValueError("content version not found")
        export.status = "running"
        session.commit()
        content = version.content
        export_format = export.format

    try:
        suffix = "json" if export_format == "json" else "md"
        content_type = "application/json" if export_format == "json" else "text/markdown"
        stored = storage.put_bytes(
            namespace="exports",
            original_filename=f"{export_job_id}.{suffix}",
            content=content.encode("utf-8"),
            content_type=content_type,
        )
        with session_factory() as session:
            export = session.get(ExportJobRecord, export_job_id)
            if export is not None:
                export.status = "completed"
                export.storage_uri = stored.storage_uri
                export.completed_at = _utc_now()
            session.commit()
    except Exception as exc:
        with session_factory() as session:
            export = session.get(ExportJobRecord, export_job_id)
            if export is not None:
                export.status = "failed"
                export.error_message = str(exc)
                export.completed_at = _utc_now()
            session.commit()
        raise


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_source_text(source_text: str) -> str:
    text = " ".join(source_text.split())
    return text or "No readable content extracted."


def _build_outline(normalized: str) -> str:
    title = normalized.split(".")[0][:80] or "Study Notes"
    return f"# {title}\n\n## Key Ideas\n- {normalized}"


def _build_questions(normalized: str) -> str:
    return (
        "# Question Set\n\n"
        "1. What is the central idea of this document?\n\n"
        f"Answer: {normalized[:240]}"
    )


def _validated_stages(task: DocumentProcessingTask) -> list[tuple[str, StageCallable]]:
    validated = []
    for stage_entry in task.stages:
        if len(stage_entry) != 2:
            raise ValueError("stage must be a (name, callable) pair")

        stage_name, stage = stage_entry
        if not isinstance(stage_name, str) or not callable(stage):
            raise ValueError("stage must be a (name, callable) pair")

        validated.append((stage_name, stage))
    return validated


def _record_stage(
    job_service,
    job_id: str,
    stage: str,
    status: str,
    error_message: str | None = None,
) -> None:
    if hasattr(job_service, "record_job_stage"):
        job_service.record_job_stage(job_id, stage, status, error_message=error_message)
        return

    job_service.update_job_status(
        job_id,
        "failed" if status == "failed" else "running",
        error_message=error_message,
        current_stage=stage,
        stage_status=status,
    )
