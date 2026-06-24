from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.db.models import UserRecord
from src.security.auth import AuthenticatedUser, create_access_token, verify_password


router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str = Field(min_length=1)
    password: str = Field(min_length=1)


def user_response(user: AuthenticatedUser) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
    }


@router.post("/login")
def login(request: Request, login_request: LoginRequest) -> dict[str, str]:
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        raise HTTPException(status_code=503, detail="Authentication is not configured")
    with session_factory() as session:
        record = (
            session.query(UserRecord)
            .filter(UserRecord.email == login_request.email)
            .one_or_none()
        )
        if record is None or not record.is_active:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        if not verify_password(login_request.password, record.password_hash):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        user = AuthenticatedUser(
            id=record.id,
            email=record.email,
            role=record.role,
            is_active=record.is_active,
        )
    token = create_access_token(user, secret_key=request.app.state.secret_key)
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me")
def me(request: Request) -> dict[str, Any]:
    user = getattr(request.state, "user", None)
    if not isinstance(user, AuthenticatedUser):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user_response(user)
