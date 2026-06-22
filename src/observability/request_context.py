from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4


@dataclass(frozen=True)
class RequestContext:
    request_id: str
    user_id: str | None = None

    @classmethod
    def from_headers(cls, headers: dict[str, str]) -> "RequestContext":
        request_id = headers.get("x-request-id") or f"req_{uuid4().hex}"
        return cls(request_id=request_id, user_id=headers.get("x-user-id"))
