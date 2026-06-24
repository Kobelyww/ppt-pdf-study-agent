from fastapi import APIRouter, Request
from pydantic import BaseModel

from src.api.request_context import get_user_context
from src.db.models import FeedbackRecord, ReviewTaskRecord, utc_now
from src.security.audit import record_audit_event


router = APIRouter(prefix="/api/feedback", tags=["feedback"])


class FeedbackRequest(BaseModel):
    target_type: str
    target_id: str
    rating: int
    reason: str
    comment: str
    created_by: str | None = None


@router.post("")
def submit_feedback(request: Request, feedback_request: FeedbackRequest) -> dict[str, object]:
    context = get_user_context(request)
    payload = feedback_request.model_dump()
    payload["created_by"] = context.user_id
    feedback = request.app.state.feedback_service.submit_feedback(**payload)
    session_factory = _audit_session_factory(request)
    if session_factory is not None:
        _persist_feedback_and_review_task(
            session_factory=session_factory,
            feedback_id=feedback.id,
            owner_id=context.user_id,
            feedback_request=feedback_request,
        )
        record_audit_event(
            session_factory=session_factory,
            actor_id=context.user_id,
            action="feedback.created",
            resource_type="feedback",
            resource_id=feedback.id,
            request_id=context.request_id,
            metadata={
                "target_type": feedback.target_type,
                "target_id": feedback.target_id,
                "rating": feedback.rating,
                "reason": feedback.reason,
            },
        )
    return {
        "id": feedback.id,
        "rating": feedback.rating,
        "target_id": feedback.target_id,
    }


def _audit_session_factory(request: Request):
    document_service = getattr(request.app.state, "document_service", None)
    return getattr(document_service, "session_factory", None)


def _persist_feedback_and_review_task(
    *,
    session_factory,
    feedback_id: str,
    owner_id: str,
    feedback_request: FeedbackRequest,
) -> None:
    now = utc_now()
    with session_factory() as session:
        session.merge(
            FeedbackRecord(
                id=feedback_id,
                owner_id=owner_id,
                target_type=feedback_request.target_type,
                target_id=feedback_request.target_id,
                rating=feedback_request.rating,
                reason=feedback_request.reason,
                comment=feedback_request.comment,
                created_at=now,
            )
        )
        if feedback_request.rating <= 2:
            session.merge(
                ReviewTaskRecord(
                    id=f"review:{feedback_id}",
                    owner_id=owner_id,
                    target_type=feedback_request.target_type,
                    target_id=feedback_request.target_id,
                    status="open",
                    reason=feedback_request.reason,
                    created_at=now,
                    updated_at=now,
                )
            )
        session.commit()
