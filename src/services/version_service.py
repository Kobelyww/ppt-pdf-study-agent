from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.db.models import ContentVersionRecord


@dataclass(frozen=True)
class ContentVersion:
    id: str
    target_type: str
    target_id: str
    version: int
    content: str
    created_by: str
    created_at: datetime
    change_summary: str


class ContentVersionService:
    def __init__(self) -> None:
        self._versions: dict[tuple[str, str], list[ContentVersion]] = {}

    def create_version(
        self,
        target_type: str,
        target_id: str,
        content: str,
        created_by: str,
        change_summary: str,
    ) -> ContentVersion:
        key = (target_type, target_id)
        versions = self._versions.setdefault(key, [])
        next_version = len(versions) + 1
        record = ContentVersion(
            id=f"{target_type}:{target_id}:v{next_version}",
            target_type=target_type,
            target_id=target_id,
            version=next_version,
            content=content,
            created_by=created_by,
            created_at=datetime.now(timezone.utc),
            change_summary=change_summary,
        )
        versions.append(record)
        return record

    def list_versions(self, target_type: str, target_id: str) -> list[ContentVersion]:
        return list(self._versions.get((target_type, target_id), []))


def create_persisted_version(
    *,
    session_factory: Callable[[], Session],
    document_id: str,
    target_type: str,
    target_id: str,
    content: str,
    created_by: str,
    change_summary: str,
    content_metadata: dict | None = None,
) -> ContentVersionRecord:
    with session_factory() as session:
        current_max = (
            session.query(func.max(ContentVersionRecord.version))
            .filter(
                ContentVersionRecord.target_type == target_type,
                ContentVersionRecord.target_id == target_id,
            )
            .scalar()
            or 0
        )
        record = ContentVersionRecord(
            id=f"{target_type}:{target_id}:v{current_max + 1}",
            document_id=document_id,
            target_type=target_type,
            target_id=target_id,
            version=current_max + 1,
            content=content,
            created_by=created_by,
            change_summary=change_summary,
            content_metadata=content_metadata or {},
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        session.expunge(record)
        return record
