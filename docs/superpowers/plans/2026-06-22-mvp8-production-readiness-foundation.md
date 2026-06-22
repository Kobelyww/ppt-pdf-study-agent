# MVP-8 Production Readiness Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the production-readiness foundation for the PPT/PDF Study Agent: authenticated users, production database/queue/storage backends, readiness checks, CI, Docker Compose production profile, and authenticated frontend flow.

**Architecture:** Preserve the existing FastAPI + SQLAlchemy + service-layer boundaries. Add auth, queue, and storage as focused modules behind dependency/factory interfaces so tests can keep using local fakes while production uses PostgreSQL, Redis, and S3/MinIO. Keep RAG routing out of this phase and reserve it for MVP-9.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, stdlib HMAC-signed JWT-shaped access tokens, stdlib PBKDF2 password hashing, Redis JSON queue payloads, boto3-compatible S3 client, Docker Compose, GitHub Actions, Vite/React.

---

## File Structure

Create or modify these files:

- `src/config.py` — add production readiness config values and fail-fast validation helpers.
- `src/db/models.py` — add `UserRecord` and indexes needed by MVP-8.
- `src/db/migrations/versions/0002_mvp8_auth_indexes.py` — add auth and index migration.
- `src/security/auth.py` — password hashing, JWT creation/validation, authenticated user context.
- `src/security/permissions.py` — role-aware permission helpers.
- `src/api/request_context.py` — derive `UserContext` from authenticated users and keep `x-user-id` only as dev override.
- `src/api/routes/auth.py` — login and `me` endpoints.
- `src/api/routes/audit.py` — admin-only audit query endpoint.
- `src/api/app.py` — wire auth/audit routes, readiness endpoint, app factories, production config.
- `src/storage/backend.py` — keep contract; add backend factory.
- `src/storage/s3_backend.py` — S3/MinIO-compatible implementation.
- `src/workers/queue.py` — add stable task payload queue interface and Redis-backed implementation.
- `src/workers/runner.py` — worker process entrypoint.
- `src/workers/tasks.py` — add idempotent guards and stale job recovery helper.
- `frontend/src/api.ts` — use bearer token, login, me, and remove `x-user-id` authority.
- `frontend/src/App.tsx` — add login/logout state and authenticated API calls.
- `frontend/src/pages/LoginPage.tsx` — login UI.
- `frontend/src/pages/DocumentsPage.tsx` — hide user switcher unless dev mode.
- `frontend/src/styles.css` — auth and error-state styles.
- `.env.example` — production variables.
- `docker-compose.yml` — local and production-like service profiles.
- `.github/workflows/ci.yml` — backend and frontend verification.
- `README.md` and `SPEC.md` — MVP-8 status, auth, deploy, and operations docs.
- Tests listed per task.

---

## Task 1: Production Config Surface

**Files:**
- Modify: `src/config.py`
- Modify: `.env.example`
- Test: `tests/test_mvp8_config.py`

- [ ] **Step 1: Write failing config tests**

Create `tests/test_mvp8_config.py`:

```python
import pytest

from src.config import ProductConfig, load_product_config


def test_product_config_defaults_to_local_dev(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("ALLOW_DEV_USER_HEADER", raising=False)
    config = load_product_config()
    assert config.app_env == "development"
    assert config.allow_dev_user_header is True
    assert config.storage_backend == "local"
    assert config.queue_backend == "memory"


def test_production_config_rejects_dev_user_header():
    config = ProductConfig(
        app_env="production",
        secret_key="secret",
        database_url="postgresql://app:app@db/app",
        queue_backend="redis",
        redis_url="redis://redis:6379/0",
        storage_backend="s3",
        s3_endpoint_url="http://minio:9000",
        s3_bucket="study-agent",
        s3_access_key_id="minio",
        s3_secret_access_key="minio-secret",
        allow_dev_user_header=True,
    )

    with pytest.raises(ValueError, match="ALLOW_DEV_USER_HEADER"):
        config.validate_production()


def test_production_config_requires_external_services():
    config = ProductConfig(
        app_env="production",
        secret_key="secret",
        database_url="",
        queue_backend="memory",
        redis_url="",
        storage_backend="local",
        allow_dev_user_header=False,
    )

    with pytest.raises(ValueError, match="DATABASE_URL"):
        config.validate_production()
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
pytest tests/test_mvp8_config.py -q
```

Expected: fail because `ProductConfig` does not exist.

- [ ] **Step 3: Add config implementation**

Append to `src/config.py`:

```python
@dataclass(frozen=True)
class ProductConfig:
    app_env: str = "development"
    secret_key: str = "dev-secret-change-me"
    allow_dev_user_header: bool = True
    database_url: str = "sqlite:///./study_agent.db"
    queue_backend: str = "memory"
    redis_url: str = ""
    storage_backend: str = "local"
    local_storage_root: str = "./data/storage"
    s3_endpoint_url: str = ""
    s3_bucket: str = ""
    s3_region: str = "us-east-1"
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_secure: bool = False

    def validate_production(self) -> None:
        if self.app_env != "production":
            return
        if self.allow_dev_user_header:
            raise ValueError("ALLOW_DEV_USER_HEADER must be false in production")
        required = {
            "SECRET_KEY": self.secret_key,
            "DATABASE_URL": self.database_url,
            "REDIS_URL": self.redis_url,
            "S3_ENDPOINT_URL": self.s3_endpoint_url,
            "S3_BUCKET": self.s3_bucket,
            "S3_ACCESS_KEY_ID": self.s3_access_key_id,
            "S3_SECRET_ACCESS_KEY": self.s3_secret_access_key,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(f"Missing production config: {', '.join(missing)}")
        if self.queue_backend != "redis":
            raise ValueError("QUEUE_BACKEND must be redis in production")
        if self.storage_backend != "s3":
            raise ValueError("STORAGE_BACKEND must be s3 in production")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def load_product_config() -> ProductConfig:
    config = ProductConfig(
        app_env=os.getenv("APP_ENV", "development"),
        secret_key=os.getenv("SECRET_KEY", "dev-secret-change-me"),
        allow_dev_user_header=_env_bool("ALLOW_DEV_USER_HEADER", True),
        database_url=os.getenv("DATABASE_URL", "sqlite:///./study_agent.db"),
        queue_backend=os.getenv("QUEUE_BACKEND", "memory"),
        redis_url=os.getenv("REDIS_URL", ""),
        storage_backend=os.getenv("STORAGE_BACKEND", "local"),
        local_storage_root=os.getenv("LOCAL_STORAGE_ROOT", "./data/storage"),
        s3_endpoint_url=os.getenv("S3_ENDPOINT_URL", ""),
        s3_bucket=os.getenv("S3_BUCKET", ""),
        s3_region=os.getenv("S3_REGION", "us-east-1"),
        s3_access_key_id=os.getenv("S3_ACCESS_KEY_ID", ""),
        s3_secret_access_key=os.getenv("S3_SECRET_ACCESS_KEY", ""),
        s3_secure=_env_bool("S3_SECURE", False),
    )
    config.validate_production()
    return config
```

- [ ] **Step 4: Update `.env.example`**

Add:

```dotenv
APP_ENV=development
SECRET_KEY=dev-secret-change-me
ALLOW_DEV_USER_HEADER=true
DATABASE_URL=sqlite:///./study_agent.db
QUEUE_BACKEND=memory
REDIS_URL=redis://localhost:6379/0
STORAGE_BACKEND=local
LOCAL_STORAGE_ROOT=./data/storage
S3_ENDPOINT_URL=http://localhost:9000
S3_BUCKET=study-agent
S3_REGION=us-east-1
S3_ACCESS_KEY_ID=minioadmin
S3_SECRET_ACCESS_KEY=minioadmin
S3_SECURE=false
```

- [ ] **Step 5: Verify tests pass**

Run:

```bash
pytest tests/test_mvp8_config.py -q
```

Expected: `3 passed`.

- [ ] **Step 6: Commit**

```bash
git add src/config.py .env.example tests/test_mvp8_config.py
git commit -m "feat: add production readiness configuration"
```

---

## Task 2: User Model And Auth Service

**Files:**
- Modify: `src/db/models.py`
- Create: `src/db/migrations/versions/0002_mvp8_auth_indexes.py`
- Create: `src/security/auth.py`
- Test: `tests/test_mvp8_auth.py`
- Test: `tests/test_db_models.py`

- [ ] **Step 1: Write failing auth tests**

Create `tests/test_mvp8_auth.py`:

```python
from datetime import datetime, timezone

import pytest

from src.security.auth import (
    AuthenticatedUser,
    create_access_token,
    hash_password,
    verify_access_token,
    verify_password,
)


def test_password_hash_round_trip():
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong", hashed)


def test_access_token_round_trip():
    user = AuthenticatedUser(
        id="user-1",
        email="user@example.com",
        role="user",
        is_active=True,
    )

    token = create_access_token(user, secret_key="secret", expires_minutes=30)
    decoded = verify_access_token(token, secret_key="secret")

    assert decoded.id == "user-1"
    assert decoded.email == "user@example.com"
    assert decoded.role == "user"


def test_invalid_access_token_is_rejected():
    with pytest.raises(ValueError, match="Invalid access token"):
        verify_access_token("not-a-token", secret_key="secret")
```

- [ ] **Step 2: Write failing DB model test**

Append to `tests/test_db_models.py`:

```python
def test_user_record_persists(session):
    from src.db.models import UserRecord

    user = UserRecord(
        id="user-1",
        email="user@example.com",
        password_hash="hash",
        role="user",
        is_active=True,
    )
    session.add(user)
    session.commit()

    saved = session.get(UserRecord, "user-1")
    assert saved.email == "user@example.com"
    assert saved.role == "user"
    assert saved.is_active is True
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```bash
pytest tests/test_mvp8_auth.py tests/test_db_models.py::test_user_record_persists -q
```

Expected: fail because auth helpers and `UserRecord` do not exist.

- [ ] **Step 4: Add `UserRecord`**

In `src/db/models.py`, add:

```python
from sqlalchemy import Boolean


class UserRecord(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="user", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(255))
    display_name: Mapped[Optional[str]] = mapped_column(String(255))
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
```

- [ ] **Step 5: Add migration**

Create `src/db/migrations/versions/0002_mvp8_auth_indexes.py`:

```python
"""mvp8 auth and indexes

Revision ID: 0002_mvp8_auth_indexes
Revises: 0001
Create Date: 2026-06-22
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_mvp8_auth_indexes"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("role", sa.String(length=32), nullable=False, server_default="user"))
    op.add_column("users", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("users", sa.Column("display_name", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE users SET password_hash = 'disabled$legacy$account' WHERE password_hash IS NULL")
    op.execute("UPDATE users SET updated_at = created_at WHERE updated_at IS NULL")
    op.alter_column("users", "password_hash", existing_type=sa.String(length=255), nullable=False)
    op.alter_column("users", "updated_at", existing_type=sa.DateTime(timezone=True), nullable=False)
    op.alter_column("users", "name", existing_type=sa.String(length=255), nullable=True)
    op.create_index("ix_users_role", "users", ["role"])
    op.create_index("ix_documents_owner_created", "documents", ["owner_id", "created_at"])
    op.create_index("ix_processing_jobs_owner_status", "processing_jobs", ["owner_id", "status"])
    op.create_index("ix_processing_jobs_owner_document", "processing_jobs", ["owner_id", "document_id"])
    op.create_index("ix_content_versions_doc_type_version", "content_versions", ["document_id", "target_type", "version"])
    op.create_index("ix_review_tasks_assignee_status", "review_tasks", ["assignee", "status"])
    op.create_index("ix_review_tasks_owner_status", "review_tasks", ["owner_id", "status"])
    op.create_index("ix_audit_events_resource_created", "audit_events", ["resource_type", "resource_id", "created_at"])
    op.create_index("ix_audit_events_actor_created", "audit_events", ["actor_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_actor_created", table_name="audit_events")
    op.drop_index("ix_audit_events_resource_created", table_name="audit_events")
    op.drop_index("ix_review_tasks_owner_status", table_name="review_tasks")
    op.drop_index("ix_review_tasks_assignee_status", table_name="review_tasks")
    op.drop_index("ix_content_versions_doc_type_version", table_name="content_versions")
    op.drop_index("ix_processing_jobs_owner_document", table_name="processing_jobs")
    op.drop_index("ix_processing_jobs_owner_status", table_name="processing_jobs")
    op.drop_index("ix_documents_owner_created", table_name="documents")
    op.drop_index("ix_users_role", table_name="users")
    op.alter_column("users", "name", existing_type=sa.String(length=255), nullable=False)
    op.drop_column("users", "updated_at")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "display_name")
    op.drop_column("users", "is_active")
    op.drop_column("users", "role")
    op.drop_column("users", "password_hash")
```

- [ ] **Step 6: Add auth service**

Create `src/security/auth.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import hmac
import json
from uuid import uuid4


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    email: str
    role: str
    is_active: bool


def hash_password(password: str, *, salt: str | None = None) -> str:
    salt = salt or uuid4().hex
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000)
    return f"pbkdf2_sha256${salt}${base64.urlsafe_b64encode(digest).decode('ascii')}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, salt, expected = password_hash.split("$", 2)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    candidate = hash_password(password, salt=salt)
    return hmac.compare_digest(candidate, password_hash)


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def create_access_token(
    user: AuthenticatedUser,
    *,
    secret_key: str,
    expires_minutes: int = 30,
) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": user.id,
        "email": user.email,
        "role": user.role,
        "exp": int((datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)).timestamp()),
    }
    signing_input = ".".join(
        [
            _b64encode(json.dumps(header, separators=(",", ":")).encode("utf-8")),
            _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
        ]
    )
    signature = hmac.new(secret_key.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_b64encode(signature)}"


def verify_access_token(token: str, *, secret_key: str) -> AuthenticatedUser:
    try:
        header_b64, payload_b64, signature_b64 = token.split(".", 2)
        signing_input = f"{header_b64}.{payload_b64}"
        expected = hmac.new(secret_key.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
        actual = _b64decode(signature_b64)
        if not hmac.compare_digest(expected, actual):
            raise ValueError
        payload = json.loads(_b64decode(payload_b64))
        if int(payload["exp"]) < int(datetime.now(timezone.utc).timestamp()):
            raise ValueError
        return AuthenticatedUser(
            id=str(payload["sub"]),
            email=str(payload["email"]),
            role=str(payload["role"]),
            is_active=True,
        )
    except Exception as exc:
        raise ValueError("Invalid access token") from exc
```

- [ ] **Step 7: Verify auth and model tests pass**

Run:

```bash
pytest tests/test_mvp8_auth.py tests/test_db_models.py::test_user_record_persists -q
```

Expected: tests pass.

- [ ] **Step 8: Commit**

```bash
git add src/db/models.py src/db/migrations/versions/0002_mvp8_auth_indexes.py src/security/auth.py tests/test_mvp8_auth.py tests/test_db_models.py
git commit -m "feat: add users and token auth primitives"
```

---

## Task 3: Auth API And Request Context

**Files:**
- Create: `src/api/routes/auth.py`
- Modify: `src/api/request_context.py`
- Modify: `src/api/app.py`
- Test: `tests/test_api_auth.py`

- [ ] **Step 1: Write failing API auth tests**

Create `tests/test_api_auth.py`:

```python
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.app import create_app
from src.db.models import Base, UserRecord
from src.security.auth import AuthenticatedUser, create_access_token, hash_password


def _client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        session.add_all(
            [
                UserRecord(
                    id="user-1",
                    email="user@example.com",
                    password_hash=hash_password("secret-password"),
                    role="user",
                    is_active=True,
                ),
                UserRecord(
                    id="inactive-1",
                    email="inactive@example.com",
                    password_hash=hash_password("secret-password"),
                    role="user",
                    is_active=False,
                ),
            ]
        )
        session.commit()
    return TestClient(create_app(session_factory=Session, secret_key="test-secret")), Session


def test_login_returns_access_token_and_me():
    client, _Session = _client()

    login = client.post(
        "/api/auth/login",
        json={"email": "user@example.com", "password": "secret-password"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    me = client.get("/api/auth/me", headers={"authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "user@example.com"


def test_login_rejects_bad_password():
    client, _Session = _client()

    response = client.post(
        "/api/auth/login",
        json={"email": "user@example.com", "password": "wrong"},
    )

    assert response.status_code == 401


def test_me_rejects_inactive_user_token():
    client, _Session = _client()
    token = create_access_token(
        AuthenticatedUser(
            id="inactive-1",
            email="inactive@example.com",
            role="user",
            is_active=False,
        ),
        secret_key="test-secret",
    )

    response = client.get("/api/auth/me", headers={"authorization": f"Bearer {token}"})

    assert response.status_code == 401
```

- [ ] **Step 2: Run failing auth API tests**

Run:

```bash
pytest tests/test_api_auth.py -q
```

Expected: fail because auth route and `create_app` parameters do not exist.

- [ ] **Step 3: Implement auth route**

Create `src/api/routes/auth.py`:

```python
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.db.models import UserRecord
from src.security.auth import AuthenticatedUser, create_access_token, verify_password


router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=1024)


@router.post("/login")
def login(request: Request, payload: LoginRequest) -> dict[str, Any]:
    session_factory = request.app.state.session_factory
    with session_factory() as session:
        user = session.query(UserRecord).filter(UserRecord.email == payload.email).one_or_none()
        if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        user.last_login_at = datetime.now(timezone.utc)
        session.commit()
        auth_user = AuthenticatedUser(
            id=user.id,
            email=user.email,
            role=user.role,
            is_active=user.is_active,
        )
    token = create_access_token(
        auth_user,
        secret_key=request.app.state.secret_key,
    )
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me")
def me(request: Request) -> dict[str, Any]:
    user = request.state.user
    return {
        "id": user.id,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
    }
```

- [ ] **Step 4: Update request context**

Modify `src/api/request_context.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
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


def authenticate_request(request: Request) -> AuthenticatedUser:
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1]
        try:
            token_user = verify_access_token(token, secret_key=request.app.state.secret_key)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail="Invalid access token") from exc
        session_factory = getattr(request.app.state, "session_factory", None)
        if session_factory is None:
            return token_user
        with session_factory() as session:
            user = session.get(UserRecord, token_user.id)
            if user is None or not user.is_active:
                raise HTTPException(status_code=401, detail="Inactive or unknown user")
            return AuthenticatedUser(
                id=user.id,
                email=user.email,
                role=user.role,
                is_active=user.is_active,
            )

    if request.app.state.allow_dev_user_header:
        user_id = request.headers.get("x-user-id") or "demo-user"
        return AuthenticatedUser(id=user_id, email=f"{user_id}@local.dev", role="user", is_active=True)

    raise HTTPException(status_code=401, detail="Authentication required")


def get_user_context(request: Request) -> UserContext:
    user = getattr(request.state, "user", None)
    if user is None:
        user = authenticate_request(request)
        request.state.user = user
    request_id = request.headers.get("x-request-id") or f"req_{uuid4().hex}"
    return UserContext(
        user_id=user.id,
        request_id=request_id,
        email=user.email,
        role=user.role,
    )
```

- [ ] **Step 5: Update app wiring**

Modify `src/api/app.py`:

```python
from src.api.routes.auth import router as auth_router
from src.config import load_product_config
```

Change signature:

```python
def create_app(
    document_service: Any | None = None,
    job_queue: Any | None = None,
    session_factory: Any | None = None,
    secret_key: str | None = None,
    allow_dev_user_header: bool | None = None,
) -> FastAPI:
```

Inside `create_app` before routers:

```python
    product_config = load_product_config()
    app.state.secret_key = secret_key or product_config.secret_key
    app.state.allow_dev_user_header = (
        product_config.allow_dev_user_header
        if allow_dev_user_header is None
        else allow_dev_user_header
    )
    app.state.session_factory = session_factory
    if session_factory is None and hasattr(app.state.document_service, "session_factory"):
        app.state.session_factory = app.state.document_service.session_factory
```

Add middleware:

```python
    @app.middleware("http")
    async def attach_user(request, call_next):
        if request.url.path.startswith("/api/auth/login") or request.url.path in {"/health", "/ready"}:
            return await call_next(request)
        from src.api.request_context import authenticate_request
        request.state.user = authenticate_request(request)
        return await call_next(request)
```

Include auth router:

```python
    app.include_router(auth_router)
```

- [ ] **Step 6: Verify auth API tests pass**

Run:

```bash
pytest tests/test_api_auth.py -q
```

Expected: `3 passed`.

- [ ] **Step 7: Run selected existing API tests**

Run:

```bash
pytest tests/test_api_documents.py tests/test_api_permissions_audit.py tests/test_quality_feedback.py -q
```

Expected: existing tests still pass through dev header override.

- [ ] **Step 8: Commit**

```bash
git add src/api/app.py src/api/request_context.py src/api/routes/auth.py tests/test_api_auth.py
git commit -m "feat: add authenticated API context"
```

---

## Task 4: Role-Aware Audit Query

**Files:**
- Create: `src/api/routes/audit.py`
- Modify: `src/api/app.py`
- Test: `tests/test_api_audit_query.py`

- [ ] **Step 1: Write failing audit query tests**

Create `tests/test_api_audit_query.py`:

```python
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.app import create_app
from src.db.models import AuditEventRecord, Base, UserRecord
from src.security.auth import create_access_token, hash_password, AuthenticatedUser


def _client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        session.add_all(
            [
                UserRecord(id="admin-1", email="admin@example.com", password_hash=hash_password("secret"), role="admin", is_active=True),
                UserRecord(id="user-1", email="user@example.com", password_hash=hash_password("secret"), role="user", is_active=True),
                AuditEventRecord(
                    id="audit-1",
                    actor_id="user-1",
                    action="document.uploaded",
                    resource_type="document",
                    resource_id="doc-1",
                    request_id="req-1",
                    event_metadata={"filename": "notes.pdf"},
                ),
            ]
        )
        session.commit()
    app = create_app(session_factory=Session, secret_key="test-secret", allow_dev_user_header=False)
    return TestClient(app)


def _token(user_id: str, email: str, role: str) -> str:
    return create_access_token(
        AuthenticatedUser(id=user_id, email=email, role=role, is_active=True),
        secret_key="test-secret",
    )


def test_admin_can_query_audit_events():
    client = _client()
    token = _token("admin-1", "admin@example.com", "admin")

    response = client.get("/api/audit-events", headers={"authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()[0]["action"] == "document.uploaded"


def test_non_admin_cannot_query_audit_events():
    client = _client()
    token = _token("user-1", "user@example.com", "user")

    response = client.get("/api/audit-events", headers={"authorization": f"Bearer {token}"})

    assert response.status_code == 403
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
pytest tests/test_api_audit_query.py -q
```

Expected: fail because audit route does not exist.

- [ ] **Step 3: Implement audit route**

Create `src/api/routes/audit.py`:

```python
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from src.api.request_context import get_user_context
from src.db.models import AuditEventRecord


router = APIRouter(prefix="/api/audit-events", tags=["audit"])


@router.get("")
def list_audit_events(
    request: Request,
    actor_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    action: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, Any]]:
    context = get_user_context(request)
    if context.role != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")
    session_factory = request.app.state.session_factory
    with session_factory() as session:
        query = session.query(AuditEventRecord).order_by(AuditEventRecord.created_at.desc())
        if actor_id is not None:
            query = query.filter(AuditEventRecord.actor_id == actor_id)
        if resource_type is not None:
            query = query.filter(AuditEventRecord.resource_type == resource_type)
        if resource_id is not None:
            query = query.filter(AuditEventRecord.resource_id == resource_id)
        if action is not None:
            query = query.filter(AuditEventRecord.action == action)
        records = query.limit(limit).all()
        return [
            {
                "id": record.id,
                "actor_id": record.actor_id,
                "action": record.action,
                "resource_type": record.resource_type,
                "resource_id": record.resource_id,
                "request_id": record.request_id,
                "metadata": record.event_metadata,
                "created_at": record.created_at.isoformat() if record.created_at else None,
            }
            for record in records
        ]
```

- [ ] **Step 4: Wire route in app**

Modify `src/api/app.py`:

```python
from src.api.routes.audit import router as audit_router
...
app.include_router(audit_router)
```

- [ ] **Step 5: Verify tests pass**

Run:

```bash
pytest tests/test_api_audit_query.py tests/test_security_audit.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add src/api/routes/audit.py src/api/app.py tests/test_api_audit_query.py
git commit -m "feat: add admin audit query API"
```

---

## Task 5: Reviewer Role Permissions

**Files:**
- Modify: `src/security/permissions.py`
- Modify: `src/api/routes/review.py`
- Test: `tests/test_api_review_permissions.py`

- [ ] **Step 1: Write failing reviewer permission tests**

Create `tests/test_api_review_permissions.py`:

```python
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.app import create_app
from src.db.models import Base, ReviewTaskRecord, UserRecord
from src.security.auth import AuthenticatedUser, create_access_token, hash_password


def _client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        session.add_all(
            [
                UserRecord(id="owner-1", email="owner@example.com", password_hash=hash_password("secret"), role="user", is_active=True),
                UserRecord(id="reviewer-1", email="reviewer@example.com", password_hash=hash_password("secret"), role="reviewer", is_active=True),
                UserRecord(id="other-1", email="other@example.com", password_hash=hash_password("secret"), role="user", is_active=True),
                ReviewTaskRecord(
                    id="task-1",
                    owner_id="owner-1",
                    target_type="question",
                    target_id="q-1",
                    status="open",
                    reason="incorrect_answer",
                    assignee="reviewer-1",
                ),
            ]
        )
        session.commit()
    return TestClient(create_app(session_factory=Session, secret_key="test-secret", allow_dev_user_header=False))


def _token(user_id: str, email: str, role: str) -> str:
    return create_access_token(
        AuthenticatedUser(id=user_id, email=email, role=role, is_active=True),
        secret_key="test-secret",
    )


def test_assigned_reviewer_can_list_review_task():
    client = _client()
    token = _token("reviewer-1", "reviewer@example.com", "reviewer")

    response = client.get("/api/review-tasks", headers={"authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()[0]["id"] == "task-1"


def test_unassigned_user_cannot_list_review_task():
    client = _client()
    token = _token("other-1", "other@example.com", "user")

    response = client.get("/api/review-tasks", headers={"authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json() == []
```

- [ ] **Step 2: Run failing reviewer permission tests**

Run:

```bash
pytest tests/test_api_review_permissions.py -q
```

Expected: fail because review route only lists owner-scoped in-memory review tasks.

- [ ] **Step 3: Add permission helper**

Modify `src/security/permissions.py`:

```python
from dataclasses import dataclass


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
```

- [ ] **Step 4: Update review route DB-backed listing**

Modify `src/api/routes/review.py` so `list_review_tasks` uses `session_factory` when present:

```python
from src.db.models import ReviewTaskRecord
from src.security.permissions import Actor, can_view_review_task


from typing import Any


def _review_task_payload(record: ReviewTaskRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "owner_id": record.owner_id,
        "target_type": record.target_type,
        "target_id": record.target_id,
        "status": record.status,
        "reason": record.reason,
        "assignee": record.assignee,
        "decision": record.decision,
        "comment": record.comment,
    }


@router.get("")
def list_review_tasks(request: Request) -> list[Any]:
    context = get_user_context(request)
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is not None:
        actor = Actor(id=context.user_id, role=context.role)
        with session_factory() as session:
            records = session.query(ReviewTaskRecord).order_by(ReviewTaskRecord.created_at.desc()).all()
            return [
                _review_task_payload(record)
                for record in records
                if can_view_review_task(actor=actor, owner_id=record.owner_id, assignee=record.assignee)
            ]
    return request.app.state.feedback_service.list_review_tasks(owner_id=context.user_id)
```

- [ ] **Step 5: Verify reviewer permissions**

Run:

```bash
pytest tests/test_api_review_permissions.py tests/test_api_permissions_audit.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add src/security/permissions.py src/api/routes/review.py tests/test_api_review_permissions.py
git commit -m "feat: add reviewer role permissions"
```

---

## Task 6: Storage Backend Factory And S3 Backend

**Files:**
- Modify: `src/storage/backend.py`
- Create: `src/storage/s3_backend.py`
- Test: `tests/test_storage_backend.py`
- Test: `tests/test_s3_storage_backend.py`

- [ ] **Step 1: Write failing factory and S3 tests**

Append to `tests/test_storage_backend.py`:

```python
from src.config import ProductConfig
from src.storage.backend import create_storage_backend, LocalStorageBackend


def test_create_storage_backend_returns_local_backend(tmp_path):
    backend = create_storage_backend(
        ProductConfig(storage_backend="local", local_storage_root=str(tmp_path))
    )
    assert isinstance(backend, LocalStorageBackend)
```

Create `tests/test_s3_storage_backend.py`:

```python
from src.storage.s3_backend import S3StorageBackend


class FakeS3Client:
    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body, ContentType):
        self.objects[(Bucket, Key)] = {"body": Body, "content_type": ContentType}

    def get_object(self, Bucket, Key):
        return {"Body": FakeBody(self.objects[(Bucket, Key)]["body"])}


class FakeBody:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body


def test_s3_backend_puts_and_reads_bytes():
    client = FakeS3Client()
    backend = S3StorageBackend(bucket="study-agent", client=client)

    stored = backend.put_bytes(
        namespace="uploads",
        original_filename="notes.pdf",
        content=b"hello",
        content_type="application/pdf",
    )

    assert stored.storage_uri.startswith("s3://study-agent/uploads/")
    assert backend.read_bytes(stored.storage_uri) == b"hello"
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
pytest tests/test_storage_backend.py tests/test_s3_storage_backend.py -q
```

Expected: fail because factory and S3 backend do not exist.

- [ ] **Step 3: Implement S3 backend**

Create `src/storage/s3_backend.py`:

```python
from __future__ import annotations

from urllib.parse import urlparse

from src.storage.backend import StoredObject, StorageBackend, StorageError, _safe_filename


class S3StorageBackend(StorageBackend):
    def __init__(self, *, bucket: str, client):
        self.bucket = bucket
        self.client = client

    def put_bytes(
        self,
        *,
        namespace: str,
        original_filename: str,
        content: bytes,
        content_type: str,
    ) -> StoredObject:
        safe_name = _safe_filename(original_filename)
        content_hash = self._content_hash(content)
        key = f"{namespace}/{content_hash}-{safe_name}"
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=content,
                ContentType=content_type,
            )
        except Exception as exc:
            raise StorageError("failed to write object") from exc
        return StoredObject(
            storage_uri=f"s3://{self.bucket}/{key}",
            content_hash=content_hash,
            original_filename=original_filename,
            size_bytes=len(content),
            content_type=content_type,
        )

    def read_bytes(self, storage_uri: str) -> bytes:
        parsed = urlparse(storage_uri)
        if parsed.scheme != "s3" or parsed.netloc != self.bucket:
            raise StorageError("storage uri does not belong to this bucket")
        key = parsed.path.lstrip("/")
        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except Exception as exc:
            raise StorageError("failed to read object") from exc

    def exists(self, storage_uri: str) -> bool:
        parsed = urlparse(storage_uri)
        if parsed.scheme != "s3" or parsed.netloc != self.bucket:
            return False
        key = parsed.path.lstrip("/")
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    @staticmethod
    def _content_hash(content: bytes) -> str:
        from hashlib import sha256

        return f"sha256:{sha256(content).hexdigest()}"
```

- [ ] **Step 4: Add factory**

In `src/storage/backend.py`, add:

```python
def create_storage_backend(config):
    if config.storage_backend == "local":
        return LocalStorageBackend(config.local_storage_root)
    if config.storage_backend == "s3":
        import boto3
        from src.storage.s3_backend import S3StorageBackend

        client = boto3.client(
            "s3",
            endpoint_url=config.s3_endpoint_url or None,
            region_name=config.s3_region,
            aws_access_key_id=config.s3_access_key_id,
            aws_secret_access_key=config.s3_secret_access_key,
            use_ssl=config.s3_secure,
        )
        return S3StorageBackend(bucket=config.s3_bucket, client=client)
    raise ValueError(f"Unsupported storage backend: {config.storage_backend}")


def _safe_filename(original_filename: str) -> str:
    suffix = LocalStorageBackend._safe_suffix(original_filename)
    base = Path(original_filename).stem.lower()
    safe_base = re.sub(r"[^a-z0-9_-]+", "-", base).strip("-")[:64] or "upload"
    return f"{safe_base}{suffix}"
```

- [ ] **Step 5: Add dependency**

Add `boto3>=1.34.0` to `requirements.txt`.

- [ ] **Step 6: Verify tests pass**

Run:

```bash
pytest tests/test_storage_backend.py tests/test_s3_storage_backend.py -q
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add src/storage/backend.py src/storage/s3_backend.py tests/test_storage_backend.py tests/test_s3_storage_backend.py requirements.txt
git commit -m "feat: add s3 storage backend"
```

---

## Task 7: Redis Queue Payloads And Worker Runner

**Files:**
- Modify: `src/workers/queue.py`
- Create: `src/workers/runner.py`
- Modify: `src/workers/tasks.py`
- Test: `tests/test_mvp8_queue.py`
- Test: `tests/test_workers_product_flow.py`

- [ ] **Step 1: Write failing queue payload tests**

Create `tests/test_mvp8_queue.py`:

```python
from src.workers.queue import QueuePayload, RedisTaskQueue


class FakeRedis:
    def __init__(self):
        self.items = []

    def rpush(self, key, value):
        self.items.append((key, value))

    def lpop(self, key):
        for index, (stored_key, value) in enumerate(self.items):
            if stored_key == key:
                self.items.pop(index)
                return value
        return None


def test_queue_payload_round_trip():
    payload = QueuePayload(
        task_type="process_document",
        job_id="job-1",
        owner_id="user-1",
        document_id="doc-1",
        export_job_id=None,
    )

    restored = QueuePayload.from_json(payload.to_json())

    assert restored.task_type == "process_document"
    assert restored.job_id == "job-1"


def test_redis_queue_enqueue_and_dequeue():
    redis = FakeRedis()
    queue = RedisTaskQueue(redis_client=redis, queue_name="study-agent")
    payload = QueuePayload(
        task_type="process_document",
        job_id="job-1",
        owner_id="user-1",
        document_id="doc-1",
    )

    queue.enqueue(payload)
    restored = queue.dequeue()

    assert restored == payload
```

Append to `tests/test_workers_product_flow.py`:

```python
from datetime import datetime, timedelta, timezone

from src.db.models import ProcessingJob
from src.workers.tasks import recover_stale_running_jobs


def test_recover_stale_running_jobs_marks_old_running_job_failed(tmp_path: Path):
    Session = _session_factory()
    service = DocumentService(
        session_factory=Session,
        storage=LocalStorageBackend(tmp_path / "objects"),
    )
    upload = service.create_upload(
        owner_id="user-1",
        filename="notes.pdf",
        content=b"Derivatives measure instantaneous rate of change.",
        content_type="application/pdf",
    )
    stale_started_at = datetime.now(timezone.utc) - timedelta(hours=2)
    with Session() as session:
        job = session.get(ProcessingJob, upload.job.id)
        job.status = "running"
        job.started_at = stale_started_at
        job.updated_at = stale_started_at
        session.commit()

    recovered = recover_stale_running_jobs(
        session_factory=Session,
        max_age_seconds=300,
        error_message="Recovered stale running job",
    )

    with Session() as session:
        job = session.get(ProcessingJob, upload.job.id)

    assert recovered == 1
    assert job.status == "failed"
    assert job.error_message == "Recovered stale running job"
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
pytest tests/test_mvp8_queue.py -q
```

Expected: fail because queue payload classes do not exist.

- [ ] **Step 3: Implement queue payload and Redis queue**

Add to `src/workers/queue.py`:

```python
from dataclasses import dataclass
import json


@dataclass(frozen=True)
class QueuePayload:
    task_type: str
    owner_id: str
    job_id: str | None = None
    document_id: str | None = None
    export_job_id: str | None = None

    def to_json(self) -> str:
        return json.dumps(self.__dict__, separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_json(cls, raw: str | bytes):
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return cls(**json.loads(raw))


class RedisTaskQueue:
    def __init__(self, *, redis_client, queue_name: str = "study-agent-tasks"):
        self.redis_client = redis_client
        self.queue_name = queue_name

    def enqueue(self, payload: QueuePayload) -> None:
        self.redis_client.rpush(self.queue_name, payload.to_json())

    def dequeue(self) -> QueuePayload | None:
        raw = self.redis_client.lpop(self.queue_name)
        if raw is None:
            return None
        return QueuePayload.from_json(raw)
```

- [ ] **Step 4: Add worker runner**

Create `src/workers/runner.py`:

```python
from __future__ import annotations

import os
import time

from src.config import load_product_config
from src.db.session import create_session_factory, get_engine
from src.storage.backend import create_storage_backend
from src.workers.queue import QueuePayload
from src.workers.tasks import run_export_task, run_product_document_task


def run_queue_payload(payload: QueuePayload, *, session_factory, storage) -> None:
    if payload.task_type == "process_document":
        if payload.job_id is None or payload.document_id is None:
            raise ValueError("process_document payload requires job_id and document_id")
        run_product_document_task(
            job_id=payload.job_id,
            document_id=payload.document_id,
            owner_id=payload.owner_id,
            session_factory=session_factory,
            storage=storage,
        )
        return
    if payload.task_type == "export":
        if payload.export_job_id is None:
            raise ValueError("export payload requires export_job_id")
        run_export_task(
            export_job_id=payload.export_job_id,
            owner_id=payload.owner_id,
            session_factory=session_factory,
            storage=storage,
        )
        return
    raise ValueError(f"unsupported task type: {payload.task_type}")


def run_worker_loop(*, queue, session_factory, storage, poll_seconds: float = 1.0) -> None:
    while True:
        payload = queue.dequeue()
        if payload is None:
            time.sleep(poll_seconds)
            continue
        run_queue_payload(payload, session_factory=session_factory, storage=storage)


def main() -> None:
    import redis
    from src.workers.queue import RedisTaskQueue

    config = load_product_config()
    engine = get_engine(config.database_url)
    session_factory = create_session_factory(engine)
    storage = create_storage_backend(config)
    queue = RedisTaskQueue(
        redis_client=redis.from_url(config.redis_url),
        queue_name=os.getenv("QUEUE_NAME", "study-agent-tasks"),
    )
    run_worker_loop(queue=queue, session_factory=session_factory, storage=storage)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Add idempotent guards**

Modify `run_product_document_task` in `src/workers/tasks.py` before setting status running:

```python
        if job.status == "completed":
            return
```

Modify `run_export_task` similarly:

```python
        if export.status == "completed":
            return
```

Add stale running job recovery to `src/workers/tasks.py`:

```python
from datetime import timedelta


def recover_stale_running_jobs(
    *,
    session_factory,
    max_age_seconds: int,
    error_message: str = "Recovered stale running job",
) -> int:
    cutoff = _utc_now() - timedelta(seconds=max_age_seconds)
    recovered = 0
    with session_factory() as session:
        jobs = (
            session.query(ProcessingJob)
            .filter(ProcessingJob.status == "running")
            .filter(ProcessingJob.updated_at < cutoff)
            .all()
        )
        for job in jobs:
            job.status = "failed"
            job.error_message = error_message
            job.completed_at = _utc_now()
            job.updated_at = job.completed_at
            recovered += 1
        session.commit()
    return recovered
```

- [ ] **Step 6: Verify queue tests pass**

Run:

```bash
pytest tests/test_mvp8_queue.py tests/test_workers_product_flow.py tests/test_export_product_flow.py -q
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add src/workers/queue.py src/workers/runner.py src/workers/tasks.py tests/test_mvp8_queue.py
git commit -m "feat: add redis-compatible worker payloads"
```

---

## Task 8: Readiness Checks And Structured Logging

**Files:**
- Modify: `src/observability/health.py`
- Create: `src/observability/logging.py`
- Modify: `src/api/app.py`
- Test: `tests/test_readiness.py`

- [ ] **Step 1: Write failing readiness tests**

Create `tests/test_readiness.py`:

```python
from fastapi.testclient import TestClient

from src.api.app import create_app


class HealthyDependency:
    def healthcheck(self):
        return True


class FailingDependency:
    def healthcheck(self):
        return False


def test_ready_returns_ok_when_dependencies_healthy():
    app = create_app(
        readiness_checks={
            "database": HealthyDependency(),
            "queue": HealthyDependency(),
            "storage": HealthyDependency(),
        }
    )
    client = TestClient(app)

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_ready_returns_503_when_dependency_fails():
    app = create_app(
        readiness_checks={
            "database": HealthyDependency(),
            "queue": FailingDependency(),
            "storage": HealthyDependency(),
        }
    )
    client = TestClient(app)

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["queue"] is False
    assert response.json()["status"] == "not_ready"
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
pytest tests/test_readiness.py -q
```

Expected: fail because `readiness_checks` and `/ready` do not exist.

- [ ] **Step 3: Implement readiness route**

Modify `create_app` signature in `src/api/app.py`:

```python
readiness_checks: dict[str, Any] | None = None,
```

Add:

```python
    from fastapi.responses import JSONResponse

    app.state.readiness_checks = readiness_checks or {}

    @app.get("/ready")
    def ready():
        checks = {}
        for name, dependency in app.state.readiness_checks.items():
            try:
                checks[name] = bool(dependency.healthcheck())
            except Exception:
                checks[name] = False
        if checks and not all(checks.values()):
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready", "checks": checks},
            )
        return {"status": "ready", "checks": checks}
```

- [ ] **Step 4: Add structured logging helper**

Create `src/observability/logging.py`:

```python
import logging
from typing import Any


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    logger.info(
        event,
        extra={"event": event, "fields": {key: value for key, value in fields.items() if value is not None}},
    )
```

- [ ] **Step 5: Verify readiness tests pass**

Run:

```bash
pytest tests/test_readiness.py tests/test_observability.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add src/api/app.py src/observability/logging.py tests/test_readiness.py
git commit -m "feat: add readiness checks"
```

---

## Task 9: Frontend Authentication Flow

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/App.tsx`
- Create: `frontend/src/pages/LoginPage.tsx`
- Modify: `frontend/src/pages/DocumentsPage.tsx`
- Modify: `frontend/src/styles.css`
- Test: frontend build

- [ ] **Step 1: Add auth API client functions**

Modify `frontend/src/api.ts`:

```typescript
export interface AuthUser {
  id: string;
  email: string;
  role: string;
  is_active: boolean;
}

export interface AuthSession {
  access_token: string;
  token_type: string;
}

function authHeaders(token: string): HeadersInit {
  return {authorization: `Bearer ${token}`};
}

export async function login(email: string, password: string): Promise<AuthSession> {
  const response = await fetch(`${API_BASE}/api/auth/login`, {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify({email, password}),
  });
  return parseJson<AuthSession>(response, "Failed to log in");
}

export async function getMe(token: string): Promise<AuthUser> {
  const response = await fetch(`${API_BASE}/api/auth/me`, {headers: authHeaders(token)});
  return parseJson<AuthUser>(response, "Failed to load current user");
}

export async function listDocuments(token: string): Promise<ApiDocument[]> {
  const response = await fetch(`${API_BASE}/api/documents`, {headers: authHeaders(token)});
  return parseJson<ApiDocument[]>(response, "Failed to load documents");
}

export async function uploadDocument(
  token: string,
  file: File,
): Promise<{ document: ApiDocument; job: ApiJob }> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${API_BASE}/api/documents`, {
    method: "POST",
    headers: authHeaders(token),
    body: form,
  });
  return parseJson<{ document: ApiDocument; job: ApiJob }>(response, "Failed to upload document");
}
```

Replace the remaining exported API functions with token-first signatures:

```typescript
export async function getJob(token: string, jobId: string): Promise<ApiJob> {
  const response = await fetch(`${API_BASE}/api/jobs/${jobId}`, {headers: authHeaders(token)});
  return parseJson<ApiJob>(response, "Failed to load job");
}

export async function retryJob(token: string, jobId: string): Promise<ApiJob> {
  const response = await fetch(`${API_BASE}/api/jobs/${jobId}/retry`, {
    method: "POST",
    headers: authHeaders(token),
  });
  return parseJson<ApiJob>(response, "Failed to retry job");
}

export async function listVersions(
  token: string,
  documentId: string,
): Promise<ContentVersion[]> {
  const response = await fetch(`${API_BASE}/api/documents/${documentId}/versions`, {
    headers: authHeaders(token),
  });
  return parseJson<ContentVersion[]>(response, "Failed to load versions");
}

export async function createExport(
  token: string,
  documentId: string,
  versionId: string,
  format: string,
): Promise<ExportJob> {
  const response = await fetch(`${API_BASE}/api/exports/${documentId}`, {
    method: "POST",
    headers: {...authHeaders(token), "content-type": "application/json"},
    body: JSON.stringify({version_id: versionId, format}),
  });
  return parseJson<ExportJob>(response, "Failed to create export");
}

export async function submitFeedback(
  token: string,
  targetType: string,
  targetId: string,
  rating: number,
  reason: string,
  comment: string,
): Promise<{id: string; rating: number; target_id: string}> {
  const response = await fetch(`${API_BASE}/api/feedback`, {
    method: "POST",
    headers: {...authHeaders(token), "content-type": "application/json"},
    body: JSON.stringify({
      target_type: targetType,
      target_id: targetId,
      rating,
      reason,
      comment,
    }),
  });
  return parseJson<{id: string; rating: number; target_id: string}>(
    response,
    "Failed to submit feedback",
  );
}

export async function listReviewTasks(token: string): Promise<ReviewTaskSummary[]> {
  const response = await fetch(`${API_BASE}/api/review-tasks`, {headers: authHeaders(token)});
  return parseJson<ReviewTaskSummary[]>(response, "Failed to load review tasks");
}
```

Remove the old `headers(userId)` helper after these replacements.

- [ ] **Step 2: Add LoginPage**

Create `frontend/src/pages/LoginPage.tsx`:

```typescript
import { type FormEvent, useState } from "react";

interface LoginPageProps {
  error: string | null;
  onLogin: (email: string, password: string) => Promise<void>;
}

function LoginPage({error, onLogin}: LoginPageProps) {
  const [email, setEmail] = useState("user@example.com");
  const [password, setPassword] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await onLogin(email, password);
  }

  return (
    <main className="login-shell">
      <form className="login-panel" onSubmit={handleSubmit}>
        <p className="eyebrow">Production Readiness</p>
        <h1>PPT PDF Study Agent</h1>
        {error ? <div className="error-banner" role="alert">{error}</div> : null}
        <label>
          <span>Email</span>
          <input value={email} onChange={(event) => setEmail(event.target.value)} type="email" />
        </label>
        <label>
          <span>Password</span>
          <input value={password} onChange={(event) => setPassword(event.target.value)} type="password" />
        </label>
        <button className="primary-action" type="submit">Log in</button>
      </form>
    </main>
  );
}

export default LoginPage;
```

- [ ] **Step 3: Update App auth state**

In `frontend/src/App.tsx`, add token and user state:

```typescript
const [token, setToken] = useState(() => localStorage.getItem("study-agent-token") ?? "");
const [currentUser, setCurrentUser] = useState<AuthUser | null>(null);
```

Add login/logout handlers:

```typescript
async function handleLogin(email: string, password: string) {
  setError(null);
  const session = await login(email, password);
  localStorage.setItem("study-agent-token", session.access_token);
  setToken(session.access_token);
  setCurrentUser(await getMe(session.access_token));
}

function handleLogout() {
  localStorage.removeItem("study-agent-token");
  setToken("");
  setCurrentUser(null);
}
```

Render `<LoginPage error={error} onLogin={handleLogin} />` when no token exists.

Update existing product API calls in `frontend/src/App.tsx` to pass `token`:

```typescript
const nextDocuments = await listDocuments(token);
setReviewTasks(await listReviewTasks(token));
const loadedVersions = await listVersions(token, selectedDocumentId);
const result = await uploadDocument(token, file);
const job = await getJob(token, jobId);
const retriedJob = await retryJob(token, jobId);
const exportJob = await createExport(token, selectedDocument.id, version.id, format);
await submitFeedback(token, targetType, targetId, rating, reason, comment);
```

Render login and logout:

```typescript
if (!token || !currentUser) {
  return <LoginPage error={error} onLogin={handleLogin} />;
}

<button className="secondary-action" type="button" onClick={handleLogout}>
  Log out
</button>
```

- [ ] **Step 4: Remove production user switcher**

Modify `frontend/src/pages/DocumentsPage.tsx` props:

```typescript
interface DocumentsPageProps {
  documents: ApiDocument[];
  isLoading: boolean;
  isUploading: boolean;
  selectedDocumentId: string;
  currentUserEmail: string;
  showDevUserSwitcher?: boolean;
  userId?: string;
  onSelectDocument: (documentId: string) => void;
  onUpload: (file: File) => Promise<void>;
  onUserIdChange?: (userId: string) => void;
}
```

Replace the current user switcher block with:

```tsx
<div className="current-user">
  <span>Current user</span>
  <strong>{currentUserEmail}</strong>
</div>

{showDevUserSwitcher && onUserIdChange ? (
  <label className="user-switcher" htmlFor="user-id">
    <span>Development user override</span>
    <input
      id="user-id"
      type="text"
      value={userId ?? "demo-user"}
      onChange={(event) => onUserIdChange(event.target.value || "demo-user")}
    />
  </label>
) : null}
```

Update the `DocumentsPage` call in `frontend/src/App.tsx`:

```tsx
<DocumentsPage
  documents={documents}
  isLoading={isLoading}
  isUploading={isUploading}
  selectedDocumentId={selectedDocumentId}
  currentUserEmail={currentUser.email}
  showDevUserSwitcher={false}
  onSelectDocument={setSelectedDocumentId}
  onUpload={handleUpload}
/>
```

- [ ] **Step 5: Verify frontend build**

Run:

```bash
npm run build
```

Expected: build succeeds.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api.ts frontend/src/App.tsx frontend/src/pages/LoginPage.tsx frontend/src/pages/DocumentsPage.tsx frontend/src/styles.css
git commit -m "feat: add authenticated frontend session"
```

---

## Task 10: Docker Compose Production-Like Profile

**Files:**
- Modify: `docker-compose.yml`
- Create: `Dockerfile`
- Modify: `.env.example`
- Create: `scripts/smoke_mvp8.py`
- Test: compose config

- [ ] **Step 1: Create Dockerfile**

Create `Dockerfile`:

```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Update compose services**

Modify `docker-compose.yml` to include:

```yaml
services:
  api:
    build: .
    command: uvicorn src.api.app:app --host 0.0.0.0 --port 8000
    env_file: .env
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
      minio:
        condition: service_healthy
    ports:
      - "8000:8000"

  worker:
    build: .
    command: python -m src.workers.runner
    env_file: .env
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
      minio:
        condition: service_healthy

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: study_agent
      POSTGRES_PASSWORD: study_agent
      POSTGRES_DB: study_agent
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U study_agent"]
      interval: 5s
      timeout: 3s
      retries: 10

  redis:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 10

  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    ports:
      - "9000:9000"
      - "9001:9001"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/ready"]
      interval: 5s
      timeout: 3s
      retries: 10
```

- [ ] **Step 3: Add smoke script**

Create `scripts/smoke_mvp8.py`:

```python
import os
from urllib.request import urlopen


BASE_URL = os.getenv("SMOKE_BASE_URL", "http://localhost:8000")


def main() -> None:
    with urlopen(f"{BASE_URL}/ready", timeout=10) as response:
        if response.status != 200:
            raise SystemExit(f"readiness failed: {response.status}")
    print("ready ok")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Verify compose config**

Run:

```bash
docker compose config
```

Expected: config renders without errors.

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml Dockerfile .env.example scripts/smoke_mvp8.py requirements.txt
git commit -m "chore: add production-like compose profile"
```

---

## Task 11: GitHub Actions CI

**Files:**
- Create: `.github/workflows/ci.yml`
- Test: local command parity

- [ ] **Step 1: Create CI workflow**

Create `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
  pull_request:

jobs:
  backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install backend dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
      - name: Run backend tests
        run: pytest -q

  frontend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: frontend
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: "npm"
          cache-dependency-path: frontend/package-lock.json
      - name: Install frontend dependencies
        run: npm ci
      - name: Build frontend
        run: npm run build
```

- [ ] **Step 2: Verify local parity commands**

Run:

```bash
pytest -q
```

Expected: backend tests pass.

Run:

```bash
npm run build
```

from `frontend/`.

Expected: frontend build passes.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: verify backend and frontend"
```

---

## Task 12: MVP-8 Product Smoke Test And Docs

**Files:**
- Create: `tests/test_mvp8_authenticated_product_loop.py`
- Modify: `README.md`
- Modify: `SPEC.md`

- [ ] **Step 1: Write authenticated product loop test**

Create `tests/test_mvp8_authenticated_product_loop.py`:

```python
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.app import create_app
from src.db.models import Base, UserRecord
from src.security.auth import hash_password
from src.services.document_service import DocumentService
from src.services.version_service import create_persisted_version
from src.storage.backend import LocalStorageBackend


def test_authenticated_mvp8_product_loop(tmp_path: Path):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        session.add_all(
            [
                UserRecord(id="user-1", email="user1@example.com", password_hash=hash_password("secret"), role="user", is_active=True),
                UserRecord(id="user-2", email="user2@example.com", password_hash=hash_password("secret"), role="user", is_active=True),
            ]
        )
        session.commit()

    service = DocumentService(
        session_factory=Session,
        storage=LocalStorageBackend(tmp_path / "objects"),
    )
    client = TestClient(
        create_app(
            document_service=service,
            session_factory=Session,
            secret_key="test-secret",
            allow_dev_user_header=False,
        )
    )
    token_1 = client.post("/api/auth/login", json={"email": "user1@example.com", "password": "secret"}).json()["access_token"]
    token_2 = client.post("/api/auth/login", json={"email": "user2@example.com", "password": "secret"}).json()["access_token"]

    upload = client.post(
        "/api/documents",
        headers={"authorization": f"Bearer {token_1}"},
        files={"file": ("notes.pdf", b"Derivatives measure change.", "application/pdf")},
    )
    assert upload.status_code == 202
    document_id = upload.json()["document"]["id"]

    create_persisted_version(
        session_factory=Session,
        document_id=document_id,
        target_type="outline",
        target_id=document_id,
        content="# Derivatives",
        created_by="test",
        change_summary="test outline",
        content_metadata={},
    )

    assert client.get(f"/api/documents/{document_id}/outline", headers={"authorization": f"Bearer {token_1}"}).status_code == 200
    assert client.get(f"/api/documents/{document_id}", headers={"authorization": f"Bearer {token_2}"}).status_code == 403
```

- [ ] **Step 2: Run smoke test**

Run:

```bash
pytest tests/test_mvp8_authenticated_product_loop.py -q
```

Expected: pass.

- [ ] **Step 3: Update README**

Add a section:

```markdown
## MVP-8 Production Readiness

MVP-8 introduces authenticated users, short-lived JWT auth, PostgreSQL production configuration, Redis-backed queue payloads, S3/MinIO storage, readiness checks, and CI. Development can still use local SQLite/in-memory queue/local storage, but production mode must disable `ALLOW_DEV_USER_HEADER`.
```

- [ ] **Step 4: Update SPEC**

Add this section to `SPEC.md` after the MVP-7 status section:

```markdown
## MVP-8 Production Readiness Foundation

Status: implemented when the MVP-8 implementation plan verification passes.

MVP-8 introduces persisted users, short-lived bearer tokens, and request context derived from authenticated credentials. `x-user-id` is retained only as a development/test override guarded by `ALLOW_DEV_USER_HEADER=false` in production.

Production runtime boundaries are PostgreSQL for persistence, Redis JSON payloads for workers, and S3/MinIO-compatible object storage behind the `StorageBackend` contract. Docker Compose runs API, worker, Postgres, Redis, and MinIO in a production-like local profile.

Readiness checks must cover database, queue, and storage connectivity. CI must run backend tests and frontend build before changes land.
```

- [ ] **Step 5: Run full verification**

Run:

```bash
pytest -q
```

Expected: full backend suite passes.

Run:

```bash
npm run build
```

from `frontend/`.

Expected: frontend build passes.

- [ ] **Step 6: Commit**

```bash
git add tests/test_mvp8_authenticated_product_loop.py README.md SPEC.md
git commit -m "test: verify MVP-8 production readiness loop"
```

---

## Final Verification

Run:

```bash
pytest -q
```

Expected: all backend tests pass with only explicitly reasoned xfails.

Run:

```bash
npm run build
```

from `frontend/`.

Expected: frontend build succeeds.

Run:

```bash
git status --short --branch
```

Expected: clean branch with all MVP-8 commits present.

## Spec Review Checklist

- Authenticated users replace `x-user-id` as production authority.
- `ALLOW_DEV_USER_HEADER` exists and is disabled in production.
- Product APIs can run with bearer token auth.
- Owner isolation still works.
- Admin audit query exists.
- PostgreSQL production configuration is documented.
- Redis-backed queue payloads are stable JSON payloads.
- S3/MinIO backend implements the existing storage contract.
- Readiness checks cover DB, queue, and storage.
- Frontend supports login/logout and authenticated API calls.
- Docker Compose includes API, worker, Postgres, Redis, and MinIO.
- CI runs backend tests and frontend build.
- RAG automatic routing remains out of scope and deferred to MVP-9.

## Quality Review Checklist

- No route trusts `owner_id`, `created_by`, or `user_id` from request JSON.
- Auth failures return `401`; authorization failures return `403`.
- Production config fails fast when required variables are missing.
- Queue payloads contain stable primitive data only.
- Worker tasks are idempotent for completed jobs.
- Storage code never exposes raw local paths to API clients.
- Audit metadata remains sanitized.
- Existing MVP-7 tests still pass.
- Frontend text and buttons do not overflow at mobile widths.
