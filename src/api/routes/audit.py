from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from src.api.request_context import get_user_context
from src.db.models import AuditEventRecord


router = APIRouter(prefix="/api/audit-events", tags=["audit"])


@router.get("")
def list_audit_events(
    request: Request,
    actor_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    action: str | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, Any]]:
    context = get_user_context(request)
    if context.role != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")
    session_factory = request.app.state.session_factory
    with session_factory() as session:
        query = session.query(AuditEventRecord).order_by(AuditEventRecord.created_at.desc())
        if actor_id is not None:
            query = query.filter(AuditEventRecord.actor_id == actor_id)
        if resource_type is not None:
            query = query.filter(AuditEventRecord.resource_type == resource_type)
        if resource_id is not None:
            query = query.filter(AuditEventRecord.resource_id == resource_id)
        if action is not None:
            query = query.filter(AuditEventRecord.action == action)
        if created_after is not None:
            query = query.filter(AuditEventRecord.created_at >= _parse_datetime(created_after))
        if created_before is not None:
            query = query.filter(AuditEventRecord.created_at <= _parse_datetime(created_before))
        return [
            {
                "id": record.id,
                "actor_id": record.actor_id,
                "action": record.action,
                "resource_type": record.resource_type,
                "resource_id": record.resource_id,
                "request_id": record.request_id,
                "metadata": record.event_metadata,
                "created_at": record.created_at.isoformat() if record.created_at else None,
            }
            for record in query.limit(limit).all()
        ]


def _parse_datetime(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid datetime: {value}") from exc
