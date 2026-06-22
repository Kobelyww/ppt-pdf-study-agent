# MVP-7 Internal Beta Product Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an internal-beta product loop where a lightweight user can upload a PPT/PDF, track processing, view generated outline/questions, submit feedback, create exports, and rely on owner isolation.

**Architecture:** Extend the existing FastAPI, SQLAlchemy, worker, storage, and React/Vite code rather than replacing it. Move the current metadata-only API and in-memory services toward persisted document/job/export state, a `StorageBackend` interface with local storage, and API-driven frontend state. Keep advanced RAG and self-evolution out of the critical MVP-7 path.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy, Alembic, pytest, React, TypeScript, Vite, local filesystem storage.

---

## Reference Documents

- Spec: `docs/superpowers/specs/2026-06-16-mvp7-internal-beta-product-loop-design.md`
- Current API entrypoint: `src/api/app.py`
- Current document route: `src/api/routes/documents.py`
- Current job route: `src/api/routes/jobs.py`
- Current DB models: `src/db/models.py`
- Current migration: `src/db/migrations/versions/0001_initial_product_schema.py`
- Current worker queue/tasks: `src/workers/queue.py`, `src/workers/tasks.py`
- Current frontend root: `frontend/src/App.tsx`

## File Structure

New and modified files should keep these responsibilities:

- `src/api/request_context.py` — extract lightweight `x-user-id` and `x-request-id` context.
- `src/storage/backend.py` — define storage protocol, result dataclass, local backend, and safe URI operations.
- `src/services/document_service.py` — persisted document and processing job service.
- `src/services/version_service.py` — extend content versions with optional DB-backed repository methods while preserving existing in-memory tests.
- `src/services/export_service.py` — create and persist export jobs, render markdown/json exports.
- `src/services/feedback_service.py` — add owner-aware feedback/review behavior while preserving existing in-memory tests.
- `src/security/permissions.py` and `src/security/audit.py` — reuse existing permission/audit primitives and integrate them into API services.
- `src/workers/tasks.py` — add product task handlers for document processing and export rendering.
- `src/api/routes/*.py` — expose product endpoints and enforce user context.
- `frontend/src/api.ts` — typed frontend API client with `x-user-id`.
- `frontend/src/App.tsx` and page components — replace static mock state with internal-beta API flow.

---

## Task 1: Storage Backend Abstraction and Local Backend

**Files:**
- Create: `src/storage/backend.py`
- Modify: `src/storage/__init__.py`
- Modify: `src/storage/file_store.py`
- Test: `tests/test_storage_backend.py`
- Test: `tests/test_storage.py`

- [ ] **Step 1: Add failing storage backend tests**

Create `tests/test_storage_backend.py`:

```python
from pathlib import Path

import pytest

from src.storage.backend import LocalStorageBackend, StorageError


def test_local_storage_backend_puts_and_reads_upload(tmp_path: Path):
    backend = LocalStorageBackend(root=tmp_path)

    stored = backend.put_bytes(
        namespace="uploads",
        original_filename="Lecture Notes.pdf",
        content=b"study content",
        content_type="application/pdf",
    )

    assert stored.storage_uri.startswith("local://uploads/")
    assert stored.original_filename == "Lecture Notes.pdf"
    assert stored.content_type == "application/pdf"
    assert stored.size_bytes == len(b"study content")
    assert backend.exists(stored.storage_uri)
    assert backend.read_bytes(stored.storage_uri) == b"study content"


def test_local_storage_backend_rejects_path_traversal_uri(tmp_path: Path):
    backend = LocalStorageBackend(root=tmp_path)

    with pytest.raises(StorageError, match="invalid storage uri"):
        backend.read_bytes("local://uploads/../secret.txt")


def test_local_storage_backend_writes_export_namespace(tmp_path: Path):
    backend = LocalStorageBackend(root=tmp_path)

    stored = backend.put_bytes(
        namespace="exports",
        original_filename="outline.md",
        content=b"# Outline",
        content_type="text/markdown",
    )

    assert stored.storage_uri.startswith("local://exports/")
    assert backend.read_bytes(stored.storage_uri) == b"# Outline"
```

- [ ] **Step 2: Run storage backend tests to verify failure**

Run:

```bash
pytest tests/test_storage_backend.py -q
```

Expected: fail with `ModuleNotFoundError` or missing `src.storage.backend`.

- [ ] **Step 3: Implement storage backend**

Create `src/storage/backend.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Protocol
from urllib.parse import quote, unquote, urlparse
import re
from uuid import uuid4


class StorageError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredObject:
    storage_uri: str
    content_hash: str
    original_filename: str
    content_type: str
    size_bytes: int


class StorageBackend(Protocol):
    def put_bytes(
        self,
        *,
        namespace: str,
        original_filename: str,
        content: bytes,
        content_type: str,
    ) -> StoredObject:
        ...

    def read_bytes(self, storage_uri: str) -> bytes:
        ...

    def exists(self, storage_uri: str) -> bool:
        ...


class LocalStorageBackend:
    def __init__(self, root: Path | str):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put_bytes(
        self,
        *,
        namespace: str,
        original_filename: str,
        content: bytes,
        content_type: str,
    ) -> StoredObject:
        namespace_path = self._safe_namespace(namespace)
        target_dir = self.root / namespace_path
        target_dir.mkdir(parents=True, exist_ok=True)
        suffix = self._safe_suffix(original_filename)
        stored_name = f"{uuid4().hex}{suffix}"
        target_path = target_dir / stored_name
        target_path.write_bytes(content)
        return StoredObject(
            storage_uri=f"local://{quote(namespace_path)}/{stored_name}",
            content_hash=f"sha256:{sha256(content).hexdigest()}",
            original_filename=original_filename,
            content_type=content_type,
            size_bytes=len(content),
        )

    def read_bytes(self, storage_uri: str) -> bytes:
        return self._path_from_uri(storage_uri).read_bytes()

    def exists(self, storage_uri: str) -> bool:
        try:
            return self._path_from_uri(storage_uri).exists()
        except StorageError:
            return False

    def _path_from_uri(self, storage_uri: str) -> Path:
        parsed = urlparse(storage_uri)
        if parsed.scheme != "local" or not parsed.netloc or not parsed.path:
            raise StorageError("invalid storage uri")
        namespace = self._safe_namespace(unquote(parsed.netloc))
        filename = Path(unquote(parsed.path).lstrip("/")).name
        if not filename or "/" in filename or "\\" in filename:
            raise StorageError("invalid storage uri")
        path = (self.root / namespace / filename).resolve()
        if not path.is_relative_to(self.root):
            raise StorageError("invalid storage uri")
        return path

    @staticmethod
    def _safe_namespace(namespace: str) -> str:
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", namespace):
            raise StorageError("invalid storage namespace")
        return namespace

    @staticmethod
    def _safe_suffix(original_filename: str) -> str:
        suffix = Path(original_filename).suffix.lower()
        if re.fullmatch(r"\.[a-z0-9]{1,16}", suffix):
            return suffix
        return ""
```

- [ ] **Step 4: Export backend API and preserve `FileStore` compatibility**

Modify `src/storage/__init__.py` so it exports both old and new storage APIs:

```python
from src.storage.backend import (
    LocalStorageBackend,
    StorageBackend,
    StorageError,
    StoredObject,
)
from src.storage.file_store import FileStore, StoredFile

__all__ = [
    "FileStore",
    "LocalStorageBackend",
    "StorageBackend",
    "StorageError",
    "StoredFile",
    "StoredObject",
]
```

Keep `src/storage/file_store.py` intact unless imports need formatting changes.

- [ ] **Step 5: Verify storage tests**

Run:

```bash
pytest tests/test_storage_backend.py tests/test_storage.py -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/storage/backend.py src/storage/__init__.py tests/test_storage_backend.py
git commit -m "feat: add local storage backend abstraction"
```

---

## Task 2: Persisted Document and Job Services

**Files:**
- Modify: `src/db/models.py`
- Modify: `src/db/migrations/versions/0001_initial_product_schema.py`
- Create: `src/services/document_service.py`
- Create: `src/api/request_context.py`
- Modify: `src/api/app.py`
- Modify: `src/api/routes/documents.py`
- Modify: `src/api/routes/jobs.py`
- Test: `tests/test_document_service.py`
- Test: `tests/test_api_documents.py`
- Test: `tests/test_db_models.py`
- Test: `tests/test_db_migrations.py`

- [ ] **Step 1: Add failing document service tests**

Create `tests/test_document_service.py`:

```python
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base
from src.services.document_service import DocumentService
from src.storage.backend import LocalStorageBackend


def _service(tmp_path: Path) -> DocumentService:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return DocumentService(
        session_factory=Session,
        storage=LocalStorageBackend(tmp_path / "objects"),
    )


def test_document_service_upload_creates_owned_document_and_job(tmp_path: Path):
    service = _service(tmp_path)

    result = service.create_upload(
        owner_id="user-1",
        filename="notes.pdf",
        content=b"calculus notes",
        content_type="application/pdf",
    )

    assert result.document.owner_id == "user-1"
    assert result.document.original_filename == "notes.pdf"
    assert result.document.status == "uploaded"
    assert result.document.storage_uri.startswith("local://uploads/")
    assert result.job.owner_id == "user-1"
    assert result.job.document_id == result.document.id
    assert result.job.status == "queued"
    assert result.job.progress == 0


def test_document_service_lists_only_owned_documents(tmp_path: Path):
    service = _service(tmp_path)
    service.create_upload(
        owner_id="user-1",
        filename="first.pdf",
        content=b"first",
        content_type="application/pdf",
    )
    service.create_upload(
        owner_id="user-2",
        filename="second.pdf",
        content=b"second",
        content_type="application/pdf",
    )

    user_1_documents = service.list_documents(owner_id="user-1")

    assert [document.owner_id for document in user_1_documents] == ["user-1"]
    assert [document.original_filename for document in user_1_documents] == ["first.pdf"]


def test_document_service_retries_failed_job(tmp_path: Path):
    service = _service(tmp_path)
    result = service.create_upload(
        owner_id="user-1",
        filename="notes.pdf",
        content=b"notes",
        content_type="application/pdf",
    )
    service.update_job_status(
        job_id=result.job.id,
        status="failed",
        owner_id="user-1",
        error_message="parser failed",
    )

    retried = service.retry_job(job_id=result.job.id, owner_id="user-1")

    assert retried.status == "queued"
    assert retried.progress == 0
    assert retried.error_message is None
```

- [ ] **Step 2: Add failing API tests for upload, owner isolation, and retry**

Append these tests to `tests/test_api_documents.py` while keeping existing tests until they are intentionally updated:

```python
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base
from src.services.document_service import DocumentService
from src.storage.backend import LocalStorageBackend


def _client_with_persisted_service(tmp_path: Path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    service = DocumentService(
        session_factory=Session,
        storage=LocalStorageBackend(tmp_path / "objects"),
    )
    return TestClient(create_app(document_service=service)), service


def test_upload_file_creates_document_and_job_for_current_user(tmp_path: Path):
    client, _service = _client_with_persisted_service(tmp_path)

    response = client.post(
        "/api/documents",
        headers={"x-user-id": "user-1"},
        files={"file": ("notes.pdf", b"calculus notes", "application/pdf")},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["document"]["owner_id"] == "user-1"
    assert body["document"]["original_filename"] == "notes.pdf"
    assert body["job"]["owner_id"] == "user-1"
    assert body["job"]["document_id"] == body["document"]["id"]


def test_document_list_is_scoped_to_current_user(tmp_path: Path):
    client, _service = _client_with_persisted_service(tmp_path)
    client.post(
        "/api/documents",
        headers={"x-user-id": "user-1"},
        files={"file": ("first.pdf", b"first", "application/pdf")},
    )
    client.post(
        "/api/documents",
        headers={"x-user-id": "user-2"},
        files={"file": ("second.pdf", b"second", "application/pdf")},
    )

    response = client.get("/api/documents", headers={"x-user-id": "user-1"})

    assert response.status_code == 200
    assert [document["original_filename"] for document in response.json()] == ["first.pdf"]


def test_cross_user_job_access_returns_403(tmp_path: Path):
    client, _service = _client_with_persisted_service(tmp_path)
    upload = client.post(
        "/api/documents",
        headers={"x-user-id": "user-1"},
        files={"file": ("notes.pdf", b"notes", "application/pdf")},
    ).json()

    response = client.get(
        f"/api/jobs/{upload['job']['id']}",
        headers={"x-user-id": "user-2"},
    )

    assert response.status_code == 403


def test_failed_job_can_be_retried_by_owner(tmp_path: Path):
    client, service = _client_with_persisted_service(tmp_path)
    upload = client.post(
        "/api/documents",
        headers={"x-user-id": "user-1"},
        files={"file": ("notes.pdf", b"notes", "application/pdf")},
    ).json()
    service.update_job_status(
        job_id=upload["job"]["id"],
        owner_id="user-1",
        status="failed",
        error_message="parser failed",
    )

    response = client.post(
        f"/api/jobs/{upload['job']['id']}/retry",
        headers={"x-user-id": "user-1"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "queued"
```

- [ ] **Step 3: Run selected tests to verify failure**

Run:

```bash
pytest tests/test_document_service.py tests/test_api_documents.py -q
```

Expected: fail because `DocumentService`, upload handling, owner fields, and retry endpoints are not implemented.

- [ ] **Step 4: Update DB models for MVP-7 document/job state**

Modify `src/db/models.py`:

- Add `JSON` to SQLAlchemy imports.
- Add `owner_id`, `status`, `updated_at` to `Document`.
- Keep existing `title`, `source_type`, `storage_uri`, `content_hash`, and `original_filename` for backward compatibility.
- Add `owner_id`, `job_type`, `progress`, `started_at`, `completed_at` to `ProcessingJob`.
- Change the job status constraint to accept both current and MVP-7 spellings during transition: `queued`, `running`, `completed`, `succeeded`, `failed`, `cancelled`, `canceled`.
- Add `DocumentArtifactRecord`.
- Add optional `document_id` and a mapped attribute named `content_metadata` stored in a database column named `metadata` to `ContentVersionRecord`. Do not name a SQLAlchemy model attribute `metadata`, because Declarative Base reserves that name.
- Add owner/timestamps to `ExportJobRecord`, `FeedbackRecord`, `ReviewTaskRecord`, and `AuditEventRecord` if these classes do not exist.
- For every ORM field backed by a database column named `metadata`, use a Python attribute ending in `_metadata`, for example `artifact_metadata`, `content_metadata`, or `event_metadata`.

The model names expected by later tasks are:

```python
class DocumentArtifactRecord(Base):
    __tablename__ = "document_artifacts"

class ExportJobRecord(Base):
    __tablename__ = "export_jobs"

class FeedbackRecord(Base):
    __tablename__ = "feedback"

class ReviewTaskRecord(Base):
    __tablename__ = "review_tasks"

class AuditEventRecord(Base):
    __tablename__ = "audit_events"
```

The DB model tests must instantiate each new record class and call `Base.metadata.create_all(engine)` successfully. Include at least one assertion that `ContentVersionRecord.content_metadata` persists through the database column named `metadata`.

- [ ] **Step 5: Update initial migration to match ORM**

Modify `src/db/migrations/versions/0001_initial_product_schema.py` so it matches the ORM fields added in Step 4:

- `documents.owner_id`, `documents.status`, `documents.updated_at`
- `processing_jobs.owner_id`, `processing_jobs.job_type`, `processing_jobs.progress`, `processing_jobs.started_at`, `processing_jobs.completed_at`
- `document_artifacts`
- `content_versions.document_id`, database column `content_versions.metadata` mapped through the ORM attribute `content_metadata`
- database column `document_artifacts.metadata` mapped through ORM attribute `artifact_metadata`
- database column `audit_events.metadata` mapped through ORM attribute `event_metadata`
- `export_jobs.owner_id`, `export_jobs.created_at`, `export_jobs.completed_at`
- `feedback.owner_id`, `feedback.reason`, `feedback.created_at`
- `review_tasks`
- `audit_events`

Keep existing tables from MVP-1 through MVP-6 intact.

- [ ] **Step 6: Implement request context helper**

Create `src/api/request_context.py`:

```python
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
```

- [ ] **Step 7: Implement persisted document service**

Create `src/services/document_service.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

from sqlalchemy.orm import Session

from src.db.models import Document, ProcessingJob
from src.storage.backend import StorageBackend


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class DocumentUploadResult:
    document: Document
    job: ProcessingJob


class DocumentService:
    def __init__(self, session_factory: Callable[[], Session], storage: StorageBackend):
        self.session_factory = session_factory
        self.storage = storage

    def create_upload(
        self,
        *,
        owner_id: str,
        filename: str,
        content: bytes,
        content_type: str,
    ) -> DocumentUploadResult:
        stored = self.storage.put_bytes(
            namespace="uploads",
            original_filename=filename,
            content=content,
            content_type=content_type,
        )
        now = _now()
        document = Document(
            id=f"doc-{uuid4().hex}",
            owner_id=owner_id,
            title=filename,
            source_type=self._source_type(filename, content_type),
            storage_uri=stored.storage_uri,
            content_hash=stored.content_hash,
            original_filename=filename,
            status="uploaded",
            created_at=now,
            updated_at=now,
        )
        job = ProcessingJob(
            id=f"job-{uuid4().hex}",
            document_id=document.id,
            owner_id=owner_id,
            job_type="process_document",
            status="queued",
            progress=0,
            created_at=now,
            updated_at=now,
        )
        with self.session_factory() as session:
            session.add(document)
            session.add(job)
            session.commit()
            session.refresh(document)
            session.refresh(job)
            session.expunge(document)
            session.expunge(job)
        return DocumentUploadResult(document=document, job=job)

    def list_documents(self, *, owner_id: str) -> list[Document]:
        with self.session_factory() as session:
            documents = (
                session.query(Document)
                .filter(Document.owner_id == owner_id)
                .order_by(Document.created_at.asc())
                .all()
            )
            for document in documents:
                session.expunge(document)
            return documents

    def get_document(self, *, document_id: str, owner_id: str) -> Document | None:
        with self.session_factory() as session:
            document = (
                session.query(Document)
                .filter(Document.id == document_id, Document.owner_id == owner_id)
                .one_or_none()
            )
            if document is not None:
                session.expunge(document)
            return document

    def get_job(self, *, job_id: str, owner_id: str) -> ProcessingJob | None:
        with self.session_factory() as session:
            job = (
                session.query(ProcessingJob)
                .filter(ProcessingJob.id == job_id, ProcessingJob.owner_id == owner_id)
                .one_or_none()
            )
            if job is not None:
                session.expunge(job)
            return job

    def job_exists(self, *, job_id: str) -> bool:
        with self.session_factory() as session:
            return session.query(ProcessingJob.id).filter(ProcessingJob.id == job_id).first() is not None

    def update_job_status(
        self,
        *,
        job_id: str,
        owner_id: str | None = None,
        status: str,
        error_message: str | None = None,
        progress: int | None = None,
    ) -> ProcessingJob:
        with self.session_factory() as session:
            query = session.query(ProcessingJob).filter(ProcessingJob.id == job_id)
            if owner_id is not None:
                query = query.filter(ProcessingJob.owner_id == owner_id)
            job = query.one()
            job.status = status
            job.error_message = error_message
            if progress is not None:
                job.progress = progress
            job.updated_at = _now()
            if status == "running" and job.started_at is None:
                job.started_at = job.updated_at
            if status in {"completed", "succeeded", "failed", "cancelled", "canceled"}:
                job.completed_at = job.updated_at
            session.commit()
            session.refresh(job)
            session.expunge(job)
            return job

    def retry_job(self, *, job_id: str, owner_id: str) -> ProcessingJob:
        return self.update_job_status(
            job_id=job_id,
            owner_id=owner_id,
            status="queued",
            error_message=None,
            progress=0,
        )

    @staticmethod
    def _source_type(filename: str, content_type: str) -> str:
        suffix = filename.lower().rsplit(".", maxsplit=1)[-1] if "." in filename else ""
        if suffix in {"pdf", "ppt", "pptx"}:
            return suffix
        if "pdf" in content_type:
            return "pdf"
        if "presentation" in content_type or "powerpoint" in content_type:
            return "pptx"
        return "unknown"
```

- [ ] **Step 8: Update app factory and routes**

Modify `src/api/app.py` to keep dependency injection and stop relying on `InMemoryDocumentService` when a real service is provided. Keep `InMemoryDocumentService` for the existing metadata-only route tests; use `DocumentService` only when it is passed into `create_app(document_service=...)`.

Modify `src/api/routes/documents.py`:

- Accept multipart upload when `file` is present.
- Preserve metadata JSON support for older tests by detecting missing file and using existing `create_document(metadata)` path when service lacks `create_upload`.
- Use `get_user_context(request)`.
- Return nested `document` and `job` for upload file path.
- Add `GET /documents`.
- Add `GET /documents/{document_id}`.
- Enqueue a product document task using `document_id` and `job_id`.

Modify `src/api/routes/jobs.py`:

- Use `get_user_context(request)`.
- If job exists but owner does not match, return 403.
- Add `POST /jobs/{job_id}/retry`.

- [ ] **Step 9: Verify document/job tests**

Run:

```bash
pytest tests/test_document_service.py tests/test_api_documents.py tests/test_db_models.py tests/test_db_migrations.py -q
```

Expected: selected tests pass.

- [ ] **Step 10: Commit**

```bash
git add src/db/models.py src/db/migrations/versions/0001_initial_product_schema.py src/services/document_service.py src/api/request_context.py src/api/app.py src/api/routes/documents.py src/api/routes/jobs.py tests/test_document_service.py tests/test_api_documents.py
git commit -m "feat: persist documents and processing jobs"
```

---

## Task 3: Worker Execution for Main Product Path

**Files:**
- Modify: `src/workers/tasks.py`
- Modify: `src/workers/queue.py`
- Modify: `src/services/version_service.py`
- Modify: `src/services/document_service.py`
- Test: `tests/test_workers_product_flow.py`
- Test: `tests/test_version_service.py`

- [ ] **Step 1: Add failing product worker test**

Create `tests/test_workers_product_flow.py`:

```python
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, ContentVersionRecord, Document, DocumentArtifactRecord
from src.services.document_service import DocumentService
from src.storage.backend import LocalStorageBackend
from src.workers.tasks import run_product_document_task


def _session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def test_product_document_task_creates_artifact_outline_and_questions(tmp_path: Path):
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

    run_product_document_task(
        job_id=upload.job.id,
        document_id=upload.document.id,
        owner_id="user-1",
        session_factory=Session,
        storage=service.storage,
    )

    with Session() as session:
        document = session.get(Document, upload.document.id)
        versions = session.query(ContentVersionRecord).order_by(ContentVersionRecord.target_type).all()
        artifacts = session.query(DocumentArtifactRecord).all()

    assert document.status == "ready"
    assert {version.target_type for version in versions} == {"outline", "question_set"}
    assert any("Derivatives" in version.content for version in versions)
    assert artifacts[0].artifact_type == "normalized_document"
```

- [ ] **Step 2: Run product worker test to verify failure**

Run:

```bash
pytest tests/test_workers_product_flow.py -q
```

Expected: fail because `run_product_document_task` and artifact persistence are not implemented.

- [ ] **Step 3: Extend version service with DB helper**

Modify `src/services/version_service.py` so the existing in-memory API remains compatible and add:

```python
from typing import Callable

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.db.models import ContentVersionRecord


def create_persisted_version(
    *,
    session_factory: Callable[[], Session],
    document_id: str,
    target_type: str,
    target_id: str,
    content: str,
    created_by: str,
    change_summary: str,
    content_metadata: dict | None = None,
) -> ContentVersionRecord:
    with session_factory() as session:
        current_max = (
            session.query(func.max(ContentVersionRecord.version))
            .filter(
                ContentVersionRecord.target_type == target_type,
                ContentVersionRecord.target_id == target_id,
            )
            .scalar()
            or 0
        )
        record = ContentVersionRecord(
            id=f"{target_type}:{target_id}:v{current_max + 1}",
            document_id=document_id,
            target_type=target_type,
            target_id=target_id,
            version=current_max + 1,
            content=content,
            created_by=created_by,
            change_summary=change_summary,
            content_metadata=content_metadata or {},
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        session.expunge(record)
        return record
```

- [ ] **Step 4: Implement deterministic product document task**

Modify `src/workers/tasks.py` by adding `run_product_document_task` without removing existing tests for `DocumentProcessingTask`:

```python
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from src.db.models import Document, DocumentArtifactRecord, ProcessingJob
from src.services.version_service import create_persisted_version
from src.storage.backend import StorageBackend


def _utc_now():
    return datetime.now(timezone.utc)


def run_product_document_task(
    *,
    job_id: str,
    document_id: str,
    owner_id: str,
    session_factory,
    storage: StorageBackend,
) -> None:
    with session_factory() as session:
        document = session.get(Document, document_id)
        if document is None or document.owner_id != owner_id:
            raise ValueError("document not found")
        job = document.jobs[0] if document.jobs else None
        if job is None or job.id != job_id:
            raise ValueError("job not found")
        job.status = "running"
        job.progress = 10
        job.started_at = _utc_now()
        document.status = "processing"
        document.updated_at = _utc_now()
        session.commit()

    try:
        source_text = storage.read_bytes(document.storage_uri).decode("utf-8", errors="ignore")
        normalized = _normalize_source_text(source_text)
        outline = _build_outline(normalized)
        questions = _build_questions(normalized)

        with session_factory() as session:
            session.add(
                DocumentArtifactRecord(
                    id=f"artifact:{document_id}:normalized",
                    document_id=document_id,
                    artifact_type="normalized_document",
                    content=normalized,
                    content_metadata={"source": "deterministic_worker"},
                    created_at=_utc_now(),
                )
            )
            session.commit()

        create_persisted_version(
            session_factory=session_factory,
            document_id=document_id,
            target_type="outline",
            target_id=document_id,
            content=outline,
            created_by="worker",
            change_summary="generated outline",
            content_metadata={"generator": "deterministic_worker"},
        )
        create_persisted_version(
            session_factory=session_factory,
            document_id=document_id,
            target_type="question_set",
            target_id=document_id,
            content=questions,
            created_by="worker",
            change_summary="generated question set",
            content_metadata={"generator": "deterministic_worker"},
        )

        with session_factory() as session:
            document = session.get(Document, document_id)
            job = session.get(ProcessingJob, job_id)
            document.status = "ready"
            document.updated_at = _utc_now()
            job.status = "completed"
            job.progress = 100
            job.completed_at = _utc_now()
            job.updated_at = _utc_now()
            session.commit()
    except Exception as exc:
        with session_factory() as session:
            document = session.get(Document, document_id)
            if document is not None:
                document.status = "failed"
                document.updated_at = _utc_now()
            job = session.get(ProcessingJob, job_id)
            if job is not None:
                job.status = "failed"
                job.error_message = str(exc)
                job.updated_at = _utc_now()
                job.completed_at = _utc_now()
            session.commit()
        raise


def _normalize_source_text(source_text: str) -> str:
    text = " ".join(source_text.split())
    return text or "No readable content extracted."


def _build_outline(normalized: str) -> str:
    title = normalized.split(".")[0][:80] or "Study Notes"
    return f"# {title}\n\n## Key Ideas\n- {normalized}"


def _build_questions(normalized: str) -> str:
    return (
        "# Question Set\n\n"
        "1. What is the central idea of this document?\n\n"
        f"Answer: {normalized[:240]}"
    )
```

- [ ] **Step 5: Leave queue serialization unchanged**

Do not modify Redis serialization in `src/workers/queue.py` for MVP-7. Product worker tests invoke `run_product_document_task` directly, and API enqueue behavior can continue using the existing in-process task interface until a later queue hardening phase.

- [ ] **Step 6: Verify worker and version tests**

Run:

```bash
pytest tests/test_workers_product_flow.py tests/test_workers.py tests/test_version_service.py -q
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/workers/tasks.py src/workers/queue.py src/services/version_service.py src/services/document_service.py tests/test_workers_product_flow.py
git commit -m "feat: process documents into persisted study content"
```

---

## Task 4: Export Worker and Version Retrieval Flow

**Files:**
- Modify: `src/services/export_service.py`
- Modify: `src/api/routes/exports.py`
- Modify: `src/api/routes/documents.py`
- Modify: `src/workers/tasks.py`
- Test: `tests/test_export_product_flow.py`
- Test: `tests/test_export_service.py`
- Test: `tests/test_api_documents.py`

- [ ] **Step 1: Add failing export product tests**

Create `tests/test_export_product_flow.py`:

```python
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, ExportJobRecord
from src.services.document_service import DocumentService
from src.services.export_service import ExportFormat, ExportService
from src.services.version_service import create_persisted_version
from src.storage.backend import LocalStorageBackend
from src.workers.tasks import run_export_task


def _setup(tmp_path: Path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    storage = LocalStorageBackend(tmp_path / "objects")
    documents = DocumentService(session_factory=Session, storage=storage)
    upload = documents.create_upload(
        owner_id="user-1",
        filename="notes.pdf",
        content=b"Derivatives",
        content_type="application/pdf",
    )
    version = create_persisted_version(
        session_factory=Session,
        document_id=upload.document.id,
        target_type="outline",
        target_id=upload.document.id,
        content="# Derivatives",
        created_by="worker",
        change_summary="generated outline",
        content_metadata={},
    )
    return Session, storage, upload, version


def test_export_task_renders_markdown_to_storage(tmp_path: Path):
    Session, storage, upload, version = _setup(tmp_path)
    service = ExportService(session_factory=Session, storage=storage)
    job = service.create_export_job(
        owner_id="user-1",
        document_id=upload.document.id,
        version_id=version.id,
        export_format=ExportFormat.MARKDOWN,
    )

    run_export_task(export_job_id=job.id, owner_id="user-1", session_factory=Session, storage=storage)

    with Session() as session:
        export = session.get(ExportJobRecord, job.id)

    assert export.status == "completed"
    assert export.storage_uri.startswith("local://exports/")
    assert storage.read_bytes(export.storage_uri) == b"# Derivatives"
```

- [ ] **Step 2: Add failing API tests for versions and export status**

Append to `tests/test_api_documents.py`:

```python
def test_document_versions_endpoint_returns_owned_versions(tmp_path: Path):
    client, service = _client_with_persisted_service(tmp_path)
    upload = client.post(
        "/api/documents",
        headers={"x-user-id": "user-1"},
        files={"file": ("notes.pdf", b"notes", "application/pdf")},
    ).json()
    from src.services.version_service import create_persisted_version

    create_persisted_version(
        session_factory=service.session_factory,
        document_id=upload["document"]["id"],
        target_type="outline",
        target_id=upload["document"]["id"],
        content="# Notes",
        created_by="test",
        change_summary="test version",
        content_metadata={},
    )

    response = client.get(
        f"/api/documents/{upload['document']['id']}/versions",
        headers={"x-user-id": "user-1"},
    )

    assert response.status_code == 200
    assert response.json()[0]["content"] == "# Notes"


def test_create_export_job_for_owned_document(tmp_path: Path):
    client, service = _client_with_persisted_service(tmp_path)
    upload = client.post(
        "/api/documents",
        headers={"x-user-id": "user-1"},
        files={"file": ("notes.pdf", b"notes", "application/pdf")},
    ).json()
    from src.services.version_service import create_persisted_version

    version = create_persisted_version(
        session_factory=service.session_factory,
        document_id=upload["document"]["id"],
        target_type="outline",
        target_id=upload["document"]["id"],
        content="# Notes",
        created_by="test",
        change_summary="test version",
        content_metadata={},
    )

    response = client.post(
        f"/api/exports/{upload['document']['id']}",
        headers={"x-user-id": "user-1"},
        json={"version_id": version.id, "format": "markdown"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    assert response.json()["version_id"] == version.id
```

- [ ] **Step 3: Run export tests to verify failure**

Run:

```bash
pytest tests/test_export_product_flow.py tests/test_api_documents.py -q
```

Expected: fail because persisted export job creation, version endpoints, and `run_export_task` are missing.

- [ ] **Step 4: Extend export service**

Modify `src/services/export_service.py`:

- Preserve existing dataclass `ExportService().create_export(...)` API for old tests.
- Add constructor accepting optional `session_factory` and `storage`.
- Add `create_export_job(owner_id, document_id, version_id, export_format)`.
- Add `get_export_job(owner_id, export_job_id)`.
- Add `render_export_content(content, export_format)`.

Persist jobs through `ExportJobRecord` with `status="queued"`.

- [ ] **Step 5: Implement export worker task**

Modify `src/workers/tasks.py`:

```python
from src.db.models import ContentVersionRecord, ExportJobRecord


def run_export_task(*, export_job_id: str, owner_id: str, session_factory, storage: StorageBackend) -> None:
    with session_factory() as session:
        export = session.get(ExportJobRecord, export_job_id)
        if export is None or export.owner_id != owner_id:
            raise ValueError("export job not found")
        version = session.get(ContentVersionRecord, export.version_id)
        if version is None:
            raise ValueError("content version not found")
        export.status = "running"
        session.commit()
        content = version.content
        suffix = "json" if export.format == "json" else "md"
        content_type = "application/json" if export.format == "json" else "text/markdown"

    try:
        stored = storage.put_bytes(
            namespace="exports",
            original_filename=f"{export_job_id}.{suffix}",
            content=content.encode("utf-8"),
            content_type=content_type,
        )
        with session_factory() as session:
            export = session.get(ExportJobRecord, export_job_id)
            export.status = "completed"
            export.storage_uri = stored.storage_uri
            export.completed_at = _utc_now()
            session.commit()
    except Exception as exc:
        with session_factory() as session:
            export = session.get(ExportJobRecord, export_job_id)
            if export is not None:
                export.status = "failed"
                export.error_message = str(exc)
                export.completed_at = _utc_now()
                session.commit()
        raise
```

- [ ] **Step 6: Add version and latest content API routes**

Modify `src/api/routes/documents.py`:

- `GET /documents/{document_id}/versions`
- `GET /documents/{document_id}/outline`
- `GET /documents/{document_id}/questions`

Each route must:

- Extract user context.
- Verify document ownership through `DocumentService`.
- Query `ContentVersionRecord` by `document_id`.
- Return 403 for cross-user access.
- Return 404 when owned document exists but no relevant content exists.

- [ ] **Step 7: Update export route**

Modify `src/api/routes/exports.py`:

- Use `request.app.state.export_service` when present.
- Extract `x-user-id`.
- Verify document ownership before creating export.
- Return `id`, `document_id`, `version_id`, `format`, `status`, and `storage_uri`.
- Add `GET /api/exports/{export_id}`.

Modify `src/api/app.py` to set `app.state.export_service` when a real service can be built or injected.

- [ ] **Step 8: Verify export tests**

Run:

```bash
pytest tests/test_export_product_flow.py tests/test_export_service.py tests/test_api_documents.py -q
```

Expected: all selected tests pass.

- [ ] **Step 9: Commit**

```bash
git add src/services/export_service.py src/api/routes/exports.py src/api/routes/documents.py src/api/app.py src/workers/tasks.py tests/test_export_product_flow.py tests/test_api_documents.py
git commit -m "feat: add persisted export workflow"
```

---

## Task 5: Lightweight Permission and Audit Integration

**Files:**
- Modify: `src/security/permissions.py`
- Modify: `src/security/audit.py`
- Modify: `src/api/routes/documents.py`
- Modify: `src/api/routes/jobs.py`
- Modify: `src/api/routes/exports.py`
- Modify: `src/api/routes/feedback.py`
- Modify: `src/api/routes/review.py`
- Modify: `src/api/app.py`
- Test: `tests/test_api_permissions_audit.py`
- Test: `tests/test_security_audit.py`
- Test: `tests/test_quality_feedback.py`

- [ ] **Step 1: Add failing API permission and audit tests**

Create `tests/test_api_permissions_audit.py`:

```python
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.app import create_app
from src.db.models import AuditEventRecord, Base
from src.services.document_service import DocumentService
from src.storage.backend import LocalStorageBackend


def _client(tmp_path: Path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    service = DocumentService(
        session_factory=Session,
        storage=LocalStorageBackend(tmp_path / "objects"),
    )
    return TestClient(create_app(document_service=service)), service, Session


def test_upload_records_audit_event_without_raw_content(tmp_path: Path):
    client, _service, Session = _client(tmp_path)

    response = client.post(
        "/api/documents",
        headers={"x-user-id": "user-1", "x-request-id": "req-1"},
        files={"file": ("notes.pdf", b"secret content", "application/pdf")},
    )

    assert response.status_code == 202
    with Session() as session:
        events = session.query(AuditEventRecord).all()
    assert events[0].actor_id == "user-1"
    assert events[0].action == "document.uploaded"
    assert "secret content" not in str(events[0].event_metadata)


def test_cross_user_document_detail_is_forbidden(tmp_path: Path):
    client, _service, _Session = _client(tmp_path)
    upload = client.post(
        "/api/documents",
        headers={"x-user-id": "user-1"},
        files={"file": ("notes.pdf", b"notes", "application/pdf")},
    ).json()

    response = client.get(
        f"/api/documents/{upload['document']['id']}",
        headers={"x-user-id": "user-2"},
    )

    assert response.status_code == 403
```

- [ ] **Step 2: Run permission/audit tests to verify failure**

Run:

```bash
pytest tests/test_api_permissions_audit.py -q
```

Expected: fail because audit persistence and cross-user resource existence checks are not complete.

- [ ] **Step 3: Extend audit logger with DB persistence**

Modify `src/security/audit.py`:

- Keep existing in-memory `AuditLogger` behavior.
- Add `record_audit_event(session_factory, actor_id, action, resource_type, resource_id, request_id, metadata)`.
- Persist `AuditEventRecord`.
- Reuse the existing sensitive key filter.

Expected function signature:

```python
def record_audit_event(
    *,
    session_factory,
    actor_id: str,
    action: str,
    resource_type: str,
    resource_id: str,
    request_id: str,
    metadata: dict | None = None,
) -> AuditEventRecord:
    ...
```

- [ ] **Step 4: Integrate permission checks and audit events**

Modify API routes:

- Documents:
  - Upload records `document.uploaded`.
  - Detail/list enforce owner.
  - Cross-user detail returns 403 if resource exists with another owner.
- Jobs:
  - Cross-user access returns 403.
  - Retry records `job.retry_requested`.
- Exports:
  - Create records `export.created`.
  - Status enforces owner.
- Feedback:
  - Use `x-user-id` as owner/created_by instead of trusting request body.
  - Record `feedback.created`.
- Review:
  - List only current user's tasks where ownership exists.
  - Decision records `review_task.decided`.

- [ ] **Step 5: Verify permission, audit, and existing security tests**

Run:

```bash
pytest tests/test_api_permissions_audit.py tests/test_security_audit.py tests/test_quality_feedback.py tests/test_api_documents.py -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/security/audit.py src/security/permissions.py src/api/routes/documents.py src/api/routes/jobs.py src/api/routes/exports.py src/api/routes/feedback.py src/api/routes/review.py src/api/app.py tests/test_api_permissions_audit.py
git commit -m "feat: enforce lightweight ownership and audit API actions"
```

---

## Task 6: Frontend Internal-Beta Product Loop

**Files:**
- Create: `frontend/src/api.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/pages/DocumentsPage.tsx`
- Modify: `frontend/src/pages/JobDetailPage.tsx`
- Modify: `frontend/src/pages/OutlinePage.tsx`
- Modify: `frontend/src/pages/QuestionsPage.tsx`
- Create: `frontend/src/pages/ReviewTasksPage.tsx`
- Modify: `frontend/src/styles.css`
- Test: frontend build

- [ ] **Step 1: Add typed frontend API client**

Create `frontend/src/api.ts`:

```typescript
export type JobStatus = "queued" | "running" | "completed" | "succeeded" | "failed" | "cancelled" | "canceled";

export interface ApiDocument {
  id: string;
  owner_id: string;
  title: string;
  source_type: string;
  storage_uri?: string;
  original_filename?: string;
  status: string;
  created_at?: string;
  updated_at?: string;
}

export interface ApiJob {
  id: string;
  document_id: string;
  owner_id: string;
  job_type?: string;
  status: JobStatus;
  progress?: number;
  error_message?: string | null;
}

export interface ContentVersion {
  id: string;
  document_id?: string;
  target_type: string;
  target_id: string;
  version: number;
  content: string;
  created_by: string;
  change_summary: string;
}

export interface ExportJob {
  id: string;
  document_id: string;
  version_id: string;
  format: string;
  status: string;
  storage_uri?: string | null;
  error_message?: string | null;
}

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

function headers(userId: string): HeadersInit {
  return {"x-user-id": userId};
}

export async function listDocuments(userId: string): Promise<ApiDocument[]> {
  const response = await fetch(`${API_BASE}/api/documents`, {headers: headers(userId)});
  if (!response.ok) throw new Error(`Failed to load documents: ${response.status}`);
  return response.json();
}

export async function uploadDocument(userId: string, file: File): Promise<{document: ApiDocument; job: ApiJob}> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${API_BASE}/api/documents`, {
    method: "POST",
    headers: headers(userId),
    body: form,
  });
  if (!response.ok) throw new Error(`Failed to upload document: ${response.status}`);
  return response.json();
}

export async function getJob(userId: string, jobId: string): Promise<ApiJob> {
  const response = await fetch(`${API_BASE}/api/jobs/${jobId}`, {headers: headers(userId)});
  if (!response.ok) throw new Error(`Failed to load job: ${response.status}`);
  return response.json();
}

export async function retryJob(userId: string, jobId: string): Promise<ApiJob> {
  const response = await fetch(`${API_BASE}/api/jobs/${jobId}/retry`, {
    method: "POST",
    headers: headers(userId),
  });
  if (!response.ok) throw new Error(`Failed to retry job: ${response.status}`);
  return response.json();
}

export async function listVersions(userId: string, documentId: string): Promise<ContentVersion[]> {
  const response = await fetch(`${API_BASE}/api/documents/${documentId}/versions`, {headers: headers(userId)});
  if (!response.ok) throw new Error(`Failed to load versions: ${response.status}`);
  return response.json();
}

export async function createExport(userId: string, documentId: string, versionId: string, format: string): Promise<ExportJob> {
  const response = await fetch(`${API_BASE}/api/exports/${documentId}`, {
    method: "POST",
    headers: {...headers(userId), "content-type": "application/json"},
    body: JSON.stringify({version_id: versionId, format}),
  });
  if (!response.ok) throw new Error(`Failed to create export: ${response.status}`);
  return response.json();
}

export async function submitFeedback(userId: string, targetType: string, targetId: string, rating: number, reason: string, comment: string) {
  const response = await fetch(`${API_BASE}/api/feedback`, {
    method: "POST",
    headers: {...headers(userId), "content-type": "application/json"},
    body: JSON.stringify({target_type: targetType, target_id: targetId, rating, reason, comment, created_by: userId}),
  });
  if (!response.ok) throw new Error(`Failed to submit feedback: ${response.status}`);
  return response.json();
}
```

- [ ] **Step 2: Replace static document source with API-driven state**

Modify `frontend/src/App.tsx`:

- Remove the hard-coded `documents` array.
- Add `userId` state defaulting to `demo-user`.
- Load documents with `listDocuments(userId)` in `useEffect`.
- Track selected document id from API results.
- Load versions when selection changes.
- Provide upload handler to `DocumentsPage`.
- Provide retry handler to `JobDetailPage`.
- Provide export and feedback handlers to `OutlinePage` and `QuestionsPage`.

Keep the visual layout utilitarian and do not add a landing page.

- [ ] **Step 3: Update page components to accept API data**

Modify:

- `frontend/src/pages/DocumentsPage.tsx`
- `frontend/src/pages/JobDetailPage.tsx`
- `frontend/src/pages/OutlinePage.tsx`
- `frontend/src/pages/QuestionsPage.tsx`

Required behavior:

- Documents page shows upload input, current user id, documents from API, and status.
- Job detail page shows selected document status and retry button when failed.
- Outline page shows latest `target_type === "outline"` version content.
- Questions page shows latest `target_type === "question_set"` version content.
- Feedback controls post rating/comment through passed callback.
- Export buttons call passed export callback for latest version.

- [ ] **Step 4: Add review tasks page**

Create `frontend/src/pages/ReviewTasksPage.tsx`:

```typescript
export interface ReviewTaskSummary {
  id: string;
  target_type: string;
  target_id: string;
  status: string;
  reason: string;
}

interface ReviewTasksPageProps {
  tasks: ReviewTaskSummary[];
}

function ReviewTasksPage({tasks}: ReviewTasksPageProps) {
  return (
    <section className="panel" aria-labelledby="review-title">
      <h2 id="review-title">Review tasks</h2>
      {tasks.length === 0 ? (
        <p className="muted">No open review tasks.</p>
      ) : (
        <ul className="review-list">
          {tasks.map((task) => (
            <li key={task.id}>
              <strong>{task.target_type}</strong>
              <span>{task.reason}</span>
              <span>{task.status}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export default ReviewTasksPage;
```

- [ ] **Step 5: Update styles for stable product UI**

Modify `frontend/src/styles.css`:

- Keep existing layout pattern.
- Add styles for `.user-switcher`, `.upload-row`, `.error-banner`, `.review-list`, `.version-list`, and `.action-row`.
- Ensure buttons and text do not overflow at mobile widths.

- [ ] **Step 6: Build frontend**

Run:

```bash
npm run build
```

from `frontend/`.

Expected: build succeeds with no TypeScript errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api.ts frontend/src/App.tsx frontend/src/pages frontend/src/styles.css
git commit -m "feat: connect frontend to internal beta product API"
```

---

## Task 7: MVP-7 End-to-End Regression and Reviews

**Files:**
- Create: `tests/test_mvp7_product_loop.py`
- Modify: `README.md`
- Modify: `SPEC.md`

- [ ] **Step 1: Add end-to-end API regression test**

Create `tests/test_mvp7_product_loop.py`:

```python
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.app import create_app
from src.db.models import Base
from src.services.document_service import DocumentService
from src.services.version_service import create_persisted_version
from src.storage.backend import LocalStorageBackend


def test_mvp7_internal_beta_product_loop(tmp_path: Path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    service = DocumentService(
        session_factory=Session,
        storage=LocalStorageBackend(tmp_path / "objects"),
    )
    client = TestClient(create_app(document_service=service))

    upload = client.post(
        "/api/documents",
        headers={"x-user-id": "user-1"},
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
    create_persisted_version(
        session_factory=Session,
        document_id=document_id,
        target_type="question_set",
        target_id=document_id,
        content="# Question Set",
        created_by="test",
        change_summary="test questions",
        content_metadata={},
    )

    assert client.get("/api/documents", headers={"x-user-id": "user-1"}).status_code == 200
    assert client.get(f"/api/documents/{document_id}/outline", headers={"x-user-id": "user-1"}).status_code == 200
    assert client.get(f"/api/documents/{document_id}/questions", headers={"x-user-id": "user-1"}).status_code == 200
    assert client.get(f"/api/documents/{document_id}", headers={"x-user-id": "user-2"}).status_code == 403
```

- [ ] **Step 2: Run full backend suite**

Run:

```bash
pytest -q
```

Expected: all tests pass, with only explicitly reasoned existing xfails.

- [ ] **Step 3: Run frontend build**

Run:

```bash
npm run build
```

from `frontend/`.

Expected: build succeeds.

- [ ] **Step 4: Update README and SPEC implementation status**

Modify `README.md` and `SPEC.md`:

- Add MVP-7 internal-beta product loop to implemented/current phase.
- Document lightweight `x-user-id` testing.
- Document local storage backend and in-process queue boundaries.
- Keep out-of-scope items explicit: real auth, Redis/Celery, S3/MinIO, production deployment, self-evolution implementation.

- [ ] **Step 5: Spec review**

Review against:

- `docs/superpowers/specs/2026-06-16-mvp7-internal-beta-product-loop-design.md`
- This implementation plan

Checklist:

- StorageBackend exists and local backend works.
- Upload creates persisted document and job records.
- Worker can create normalized artifact, outline version, and question version.
- Version/outline/questions endpoints exist.
- Export job can be created and completed.
- Owner isolation is tested for documents, jobs, versions, and exports.
- Audit events are persisted without sensitive content.
- Frontend uses API-driven state and supports upload/status/content/feedback/export path.

If any item is missing, fix before quality review.

- [ ] **Step 6: Quality review**

Review code quality:

- No route should trust `created_by` or `owner_id` from request JSON when `x-user-id` is available.
- No API/worker logic should construct local filesystem paths directly; use storage URI/backend.
- No full raw document content should be stored in audit metadata.
- Job failures should persist a safe error message.
- DB migration and ORM fields must match.
- Tests should avoid external services and model calls.

If any issue is found, fix and rerun relevant tests.

- [ ] **Step 7: Commit**

```bash
git add README.md SPEC.md tests/test_mvp7_product_loop.py
git commit -m "test: verify MVP-7 internal beta product loop"
```

## Final Verification

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

Expected: frontend build succeeds.

## Execution Notes

- Use a new implementation branch or worktree before executing this plan.
- Follow the project rule from `AGENTS.md`: every implementation task requires a spec review and a quality review before moving to the next task.
- Prefer subagent-driven execution, one task at a time. If a subagent stalls repeatedly, record the stalled task and continue manually or with a different subagent, but keep the two review gates.
