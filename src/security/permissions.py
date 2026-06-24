from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Resource:
    resource_type: str
    resource_id: str
    owner_id: str
    organization_id: str | None = None


class PermissionService:
    OWNER_ACTIONS = {"read", "update", "delete", "export", "retry", "cancel"}

    def can(self, actor_id: str, action: str, resource: Resource) -> bool:
        if action not in self.OWNER_ACTIONS:
            return False
        return actor_id == resource.owner_id


@dataclass(frozen=True)
class Actor:
    id: str
    role: str


def can_view_review_task(*, actor: Actor, owner_id: str, assignee: str | None) -> bool:
    if actor.role == "admin":
        return True
    if actor.id == owner_id:
        return True
    if actor.role == "reviewer" and assignee == actor.id:
        return True
    return False
