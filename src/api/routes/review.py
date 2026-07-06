from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.api.request_context import get_user_context
from src.db.models import ReviewTaskRecord, utc_now
from src.security.audit import record_audit_event
from src.security.permissions import Actor, can_view_review_task
from src.services.study_agent_memory import SAFE_REVIEW_REASONS, StudyAgentMemoryService
from src.services.study_agent_review_tasks import sanitize_review_task_metadata


router = APIRouter(prefix="/api/review-tasks", tags=["review"])


class ReviewDecisionRequest(BaseModel):
    decision: str
    comment: str = ""


@router.get("")
def list_review_tasks(request: Request) -> list[Any]:
    context = get_user_context(request)
    session_factory = _audit_session_factory(request)
    if session_factory is not None:
        actor = Actor(id=context.user_id, role=context.role)
        with session_factory() as session:
            records = (
                session.query(ReviewTaskRecord)
                .order_by(ReviewTaskRecord.created_at.asc())
                .all()
            )
            return [
                _review_task_payload(record)
                for record in records
                if can_view_review_task(
                    actor=actor,
                    owner_id=record.owner_id,
                    assignee=record.assignee,
                )
            ]
    return request.app.state.feedback_service.list_review_tasks(owner_id=context.user_id)


@router.post("/{task_id}/decision")
def submit_review_decision(
    request: Request,
    task_id: str,
    decision_request: ReviewDecisionRequest,
) -> dict[str, str]:
    context = get_user_context(request)
    session_factory = _audit_session_factory(request)
    if session_factory is not None:
        task = _decide_persisted_review_task(
            session_factory=session_factory,
            actor=Actor(id=context.user_id, role=context.role),
            task_id=task_id,
            decision=decision_request.decision,
            comment=decision_request.comment,
        )
        if task is None:
            if _persisted_review_task_exists(session_factory, task_id):
                raise HTTPException(status_code=403, detail="Forbidden")
            raise HTTPException(status_code=404, detail="Review task not found")
        record_audit_event(
            session_factory=session_factory,
            actor_id=context.user_id,
            action="review_task.decided",
            resource_type="review_task",
            resource_id=task.id,
            request_id=context.request_id,
            metadata={
                "decision": decision_request.decision,
                "target_type": task.target_type,
                "target_id": task.target_id,
            },
        )
        _store_review_decision_memory(
            session_factory=session_factory,
            task=task,
            decision=decision_request.decision,
        )
        return {"id": task.id, "status": task.status, "decision": decision_request.decision}

    task = request.app.state.feedback_service.decide_review_task(
        task_id=task_id,
        decision=decision_request.decision,
        comment=decision_request.comment,
        owner_id=context.user_id,
    )
    if task is None:
        if request.app.state.feedback_service.review_task_exists(task_id):
            raise HTTPException(status_code=403, detail="Forbidden")
        raise HTTPException(status_code=404, detail="Review task not found")
    session_factory = _audit_session_factory(request)
    if session_factory is not None:
        record_audit_event(
            session_factory=session_factory,
            actor_id=context.user_id,
            action="review_task.decided",
            resource_type="review_task",
            resource_id=task.id,
            request_id=context.request_id,
            metadata={
                "decision": decision_request.decision,
                "target_type": task.target_type,
                "target_id": task.target_id,
            },
        )
    return {"id": task.id, "status": task.status, "decision": decision_request.decision}


def _audit_session_factory(request: Request):
    document_service = getattr(request.app.state, "document_service", None)
    return getattr(document_service, "session_factory", None) or getattr(
        request.app.state,
        "session_factory",
        None,
    )


def _review_task_payload(record: ReviewTaskRecord) -> dict:
    metadata = sanitize_review_task_metadata(record.task_metadata)
    return {
        "id": record.id,
        "owner_id": record.owner_id,
        "target_type": record.target_type,
        "target_id": record.target_id,
        "status": record.status,
        "reason": record.reason,
        "assignee": record.assignee,
        "decision": record.decision,
        "comment": record.comment,
        "metadata": metadata,
        "task_metadata": metadata,
    }


def _decide_persisted_review_task(
    *,
    session_factory,
    actor: Actor,
    task_id: str,
    decision: str,
    comment: str,
) -> ReviewTaskRecord | None:
    with session_factory() as session:
        task = session.get(ReviewTaskRecord, task_id)
        if task is None:
            return None
        if not can_view_review_task(
            actor=actor,
            owner_id=task.owner_id,
            assignee=task.assignee,
        ):
            return None
        task.status = "decided"
        task.decision = decision
        task.comment = comment
        task.updated_at = utc_now()
        session.commit()
        session.refresh(task)
        session.expunge(task)
        return task


def _persisted_review_task_exists(session_factory, task_id: str) -> bool:
    with session_factory() as session:
        return session.get(ReviewTaskRecord, task_id) is not None


def _store_review_decision_memory(
    *,
    session_factory,
    task: ReviewTaskRecord,
    decision: str,
) -> bool:
    if task.target_type != "study_agent_workflow":
        return False

    metadata = sanitize_review_task_metadata(task.task_metadata)
    reasons = _safe_review_memory_reasons(task=task, metadata=metadata)
    if not reasons:
        return False

    workflow_id = metadata.get("workflow_id") or task.target_id
    try:
        StudyAgentMemoryService(session_factory).store_review_outcome(
            owner_id=task.owner_id,
            workflow_id=workflow_id,
            review_task_id=task.id,
            reasons=reasons,
            decision=decision,
            metadata=metadata,
        )
    except ValueError:
        return False
    return True


def _safe_review_memory_reasons(
    *,
    task: ReviewTaskRecord,
    metadata: dict,
) -> list[str]:
    metadata_reasons = metadata.get("review_reasons")
    if isinstance(metadata_reasons, list):
        return [
            reason
            for reason in metadata_reasons
            if isinstance(reason, str) and reason in SAFE_REVIEW_REASONS
        ]
    return [task.reason] if task.reason in SAFE_REVIEW_REASONS else []
