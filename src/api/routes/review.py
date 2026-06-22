from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.api.request_context import get_user_context
from src.security.audit import record_audit_event
from src.services.feedback_service import ReviewTask


router = APIRouter(prefix="/api/review-tasks", tags=["review"])


class ReviewDecisionRequest(BaseModel):
    decision: str
    comment: str = ""


@router.get("")
def list_review_tasks(request: Request) -> list[ReviewTask]:
    context = get_user_context(request)
    return request.app.state.feedback_service.list_review_tasks(owner_id=context.user_id)


@router.post("/{task_id}/decision")
def submit_review_decision(
    request: Request,
    task_id: str,
    decision_request: ReviewDecisionRequest,
) -> dict[str, str]:
    context = get_user_context(request)
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
    return getattr(document_service, "session_factory", None)
