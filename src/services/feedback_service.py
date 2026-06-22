from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone


@dataclass(frozen=True)
class UserFeedback:
    id: str
    target_type: str
    target_id: str
    rating: int
    reason: str
    comment: str
    created_by: str
    created_at: datetime


@dataclass(frozen=True)
class ReviewTask:
    id: str
    owner_id: str
    target_type: str
    target_id: str
    status: str
    reason: str
    assignee: str | None = None
    decision: str | None = None
    comment: str | None = None


class FeedbackService:
    def __init__(self) -> None:
        self._feedback: list[UserFeedback] = []
        self._review_tasks: list[ReviewTask] = []

    def submit_feedback(
        self,
        target_type: str,
        target_id: str,
        rating: int,
        reason: str,
        comment: str,
        created_by: str,
    ) -> UserFeedback:
        feedback = UserFeedback(
            id=f"feedback:{len(self._feedback) + 1}",
            target_type=target_type,
            target_id=target_id,
            rating=rating,
            reason=reason,
            comment=comment,
            created_by=created_by,
            created_at=datetime.now(timezone.utc),
        )
        self._feedback.append(feedback)

        if rating <= 2:
            self._review_tasks.append(
                ReviewTask(
                    id=f"review:{len(self._review_tasks) + 1}",
                    owner_id=created_by,
                    target_type=target_type,
                    target_id=target_id,
                    status="open",
                    reason=reason,
                )
            )

        return feedback

    def list_review_tasks(self, owner_id: str | None = None) -> list[ReviewTask]:
        if owner_id is not None:
            return [task for task in self._review_tasks if task.owner_id == owner_id]
        return list(self._review_tasks)

    def review_task_exists(self, task_id: str) -> bool:
        return any(task.id == task_id for task in self._review_tasks)

    def decide_review_task(
        self,
        task_id: str,
        decision: str,
        comment: str = "",
        owner_id: str | None = None,
    ) -> ReviewTask | None:
        for index, task in enumerate(self._review_tasks):
            if task.id == task_id:
                if owner_id is not None and task.owner_id != owner_id:
                    return None
                decided = replace(
                    task,
                    status="decided",
                    decision=decision,
                    comment=comment,
                )
                self._review_tasks[index] = decided
                return decided
        return None
