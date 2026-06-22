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
