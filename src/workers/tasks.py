from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import inspect
from uuid import uuid4

from src.db.models import (
    ContentVersionRecord,
    Document,
    DocumentArtifactRecord,
    ExportJobRecord,
    ProcessingJob,
)
from src.services.study_agent_index import StudyDocumentIndexService
from src.services.version_service import create_persisted_version
from src.storage.backend import StorageBackend


StageCallable = Callable[[], None]


@dataclass(frozen=True)
class DocumentProcessingTask:
    job_id: str
    document_id: str
    owner_id: str = "demo-user"
    stages: list[tuple[str, StageCallable]] = field(default_factory=list)
    task_type: str = "document_processing"
    stage_keys: list[str] = field(default_factory=list)


def run_document_processing_task(task: DocumentProcessingTask, job_service) -> None:
    if _task_job_is_completed(task, job_service):
        return
    _update_task_job_status(job_service, task, "running")
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
        _update_task_job_status(job_service, task, "failed", error_message=str(exc))
        raise

    _update_task_job_status(job_service, task, "completed")


def metadata_document_task(
    job_id: str,
    document_id: str,
    metadata: dict | None = None,
    owner_id: str = "demo-user",
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
        owner_id=owner_id,
        stages=[("metadata_validation", validate_metadata)],
        stage_keys=["metadata_validation", "parse", "extract", "outline", "questions"],
    )


def empty_document_task(
    job_id: str,
    document_id: str,
    owner_id: str = "demo-user",
) -> DocumentProcessingTask:
    return metadata_document_task(
        job_id=job_id,
        document_id=document_id,
        owner_id=owner_id,
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
        if job.status in {"completed", "succeeded"}:
            return
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

        artifact_id = f"artifact:{document_id}:normalized:{uuid4().hex}"
        with session_factory() as session:
            session.add(
                DocumentArtifactRecord(
                    id=artifact_id,
                    document_id=document_id,
                    artifact_type="normalized_document",
                    content=normalized,
                    artifact_metadata={"source": "deterministic_worker"},
                    created_at=_utc_now(),
                )
            )
            session.commit()

        StudyDocumentIndexService(session_factory=session_factory).index_artifact(
            owner_id=owner_id,
            document_id=document_id,
            artifact_id=artifact_id,
            require_ready=False,
        )

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
        if export.status in {"completed", "succeeded"}:
            return
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


def recover_stale_running_jobs(
    *,
    session_factory,
    max_age_seconds: int = 1800,
    error_message: str = "stale running job recovered by worker startup",
) -> int:
    cutoff = _utc_now() - timedelta(seconds=max_age_seconds)
    recovered = 0
    with session_factory() as session:
        jobs = (
            session.query(ProcessingJob)
            .filter(ProcessingJob.status == "running")
            .all()
        )
        for job in jobs:
            reference_time = job.updated_at or job.started_at or job.created_at
            if _as_aware_utc(reference_time) > cutoff:
                continue
            now = _utc_now()
            job.status = "failed"
            job.error_message = error_message
            job.completed_at = now
            job.updated_at = now
            document = session.get(Document, job.document_id)
            if document is not None and document.status == "processing":
                document.status = "failed"
                document.updated_at = now
            recovered += 1
        session.commit()
    return recovered


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


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

    _update_job_status_compat(
        job_service,
        job_id=job_id,
        status="failed" if status == "failed" else "running",
        error_message=error_message,
        current_stage=stage,
        stage_status=status,
    )


def _task_job_is_completed(task: DocumentProcessingTask, job_service) -> bool:
    if not hasattr(job_service, "get_job"):
        return False
    try:
        job = job_service.get_job(job_id=task.job_id, owner_id=task.owner_id)
    except TypeError:
        try:
            job = job_service.get_job(task.job_id)
        except TypeError:
            return False
    if job is None:
        return False
    status = job.get("status") if isinstance(job, dict) else getattr(job, "status", None)
    return status in {"completed", "succeeded"}


def _update_task_job_status(
    job_service,
    task: DocumentProcessingTask,
    status: str,
    error_message: str | None = None,
    **metadata,
) -> None:
    _update_job_status_compat(
        job_service,
        job_id=task.job_id,
        status=status,
        owner_id=task.owner_id,
        error_message=error_message,
        **metadata,
    )


def _update_job_status_compat(
    job_service,
    *,
    job_id: str,
    status: str,
    owner_id: str | None = None,
    error_message: str | None = None,
    **metadata,
) -> None:
    if owner_id is not None and _supports_owner_scoped_status(job_service):
        try:
            job_service.update_job_status(
                job_id=job_id,
                status=status,
                owner_id=owner_id,
                error_message=error_message,
                **metadata,
            )
            return
        except TypeError:
            pass

    try:
        job_service.update_job_status(
            job_id=job_id,
            status=status,
            error_message=error_message,
            **metadata,
        )
        return
    except TypeError:
        pass

    try:
        job_service.update_job_status(
            job_id,
            status,
            error_message=error_message,
            **metadata,
        )
    except TypeError:
        job_service.update_job_status(job_id, status, error_message=error_message)


def _supports_owner_scoped_status(job_service) -> bool:
    try:
        signature = inspect.signature(job_service.update_job_status)
    except (AttributeError, TypeError, ValueError):
        return False
    parameter = signature.parameters.get("owner_id")
    if parameter is None:
        return False
    return parameter.kind in {
        inspect.Parameter.KEYWORD_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    }
