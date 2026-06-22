from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from fastapi import Request


@dataclass(frozen=True)
class UserContext:
    user_id: str
    request_id: str


def get_user_context(request: Request) -> UserContext:
    user_id = request.headers.get("x-user-id") or "demo-user"
    request_id = request.headers.get("x-request-id") or f"req_{uuid4().hex}"
    return UserContext(user_id=user_id, request_id=request_id)
