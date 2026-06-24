from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, Request

from src.db.models import UserRecord
from src.security.auth import AuthenticatedUser, verify_access_token


@dataclass(frozen=True)
class UserContext:
    user_id: str
    request_id: str
    email: str | None = None
    role: str = "user"


def get_user_context(request: Request) -> UserContext:
    authenticated_user = getattr(request.state, "user", None)
    if isinstance(authenticated_user, AuthenticatedUser):
        user_id = authenticated_user.id
        email = authenticated_user.email
        role = authenticated_user.role
    else:
        user_id = request.headers.get("x-user-id") or "demo-user"
        email = None
        role = "user"
    request_id = request.headers.get("x-request-id") or f"req_{uuid4().hex}"
    return UserContext(user_id=user_id, request_id=request_id, email=email, role=role)


def authenticate_request(request: Request) -> AuthenticatedUser:
    session_factory = request.app.state.session_factory
    if session_factory is None:
        if request.app.state.allow_dev_user_header:
            return _dev_user_from_header(request)
        raise HTTPException(status_code=401, detail="Not authenticated")

    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        if not token:
            raise HTTPException(status_code=401, detail="Not authenticated")
        try:
            token_user = verify_access_token(token, secret_key=request.app.state.secret_key)
        except ValueError:
            raise HTTPException(status_code=401, detail="Invalid access token") from None
        return _active_user_from_database(session_factory, token_user.id)

    if request.app.state.allow_dev_user_header:
        return _dev_user_from_header(request)

    raise HTTPException(status_code=401, detail="Not authenticated")


def _active_user_from_database(session_factory: Any, user_id: str) -> AuthenticatedUser:
    with session_factory() as session:
        record = session.get(UserRecord, user_id)
        if record is None or not record.is_active:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return AuthenticatedUser(
            id=record.id,
            email=record.email,
            role=record.role,
            is_active=record.is_active,
        )


def _dev_user_from_header(request: Request) -> AuthenticatedUser:
    user_id = request.headers.get("x-user-id") or "demo-user"
    return AuthenticatedUser(
        id=user_id,
        email=f"{user_id}@local",
        role="user",
        is_active=True,
    )
