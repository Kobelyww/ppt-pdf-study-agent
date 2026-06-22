from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

from sqlalchemy.orm import Session

from src.db.models import Document, ProcessingJob
from src.storage.backend import StorageBackend


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class DocumentUploadResult:
    document: Document
    job: ProcessingJob


class DocumentService:
    def __init__(self, session_factory: Callable[[], Session], storage: StorageBackend):
        self.session_factory = session_factory
        self.storage = storage

    def create_upload(
        self,
        *,
        owner_id: str,
        filename: str,
        content: bytes,
        content_type: str,
    ) -> DocumentUploadResult:
        stored = self.storage.put_bytes(
            namespace="uploads",
            original_filename=filename,
            content=content,
            content_type=content_type,
        )
        now = _now()
        document = Document(
            id=f"doc-{uuid4().hex}",
            owner_id=owner_id,
            title=filename,
            source_type=self._source_type(filename, content_type),
            storage_uri=stored.storage_uri,
            content_hash=stored.content_hash,
            original_filename=filename,
            status="uploaded",
            created_at=now,
            updated_at=now,
        )
        job = ProcessingJob(
            id=f"job-{uuid4().hex}",
            document=document,
            owner_id=owner_id,
            job_type="process_document",
            status="queued",
            progress=0,
            created_at=now,
            updated_at=now,
        )
        with self.session_factory() as session:
            session.add(document)
            session.add(job)
            session.commit()
            session.refresh(document)
            session.refresh(job)
            session.expunge(document)
            session.expunge(job)
        return DocumentUploadResult(document=document, job=job)

    def list_documents(self, *, owner_id: str) -> list[Document]:
        with self.session_factory() as session:
            documents = (
                session.query(Document)
                .filter(Document.owner_id == owner_id)
                .order_by(Document.created_at.asc())
                .all()
            )
            for document in documents:
                session.expunge(document)
            return documents

    def get_document(self, *, document_id: str, owner_id: str) -> Document | None:
        with self.session_factory() as session:
            document = (
                session.query(Document)
                .filter(Document.id == document_id, Document.owner_id == owner_id)
                .one_or_none()
            )
            if document is not None:
                session.expunge(document)
            return document

    def document_exists(self, *, document_id: str) -> bool:
        with self.session_factory() as session:
            return (
                session.query(Document.id)
                .filter(Document.id == document_id)
                .first()
                is not None
            )

    def get_job(self, *, job_id: str, owner_id: str) -> ProcessingJob | None:
        with self.session_factory() as session:
            job = (
                session.query(ProcessingJob)
                .filter(ProcessingJob.id == job_id, ProcessingJob.owner_id == owner_id)
                .one_or_none()
            )
            if job is not None:
                session.expunge(job)
            return job

    def job_exists(self, *, job_id: str) -> bool:
        with self.session_factory() as session:
            return (
                session.query(ProcessingJob.id)
                .filter(ProcessingJob.id == job_id)
                .first()
                is not None
            )

    def update_job_status(
        self,
        *,
        job_id: str,
        status: str,
        owner_id: str | None = None,
        error_message: str | None = None,
        progress: int | None = None,
    ) -> ProcessingJob:
        with self.session_factory() as session:
            query = session.query(ProcessingJob).filter(ProcessingJob.id == job_id)
            if owner_id is not None:
                query = query.filter(ProcessingJob.owner_id == owner_id)
            job = query.one()
            job.status = status
            job.error_message = error_message
            if progress is not None:
                job.progress = progress
            job.updated_at = _now()
            if status == "running" and job.started_at is None:
                job.started_at = job.updated_at
            if status in {"completed", "succeeded", "failed", "cancelled", "canceled"}:
                job.completed_at = job.updated_at
            session.commit()
            session.refresh(job)
            session.expunge(job)
            return job

    def retry_job(self, *, job_id: str, owner_id: str) -> ProcessingJob:
        return self.update_job_status(
            job_id=job_id,
            owner_id=owner_id,
            status="queued",
            error_message=None,
            progress=0,
        )

    @staticmethod
    def _source_type(filename: str, content_type: str) -> str:
        suffix = filename.lower().rsplit(".", maxsplit=1)[-1] if "." in filename else ""
        if suffix in {"pdf", "ppt", "pptx"}:
            return suffix
        if "pdf" in content_type:
            return "pdf"
        if "presentation" in content_type or "powerpoint" in content_type:
            return "pptx"
        return "unknown"
