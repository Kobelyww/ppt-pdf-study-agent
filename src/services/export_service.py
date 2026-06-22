from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Callable
from uuid import uuid4

from sqlalchemy.orm import Session

from src.db.models import ExportJobRecord
from src.services.version_service import ContentVersion
from src.storage.backend import StorageBackend


class ExportFormat(str, Enum):
    MARKDOWN = "markdown"
    LATEX = "latex"
    PDF = "pdf"
    JSON = "json"


@dataclass(frozen=True)
class ExportJob:
    id: str
    document_id: str
    version_id: str
    format: ExportFormat
    status: str
    storage_uri: str | None = None
    error_message: str | None = None


class ExportService:
    def __init__(
        self,
        session_factory: Callable[[], Session] | None = None,
        storage: StorageBackend | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.storage = storage

    def create_export(
        self,
        document_id: str,
        version: ContentVersion,
        export_format: ExportFormat,
    ) -> ExportJob:
        return ExportJob(
            id=f"export:{document_id}:{version.id}:{export_format.value}",
            document_id=document_id,
            version_id=version.id,
            format=export_format,
            status="queued",
        )

    def create_export_job(
        self,
        *,
        owner_id: str,
        document_id: str,
        version_id: str,
        export_format: ExportFormat,
    ) -> ExportJobRecord:
        if self.session_factory is None:
            raise RuntimeError("session_factory is required for persisted export jobs")
        record = ExportJobRecord(
            id=f"export-{uuid4().hex}",
            document_id=document_id,
            owner_id=owner_id,
            version_id=version_id,
            format=export_format.value,
            status="queued",
            created_at=datetime.now(timezone.utc),
        )
        with self.session_factory() as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            session.expunge(record)
            return record

    def get_export_job(
        self,
        *,
        owner_id: str,
        export_job_id: str,
    ) -> ExportJobRecord | None:
        if self.session_factory is None:
            return None
        with self.session_factory() as session:
            record = (
                session.query(ExportJobRecord)
                .filter(
                    ExportJobRecord.id == export_job_id,
                    ExportJobRecord.owner_id == owner_id,
                )
                .one_or_none()
            )
            if record is not None:
                session.expunge(record)
            return record

    def export_job_exists(self, *, export_job_id: str) -> bool:
        if self.session_factory is None:
            return False
        with self.session_factory() as session:
            return (
                session.query(ExportJobRecord.id)
                .filter(ExportJobRecord.id == export_job_id)
                .first()
                is not None
            )

    def render_export_content(self, content: str, export_format: ExportFormat) -> bytes:
        if export_format in {
            ExportFormat.MARKDOWN,
            ExportFormat.JSON,
            ExportFormat.LATEX,
            ExportFormat.PDF,
        }:
            return content.encode("utf-8")
        raise ValueError(f"unsupported export format: {export_format}")
