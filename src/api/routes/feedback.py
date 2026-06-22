from fastapi import APIRouter, Request
from pydantic import BaseModel

from src.api.request_context import get_user_context
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
