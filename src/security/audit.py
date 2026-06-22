from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
from typing import Any
from uuid import uuid4

from src.db.models import AuditEventRecord


SENSITIVE_KEYS = {"api_key", "authorization", "token", "secret", "content", "password"}
SENSITIVE_TOKENS = {
    "apikey",
    "authorization",
    "token",
    "secret",
    "content",
    "password",
}


@dataclass(frozen=True)
class AuditEvent:
    actor_id: str
    action: str
    resource_type: str
    resource_id: str
    request_id: str
    created_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


class AuditLogger:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def record(
        self,
        actor_id: str,
        action: str,
        resource_type: str,
        resource_id: str,
        request_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> AuditEvent:
        clean_metadata = self._sanitize_metadata(metadata or {}) or {}
        event = AuditEvent(
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            request_id=request_id,
            created_at=datetime.now(timezone.utc),
            metadata=clean_metadata,
        )
        self.events.append(event)
        return event

    def _sanitize_metadata(self, value: Any) -> Any:
        if isinstance(value, dict):
            clean: dict[str, Any] = {}
            for key, item in value.items():
                if self._is_sensitive_key(str(key)):
                    continue
                sanitized = self._sanitize_metadata(item)
                if sanitized is not None:
                    clean[key] = sanitized
            return clean or None

        if isinstance(value, list):
            clean_items = []
            for item in value:
                sanitized = self._sanitize_metadata(item)
                if sanitized is not None:
                    clean_items.append(sanitized)
            return clean_items or None

        return value

    def _is_sensitive_key(self, key: str) -> bool:
        normalized = re.sub(r"[^a-z0-9]", "", key.lower())
        return any(token in normalized for token in SENSITIVE_TOKENS)


def record_audit_event(
    *,
    session_factory,
    actor_id: str,
    action: str,
    resource_type: str,
    resource_id: str,
    request_id: str,
    metadata: dict | None = None,
) -> AuditEventRecord:
    clean_metadata = AuditLogger()._sanitize_metadata(metadata or {}) or {}
    record = AuditEventRecord(
        id=f"audit-{uuid4().hex}",
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        request_id=request_id,
        event_metadata=clean_metadata,
        created_at=datetime.now(timezone.utc),
    )
    with session_factory() as session:
        session.add(record)
        session.commit()
        session.refresh(record)
        session.expunge(record)
        return record
