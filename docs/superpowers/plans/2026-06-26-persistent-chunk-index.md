# Persistent Chunk Index Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Phase 2 persistent Study Agent document chunks so ready documents are indexed once during processing, queried from stable persisted evidence units, and recoverable through an owned reindex API.

**Architecture:** Add an additive `document_chunks` ORM and migration layer, then isolate all indexing behavior in a focused `StudyDocumentIndexService`. Wire the worker, runtime, and document API through that service while preserving the current query-time chunking path as an observable transition fallback.

**Tech Stack:** FastAPI, SQLAlchemy ORM, Alembic, SQLite test database, PostgreSQL-compatible migrations, pytest, Vite/TypeScript frontend type checks.

---

## Scope And Product Boundaries

This plan implements the Phase 2 backend product slice from `docs/superpowers/specs/2026-06-26-persistent-chunk-index-design.md`.

It includes:

- Persistent `DocumentChunkRecord` ORM mapping for the existing `document_chunks` table.
- Additive migration `0003_persistent_document_chunks.py` that reconciles legacy chunk columns with product fields.
- `StudyDocumentIndexService` for indexing, status, reindexing, and persisted chunk loading.
- Worker integration after `normalized_document` artifact creation.
- Runtime preference for persisted chunks with explicit fallback metadata.
- `POST /api/documents/{document_id}/study-index/reindex`.
- Compact `study_index` field in document list/detail payloads.
- Focused tests and final verification.

It excludes:

- Real embedding provider integration.
- pgvector similarity search in Study Agent runtime.
- Graph RAG or Agentic RAG routing threshold tuning.
- Frontend status panel or reindex button.
- Bulk historical reindex jobs.

## File Structure

- Modify `src/db/models.py`: add `DocumentChunkRecord`, `Document.chunks`, and timestamp-compatible fields.
- Modify `src/db/__init__.py`: export `DocumentChunkRecord`.
- Create `src/db/migrations/versions/0003_persistent_document_chunks.py`: add missing product chunk columns, constraints, and indexes without replacing existing data.
- Create `src/services/study_agent_index.py`: own all persistent indexing, status, and persisted chunk loading.
- Modify `src/services/study_agent_runtime.py`: inject/use `StudyDocumentIndexService`, prefer persisted chunks, and record fallback reason in returned audit metadata.
- Modify `src/workers/tasks.py`: index the new `normalized_document` artifact before marking the document ready.
- Modify `src/api/routes/documents.py`: serialize `study_index` and add the owned reindex endpoint.
- Modify `frontend/src/api.ts`: add optional document `study_index` type only.
- Modify `tests/test_db_models.py`: model creation and metadata mapping coverage for `DocumentChunkRecord`.
- Modify `tests/test_db_migrations.py`: Alembic schema compatibility for chunk product columns and indexes.
- Modify `tests/test_study_agent_documents.py`: focused service tests for persisted chunks and status.
- Modify `tests/test_study_agent_runtime.py`: runtime persisted-first and fallback tests.
- Modify `tests/test_workers_product_flow.py`: worker creates chunks and remains idempotent on reprocessing.
- Modify `tests/test_study_agent_api.py`: reindex endpoint and document payload status tests.
- Optional docs update in `README.md` or `SPEC.md` only if those files already summarize Study Agent document indexing.

## Shared Review Rule

After each implementation task below, run both reviews before moving to the next task:

- **Spec review:** compare the task diff against the spec acceptance criteria and the task objective. Confirm no requirement was skipped and no out-of-scope frontend, embedding, or Graph RAG work slipped in.
- **Quality review:** inspect naming, owner scoping, idempotency, transaction boundaries, test clarity, and privacy. Confirm no raw chunk content, query text, source snippets, tokens, passwords, or secrets are written to audit metadata.

Record the review result in the task completion note or commit message body when useful.

### Task 1: Model And Migration Compatibility

**Files:**
- Modify: `src/db/models.py`
- Modify: `src/db/__init__.py`
- Create: `src/db/migrations/versions/0003_persistent_document_chunks.py`
- Modify: `tests/test_db_models.py`
- Modify: `tests/test_db_migrations.py`

- [ ] **Step 1: Write the failing model test**

Add this import in `tests/test_db_models.py`:

```python
from src.db import DocumentChunkRecord
```

Extend `test_mvp7_product_records_create_and_preserve_metadata_columns` with a persisted chunk record:

```python
        chunk = DocumentChunkRecord(
            id="chunk-1",
            document=document,
            owner_id="user-1",
            artifact_id="artifact-1",
            chunk_index=0,
            chunk_count=1,
            source="document:doc-1:chunk:0",
            content="normalized",
            chunk_metadata={
                "owner_id": "user-1",
                "document_id": "doc-1",
                "document_title": "Lecture Notes",
                "artifact_id": "artifact-1",
                "artifact_type": "normalized_document",
                "chunk_index": 0,
                "chunk_count": 1,
                "source_kind": "persisted_document_chunk",
            },
            content_hash="hash-normalized",
        )
```

Add `chunk` to the existing `session.add_all([...])` call and add these assertions after reload:

```python
        chunk = session.get(DocumentChunkRecord, "chunk-1")

        assert chunk is not None
        assert chunk.owner_id == "user-1"
        assert chunk.artifact_id == "artifact-1"
        assert chunk.chunk_metadata["source_kind"] == "persisted_document_chunk"
        assert chunk.document.title == "Lecture Notes"
        assert chunk.created_at is not None
        assert chunk.updated_at is not None
```

- [ ] **Step 2: Write the failing migration test**

In `tests/test_db_migrations.py`, extend `test_alembic_upgrade_creates_orm_compatible_sqlite_schema` after `chunk_columns` is defined:

```python
    assert {
        "id",
        "owner_id",
        "document_id",
        "artifact_id",
        "chunk_index",
        "chunk_count",
        "source",
        "content",
        "metadata",
        "content_hash",
        "created_at",
        "updated_at",
        "section_id",
        "page_number",
        "embedding",
    }.issubset(chunk_columns)
    chunk_indexes = {index["name"] for index in inspector.get_indexes("document_chunks")}
    assert "ix_document_chunks_owner_document" in chunk_indexes
    assert "ix_document_chunks_document_artifact" in chunk_indexes
    chunk_unique_constraints = {
        constraint["name"] for constraint in inspector.get_unique_constraints("document_chunks")
    }
    assert "uq_document_chunks_artifact_index" in chunk_unique_constraints
```

- [ ] **Step 3: Run tests to verify they fail for missing model and migration fields**

Run:

```bash
pytest tests/test_db_models.py::test_mvp7_product_records_create_and_preserve_metadata_columns tests/test_db_migrations.py::test_alembic_upgrade_creates_orm_compatible_sqlite_schema -q
```

Expected: FAIL because `DocumentChunkRecord` is not exported and the migration lacks product chunk columns.

- [ ] **Step 4: Add the ORM model and export**

In `src/db/models.py`, add `Index` to the SQLAlchemy imports:

```python
    Index,
```

Add this relationship to `Document` next to `artifacts`:

```python
    chunks: Mapped[List["DocumentChunkRecord"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
```

Add this model after `DocumentArtifactRecord`:

```python
class DocumentChunkRecord(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("artifact_id", "chunk_index", name="uq_document_chunks_artifact_index"),
        Index("ix_document_chunks_owner_document", "owner_id", "document_id"),
        Index("ix_document_chunks_document_artifact", "document_id", "artifact_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    artifact_id: Mapped[str] = mapped_column(
        ForeignKey("document_artifacts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    section_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("parsed_sections.id", ondelete="SET NULL"), nullable=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[Optional[int]] = mapped_column(Integer)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    chunk_metadata: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    embedding: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    document: Mapped[Document] = relationship(back_populates="chunks")
    artifact: Mapped[DocumentArtifactRecord] = relationship()
```

The `embedding` ORM type remains `Text` for SQLite test compatibility in `Base.metadata.create_all`; Alembic keeps the existing `Vector(dim=768)` column from the historical migration for upgraded databases.

In `src/db/__init__.py`, import and export `DocumentChunkRecord`:

```python
    DocumentChunkRecord,
```

and add it to `__all__`.

- [ ] **Step 5: Create the additive Alembic migration**

Create `src/db/migrations/versions/0003_persistent_document_chunks.py` with this structure:

```python
"""Add persistent Study Agent document chunk fields.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-26
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "document_chunks" not in inspector.get_table_names():
        op.create_table(
            "document_chunks",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("owner_id", sa.String(length=64), nullable=False),
            sa.Column("document_id", sa.String(length=64), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
            sa.Column("artifact_id", sa.String(length=64), sa.ForeignKey("document_artifacts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("section_id", sa.String(length=64), sa.ForeignKey("parsed_sections.id", ondelete="SET NULL"), nullable=True),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("page_number", sa.Integer(), nullable=True),
            sa.Column("chunk_index", sa.Integer(), nullable=False),
            sa.Column("chunk_count", sa.Integer(), nullable=False),
            sa.Column("source", sa.String(length=255), nullable=False),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("content_hash", sa.String(length=128), nullable=False),
            sa.Column("embedding", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
    else:
        existing_columns = {column["name"] for column in inspector.get_columns("document_chunks")}
        with op.batch_alter_table("document_chunks") as batch_op:
            if "owner_id" not in existing_columns:
                batch_op.add_column(sa.Column("owner_id", sa.String(length=64), nullable=True))
            if "artifact_id" not in existing_columns:
                batch_op.add_column(sa.Column("artifact_id", sa.String(length=64), nullable=True))
            if "chunk_count" not in existing_columns:
                batch_op.add_column(sa.Column("chunk_count", sa.Integer(), nullable=True))
            if "source" not in existing_columns:
                batch_op.add_column(sa.Column("source", sa.String(length=255), nullable=True))
            if "metadata" not in existing_columns:
                batch_op.add_column(sa.Column("metadata", sa.JSON(), nullable=True))
            if "content_hash" not in existing_columns:
                batch_op.add_column(sa.Column("content_hash", sa.String(length=128), nullable=True))
            if "created_at" not in existing_columns:
                batch_op.add_column(sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
            if "updated_at" not in existing_columns:
                batch_op.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))

    _create_index_if_missing("ix_document_chunks_owner_id", "document_chunks", ["owner_id"])
    _create_index_if_missing("ix_document_chunks_document_id", "document_chunks", ["document_id"])
    _create_index_if_missing("ix_document_chunks_artifact_id", "document_chunks", ["artifact_id"])
    _create_index_if_missing("ix_document_chunks_content_hash", "document_chunks", ["content_hash"])
    _create_index_if_missing("ix_document_chunks_owner_document", "document_chunks", ["owner_id", "document_id"])
    _create_index_if_missing("ix_document_chunks_document_artifact", "document_chunks", ["document_id", "artifact_id"])
    _create_unique_constraint_if_missing(
        "uq_document_chunks_artifact_index",
        "document_chunks",
        ["artifact_id", "chunk_index"],
    )


def downgrade() -> None:
    _drop_constraint_if_exists("uq_document_chunks_artifact_index", "document_chunks")
    for index_name in [
        "ix_document_chunks_document_artifact",
        "ix_document_chunks_owner_document",
        "ix_document_chunks_content_hash",
        "ix_document_chunks_artifact_id",
        "ix_document_chunks_document_id",
        "ix_document_chunks_owner_id",
    ]:
        _drop_index_if_exists(index_name, "document_chunks")

    removable_columns = [
        "updated_at",
        "created_at",
        "content_hash",
        "metadata",
        "source",
        "chunk_count",
        "artifact_id",
        "owner_id",
    ]
    inspector = sa.inspect(op.get_bind())
    existing_columns = {column["name"] for column in inspector.get_columns("document_chunks")}
    with op.batch_alter_table("document_chunks") as batch_op:
        for column_name in removable_columns:
            if column_name in existing_columns:
                batch_op.drop_column(column_name)


def _create_index_if_missing(name: str, table_name: str, columns: list[str]) -> None:
    inspector = sa.inspect(op.get_bind())
    if name not in {index["name"] for index in inspector.get_indexes(table_name)}:
        op.create_index(name, table_name, columns)


def _drop_index_if_exists(name: str, table_name: str) -> None:
    inspector = sa.inspect(op.get_bind())
    if name in {index["name"] for index in inspector.get_indexes(table_name)}:
        op.drop_index(name, table_name=table_name)


def _create_unique_constraint_if_missing(name: str, table_name: str, columns: list[str]) -> None:
    inspector = sa.inspect(op.get_bind())
    if name not in {constraint["name"] for constraint in inspector.get_unique_constraints(table_name)}:
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.create_unique_constraint(name, columns)


def _drop_constraint_if_exists(name: str, table_name: str) -> None:
    inspector = sa.inspect(op.get_bind())
    if name in {constraint["name"] for constraint in inspector.get_unique_constraints(table_name)}:
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_constraint(name, type_="unique")
```

After creating the migration, check whether SQLite can create a unique constraint on the upgraded table. If batch mode fails because nullable legacy rows contain duplicate `(artifact_id, chunk_index)`, update the migration to backfill legacy rows before creating the constraint:

```python
    op.execute(
        """
        UPDATE document_chunks
        SET
            owner_id = COALESCE(owner_id, 'legacy-owner'),
            artifact_id = COALESCE(artifact_id, 'legacy-artifact:' || document_id),
            chunk_count = COALESCE(chunk_count, 1),
            source = COALESCE(source, 'document:' || document_id || ':chunk:' || chunk_index),
            metadata = COALESCE(metadata, '{}'),
            content_hash = COALESCE(content_hash, 'legacy:' || id),
            created_at = COALESCE(created_at, CURRENT_TIMESTAMP),
            updated_at = COALESCE(updated_at, CURRENT_TIMESTAMP)
        """
    )
```

- [ ] **Step 6: Run model and migration tests**

Run:

```bash
pytest tests/test_db_models.py::test_mvp7_product_records_create_and_preserve_metadata_columns tests/test_db_migrations.py::test_alembic_upgrade_creates_orm_compatible_sqlite_schema -q
```

Expected: PASS.

- [ ] **Step 7: Run the two reviews for Task 1**

Spec review checklist:

```text
- Required fields exist on DocumentChunkRecord.
- Existing-compatible fields section_id, page_number, and embedding remain available.
- Migration is additive and does not delete the historical table.
- Indexes and unique artifact/chunk constraint exist.
```

Quality review checklist:

```text
- No SQLAlchemy reserved attribute named metadata is used; ORM attribute is chunk_metadata.
- Owner and artifact columns are indexed.
- Base.metadata.create_all works for SQLite tests.
- Downgrade does not drop unrelated historical columns.
```

- [ ] **Step 8: Commit Task 1**

Run:

```bash
git add src/db/models.py src/db/__init__.py src/db/migrations/versions/0003_persistent_document_chunks.py tests/test_db_models.py tests/test_db_migrations.py
git commit -m "feat: model persistent document chunks"
```

### Task 2: Persistent Index Service

**Files:**
- Create: `src/services/study_agent_index.py`
- Modify: `tests/test_study_agent_documents.py`

- [ ] **Step 1: Write failing service tests**

Add these imports in `tests/test_study_agent_documents.py`:

```python
from src.db.models import DocumentChunkRecord
from src.services.study_agent_index import StudyDocumentIndexService
```

Add this test for persisted metadata:

```python
def test_index_service_persists_chunks_with_required_metadata():
    Session = _session_factory()
    _insert_document(Session, document_id="doc-1", owner_id="user-1")
    _insert_artifact(
        Session,
        artifact_id="artifact-1",
        document_id="doc-1",
        content="Derivatives measure instantaneous rate of change. Gradients extend derivatives.",
        created_at=datetime.now(timezone.utc),
    )
    service = StudyDocumentIndexService(
        session_factory=Session,
        chunker=StudyDocumentChunker(max_chars=48, overlap_chars=8),
    )

    status = service.index_document(owner_id="user-1", document_id="doc-1")

    assert status.document_id == "doc-1"
    assert status.status == "indexed"
    assert status.artifact_id == "artifact-1"
    assert status.chunk_count >= 2
    assert status.indexed_at is not None
    assert status.fallback_reason is None
    with Session() as session:
        chunks = (
            session.query(DocumentChunkRecord)
            .filter(DocumentChunkRecord.document_id == "doc-1")
            .order_by(DocumentChunkRecord.chunk_index)
            .all()
        )
    assert len(chunks) == status.chunk_count
    assert chunks[0].owner_id == "user-1"
    assert chunks[0].artifact_id == "artifact-1"
    assert chunks[0].source == "document:doc-1:chunk:0"
    assert chunks[0].chunk_metadata["source_kind"] == "persisted_document_chunk"
    assert chunks[0].chunk_metadata["document_title"] == "Calculus Notes"
```

Add this idempotency test:

```python
def test_index_service_reindex_is_idempotent_for_same_artifact():
    Session = _session_factory()
    _insert_document(Session, document_id="doc-1", owner_id="user-1")
    _insert_artifact(
        Session,
        artifact_id="artifact-1",
        document_id="doc-1",
        content="Derivatives measure instantaneous rate of change.",
        created_at=datetime.now(timezone.utc),
    )
    service = StudyDocumentIndexService(session_factory=Session)

    first = service.index_document(owner_id="user-1", document_id="doc-1")
    second = service.index_document(owner_id="user-1", document_id="doc-1")

    assert first.status == "indexed"
    assert second.status == "indexed"
    with Session() as session:
        assert session.query(DocumentChunkRecord).count() == first.chunk_count
```

Add this status test:

```python
def test_index_service_status_reports_missing_index_and_stale_index():
    Session = _session_factory()
    _insert_document(Session, document_id="doc-1", owner_id="user-1")
    old_time = datetime.now(timezone.utc) - timedelta(days=1)
    new_time = datetime.now(timezone.utc)
    _insert_artifact(
        Session,
        artifact_id="artifact-old",
        document_id="doc-1",
        content="Old derivative notes",
        created_at=old_time,
    )
    service = StudyDocumentIndexService(session_factory=Session)

    missing = service.status(owner_id="user-1", document_id="doc-1")
    assert missing.status == "fallback_available"
    assert missing.chunk_count == 0
    assert missing.fallback_reason == "persisted_chunks_missing"

    service.index_document(owner_id="user-1", document_id="doc-1")
    _insert_artifact(
        Session,
        artifact_id="artifact-new",
        document_id="doc-1",
        content="New derivative notes",
        created_at=new_time,
    )

    stale = service.status(owner_id="user-1", document_id="doc-1")
    assert stale.status == "stale"
    assert stale.artifact_id == "artifact-old"
    assert stale.fallback_reason == "latest_artifact_not_indexed"
```

Add this owner isolation test:

```python
def test_index_service_load_chunks_filters_owner_and_requested_documents():
    Session = _session_factory()
    _insert_document(Session, document_id="doc-1", owner_id="user-1")
    _insert_document(Session, document_id="doc-2", owner_id="user-2")
    now = datetime.now(timezone.utc)
    _insert_artifact(Session, artifact_id="artifact-1", document_id="doc-1", content="Owned notes", created_at=now)
    _insert_artifact(Session, artifact_id="artifact-2", document_id="doc-2", content="Private notes", created_at=now)
    service = StudyDocumentIndexService(session_factory=Session)
    service.index_document(owner_id="user-1", document_id="doc-1")
    service.index_document(owner_id="user-2", document_id="doc-2")

    chunks = service.load_chunks(owner_id="user-1", document_ids=("doc-1", "doc-2"))

    assert {chunk["metadata"]["document_id"] for chunk in chunks} == {"doc-1"}
    assert all(chunk["metadata"]["owner_id"] == "user-1" for chunk in chunks)
```

- [ ] **Step 2: Run tests to verify the service module is missing**

Run:

```bash
pytest tests/test_study_agent_documents.py::test_index_service_persists_chunks_with_required_metadata tests/test_study_agent_documents.py::test_index_service_reindex_is_idempotent_for_same_artifact tests/test_study_agent_documents.py::test_index_service_status_reports_missing_index_and_stale_index tests/test_study_agent_documents.py::test_index_service_load_chunks_filters_owner_and_requested_documents -q
```

Expected: FAIL because `src.services.study_agent_index` does not exist.

- [ ] **Step 3: Create the service dataclass and helpers**

Create `src/services/study_agent_index.py` with these public types and helpers:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
from typing import Any, Sequence

from src.db.models import Document, DocumentArtifactRecord, DocumentChunkRecord
from src.services.study_agent_documents import (
    StudyAgentDocumentError,
    StudyDocumentChunker,
    StudyDocumentEvidence,
)


@dataclass(frozen=True)
class DocumentIndexStatus:
    document_id: str
    status: str
    artifact_id: str | None
    chunk_count: int
    indexed_at: datetime | None
    fallback_reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "status": self.status,
            "artifact_id": self.artifact_id,
            "chunk_count": self.chunk_count,
            "indexed_at": self.indexed_at.isoformat() if self.indexed_at else None,
            "fallback_reason": self.fallback_reason,
        }


def _content_hash(*, content: str, source: str, metadata: dict[str, Any]) -> str:
    digest = hashlib.sha256()
    digest.update(content.encode("utf-8"))
    digest.update(b"\0")
    digest.update(source.encode("utf-8"))
    digest.update(b"\0")
    digest.update(str(metadata.get("artifact_id", "")).encode("utf-8"))
    digest.update(b"\0")
    digest.update(str(metadata.get("chunk_index", "")).encode("utf-8"))
    return digest.hexdigest()


def _chunk_id(*, document_id: str, artifact_id: str, chunk_index: int) -> str:
    digest = hashlib.sha256(f"{document_id}:{artifact_id}:{chunk_index}".encode("utf-8"))
    return f"chunk:{digest.hexdigest()[:56]}"


def _merge_persisted_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    merged = dict(metadata)
    merged["source_kind"] = "persisted_document_chunk"
    return merged
```

- [ ] **Step 4: Implement document loading and indexing methods**

In the same file, add `StudyDocumentIndexService`:

```python
class StudyDocumentIndexService:
    def __init__(
        self,
        *,
        session_factory,
        chunker: StudyDocumentChunker | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.chunker = chunker or StudyDocumentChunker()

    def index_document(self, *, owner_id: str, document_id: str) -> DocumentIndexStatus:
        with self.session_factory() as session:
            document = self._load_owned_document(
                session,
                owner_id=owner_id,
                document_id=document_id,
                require_ready=True,
            )
            artifact = self._latest_normalized_artifact(session, document_id=document.id)
            if artifact is None or not artifact.content.strip():
                raise StudyAgentDocumentError(
                    status_code=422,
                    code="document_evidence_missing",
                    detail="Processed document evidence is unavailable.",
                )
            artifact_id = artifact.id
        return self.index_artifact(owner_id=owner_id, document_id=document_id, artifact_id=artifact_id)

    def index_artifact(
        self,
        *,
        owner_id: str,
        document_id: str,
        artifact_id: str,
        require_ready: bool = True,
    ) -> DocumentIndexStatus:
        normalized_owner_id = str(owner_id or "").strip()
        with self.session_factory() as session:
            document = self._load_owned_document(
                session,
                owner_id=normalized_owner_id,
                document_id=document_id,
                require_ready=require_ready,
            )
            artifact = session.get(DocumentArtifactRecord, artifact_id)
            if (
                artifact is None
                or artifact.document_id != document.id
                or artifact.artifact_type != "normalized_document"
                or not artifact.content.strip()
            ):
                raise StudyAgentDocumentError(
                    status_code=422,
                    code="document_evidence_missing",
                    detail="Processed document evidence is unavailable.",
                )

            evidence = StudyDocumentEvidence(
                document_id=document.id,
                document_title=document.title,
                owner_id=document.owner_id,
                artifact_id=artifact.id,
                artifact_type=artifact.artifact_type,
                content=artifact.content,
                artifact_metadata=dict(artifact.artifact_metadata or {}),
                created_at=artifact.created_at,
            )
            raw_chunks = self.chunker.chunk((evidence,))
            if not raw_chunks:
                raise StudyAgentDocumentError(
                    status_code=422,
                    code="document_evidence_missing",
                    detail="Processed document evidence is unavailable.",
                )

            session.query(DocumentChunkRecord).filter(
                DocumentChunkRecord.owner_id == normalized_owner_id,
                DocumentChunkRecord.document_id == document.id,
                DocumentChunkRecord.artifact_id != artifact.id,
            ).delete(synchronize_session=False)
            session.query(DocumentChunkRecord).filter(
                DocumentChunkRecord.owner_id == normalized_owner_id,
                DocumentChunkRecord.document_id == document.id,
                DocumentChunkRecord.artifact_id == artifact.id,
            ).delete(synchronize_session=False)

            for index, chunk in enumerate(raw_chunks):
                metadata = _merge_persisted_metadata(dict(chunk["metadata"]))
                session.add(
                    DocumentChunkRecord(
                        id=_chunk_id(
                            document_id=document.id,
                            artifact_id=artifact.id,
                            chunk_index=index,
                        ),
                        owner_id=normalized_owner_id,
                        document_id=document.id,
                        artifact_id=artifact.id,
                        chunk_index=index,
                        chunk_count=len(raw_chunks),
                        source=chunk["source"],
                        content=chunk["content"],
                        chunk_metadata=metadata,
                        content_hash=_content_hash(
                            content=chunk["content"],
                            source=chunk["source"],
                            metadata=metadata,
                        ),
                    )
                )
            session.commit()
            indexed_at = max(record.updated_at for record in session.query(DocumentChunkRecord).filter(DocumentChunkRecord.artifact_id == artifact.id).all())

        return DocumentIndexStatus(
            document_id=document_id,
            status="indexed",
            artifact_id=artifact_id,
            chunk_count=len(raw_chunks),
            indexed_at=indexed_at,
            fallback_reason=None,
        )
```

- [ ] **Step 5: Implement status and persisted chunk loading**

Add these methods to `StudyDocumentIndexService`:

```python
    def status(self, *, owner_id: str, document_id: str) -> DocumentIndexStatus:
        with self.session_factory() as session:
            document = self._load_owned_document(
                session,
                owner_id=owner_id,
                document_id=document_id,
                require_ready=True,
            )
            latest_artifact = self._latest_normalized_artifact(session, document_id=document.id)
            chunks = (
                session.query(DocumentChunkRecord)
                .filter(
                    DocumentChunkRecord.owner_id == owner_id,
                    DocumentChunkRecord.document_id == document.id,
                )
                .order_by(DocumentChunkRecord.updated_at.desc())
                .all()
            )
            if not chunks:
                if latest_artifact is not None and latest_artifact.content.strip():
                    return DocumentIndexStatus(
                        document_id=document.id,
                        status="fallback_available",
                        artifact_id=latest_artifact.id,
                        chunk_count=0,
                        indexed_at=None,
                        fallback_reason="persisted_chunks_missing",
                    )
                return DocumentIndexStatus(
                    document_id=document.id,
                    status="missing",
                    artifact_id=None,
                    chunk_count=0,
                    indexed_at=None,
                    fallback_reason="normalized_artifact_missing",
                )
            artifact_ids = {chunk.artifact_id for chunk in chunks}
            active_artifact_id = chunks[0].artifact_id
            indexed_at = max(chunk.updated_at for chunk in chunks if chunk.updated_at is not None)
            if latest_artifact is not None and latest_artifact.id not in artifact_ids:
                return DocumentIndexStatus(
                    document_id=document.id,
                    status="stale",
                    artifact_id=active_artifact_id,
                    chunk_count=len(chunks),
                    indexed_at=indexed_at,
                    fallback_reason="latest_artifact_not_indexed",
                )
            return DocumentIndexStatus(
                document_id=document.id,
                status="indexed",
                artifact_id=active_artifact_id,
                chunk_count=len(chunks),
                indexed_at=indexed_at,
                fallback_reason=None,
            )

    def load_chunks(self, *, owner_id: str, document_ids: Sequence[str]) -> tuple[dict[str, Any], ...]:
        requested_ids = tuple(dict.fromkeys(str(value).strip() for value in document_ids if str(value).strip()))
        if not requested_ids:
            return ()
        with self.session_factory() as session:
            rows = (
                session.query(DocumentChunkRecord)
                .filter(
                    DocumentChunkRecord.owner_id == owner_id,
                    DocumentChunkRecord.document_id.in_(requested_ids),
                )
                .order_by(DocumentChunkRecord.document_id.asc(), DocumentChunkRecord.chunk_index.asc())
                .all()
            )
            return tuple(
                {
                    "content": row.content,
                    "source": row.source,
                    "metadata": dict(row.chunk_metadata or {}),
                }
                for row in rows
            )

    def _load_owned_document(
        self,
        session,
        *,
        owner_id: str,
        document_id: str,
        require_ready: bool = True,
    ) -> Document:
        normalized_owner_id = str(owner_id or "").strip()
        if not normalized_owner_id:
            raise StudyAgentDocumentError(
                status_code=422,
                code="authentication_required",
                detail="Study Agent requires an authenticated user.",
            )
        document = (
            session.query(Document)
            .filter(Document.owner_id == normalized_owner_id, Document.id == document_id)
            .first()
        )
        if document is None:
            raise StudyAgentDocumentError(
                status_code=404,
                code="document_unavailable",
                detail="Selected document is unavailable to the current user.",
            )
        if require_ready and document.status != "ready":
            raise StudyAgentDocumentError(
                status_code=422,
                code="document_not_ready",
                detail=f"Document {document.id} must finish processing before Study Agent can use it.",
            )
        return document

    def _latest_normalized_artifact(self, session, *, document_id: str) -> DocumentArtifactRecord | None:
        return (
            session.query(DocumentArtifactRecord)
            .filter(
                DocumentArtifactRecord.document_id == document_id,
                DocumentArtifactRecord.artifact_type == "normalized_document",
            )
            .order_by(DocumentArtifactRecord.created_at.desc())
            .first()
        )
```

If a test exposes `DetachedInstanceError` from returning values after a session closes, compute all return values before leaving the `with` block.

- [ ] **Step 6: Run service tests**

Run:

```bash
pytest tests/test_study_agent_documents.py -q
```

Expected: PASS.

- [ ] **Step 7: Run the two reviews for Task 2**

Spec review checklist:

```text
- Service loads only owned ready documents.
- Service indexes latest non-empty normalized_document artifacts.
- Service returns indexed, missing, stale, and fallback_available statuses.
- Reindexing the same artifact leaves one active chunk set.
- load_chunks filters by owner_id and requested document_ids.
```

Quality review checklist:

```text
- All DB writes happen inside one transaction per index operation.
- No raw chunk content enters status dictionaries or audit-shaped payloads.
- Metadata source_kind changes to persisted_document_chunk only for persisted chunks.
- Public methods raise StudyAgentDocumentError with product-compatible codes.
```

- [ ] **Step 8: Commit Task 2**

Run:

```bash
git add src/services/study_agent_index.py tests/test_study_agent_documents.py
git commit -m "feat: add study document index service"
```

### Task 3: Runtime Prefers Persisted Chunks

**Files:**
- Modify: `src/services/study_agent_runtime.py`
- Modify: `tests/test_study_agent_runtime.py`

- [ ] **Step 1: Write the failing runtime persisted-first test**

Add imports in `tests/test_study_agent_runtime.py`:

```python
from src.db.models import DocumentChunkRecord
from src.services.study_agent_index import StudyDocumentIndexService
```

Add this helper:

```python
def _insert_persisted_chunk(
    Session,
    *,
    document_id: str = "doc-study",
    owner_id: str = "user-1",
    artifact_id: str = "artifact-doc-study",
    content: str = "Persisted derivatives evidence.",
) -> None:
    with Session() as session:
        session.add(
            DocumentChunkRecord(
                id=f"chunk-{document_id}",
                owner_id=owner_id,
                document_id=document_id,
                artifact_id=artifact_id,
                chunk_index=0,
                chunk_count=1,
                source=f"document:{document_id}:chunk:0",
                content=content,
                chunk_metadata={
                    "owner_id": owner_id,
                    "document_id": document_id,
                    "document_title": "Calculus Notes",
                    "artifact_id": artifact_id,
                    "artifact_type": "normalized_document",
                    "chunk_index": 0,
                    "chunk_count": 1,
                    "source_kind": "persisted_document_chunk",
                },
                content_hash=f"hash-{document_id}",
            )
        )
        session.commit()
```

Add this test:

```python
@pytest.mark.asyncio
async def test_runtime_prefers_persisted_chunks_over_query_time_chunking():
    Session = _session_factory()
    _insert_ready_document_with_artifact(
        Session,
        content="Artifact text that should not appear when persisted chunks exist.",
    )
    _insert_persisted_chunk(Session)
    runtime = StudyAgentRuntimeService(
        session_factory=Session,
        chunker=StudyDocumentChunker(max_chars=200, overlap_chars=20),
    )

    result = await runtime.run(
        {
            "query": "What do derivatives measure?",
            "target": "answer",
            "document_ids": ["doc-study"],
            "authenticated_user_id": "user-1",
            "request_id": "req-runtime-persisted",
        }
    )

    assert result.evidence.sources == ("document:doc-study:chunk:0",)
    assert result.evidence.chunks[0].content == "Persisted derivatives evidence."
    assert result.evidence.chunks[0].metadata["source_kind"] == "persisted_document_chunk"
    assert result.audit_metadata["chunk_source"] == "persisted"
    assert result.audit_metadata["fallback_reason"] is None
```

Add this fallback observability test:

```python
@pytest.mark.asyncio
async def test_runtime_fallback_to_artifact_chunking_is_observable():
    Session = _session_factory()
    _insert_ready_document_with_artifact(Session)
    runtime = StudyAgentRuntimeService(
        session_factory=Session,
        chunker=StudyDocumentChunker(max_chars=200, overlap_chars=20),
    )

    result = await runtime.run(
        {
            "query": "What do derivatives measure?",
            "target": "answer",
            "document_ids": ["doc-study"],
            "authenticated_user_id": "user-1",
            "request_id": "req-runtime-fallback",
        }
    )

    assert result.evidence.chunks[0].metadata["source_kind"] == "normalized_document"
    assert result.audit_metadata["chunk_source"] == "fallback"
    assert result.audit_metadata["fallback_reason"] == "persisted_chunks_missing"
```

Add this partial persisted coverage test:

```python
@pytest.mark.asyncio
async def test_runtime_falls_back_when_any_requested_document_lacks_persisted_chunks():
    Session = _session_factory()
    _insert_ready_document_with_artifact(Session, document_id="doc-study")
    _insert_ready_document_with_artifact(
        Session,
        document_id="doc-second",
        content="Integrals accumulate signed area.",
    )
    _insert_persisted_chunk(Session, document_id="doc-study")
    runtime = StudyAgentRuntimeService(
        session_factory=Session,
        chunker=StudyDocumentChunker(max_chars=200, overlap_chars=20),
    )

    result = await runtime.run(
        {
            "query": "What do derivatives measure?",
            "target": "answer",
            "document_ids": ["doc-study", "doc-second"],
            "authenticated_user_id": "user-1",
            "request_id": "req-runtime-partial-fallback",
        }
    )

    assert result.audit_metadata["chunk_source"] == "fallback"
    assert result.audit_metadata["fallback_reason"] == "persisted_chunks_incomplete"
```

- [ ] **Step 2: Run tests to verify runtime does not use persisted chunks yet**

Run:

```bash
pytest tests/test_study_agent_runtime.py::test_runtime_prefers_persisted_chunks_over_query_time_chunking tests/test_study_agent_runtime.py::test_runtime_fallback_to_artifact_chunking_is_observable tests/test_study_agent_runtime.py::test_runtime_falls_back_when_any_requested_document_lacks_persisted_chunks -q
```

Expected: FAIL because the runtime always chunks artifacts at query time.

- [ ] **Step 3: Inject and use the index service in runtime**

In `src/services/study_agent_runtime.py`, import the service:

```python
from src.services.study_agent_index import StudyDocumentIndexService
```

Add the optional constructor argument:

```python
        index_service: StudyDocumentIndexService | None = None,
```

Store it:

```python
        self.index_service = index_service or StudyDocumentIndexService(
            session_factory=session_factory,
            chunker=self.chunker,
        )
```

Replace the direct evidence/chunker block in `run` with:

```python
        evidence = self.evidence_source.load(
            owner_id=request.authenticated_user_id,
            document_ids=request.document_ids,
        )
        persisted_chunks = self.index_service.load_chunks(
            owner_id=request.authenticated_user_id,
            document_ids=request.document_ids,
        )
        persisted_document_ids = {
            str(chunk.get("metadata", {}).get("document_id"))
            for chunk in persisted_chunks
        }
        requested_document_ids = {item.document_id for item in evidence}
        if persisted_chunks and requested_document_ids.issubset(persisted_document_ids):
            chunks = list(persisted_chunks)
            chunk_source = "persisted"
            fallback_reason = None
        else:
            chunks = self.chunker.chunk(evidence)
            chunk_source = "fallback"
            fallback_reason = (
                "persisted_chunks_missing"
                if not persisted_chunks
                else "persisted_chunks_incomplete"
            )
```

Keep the existing empty chunk error after this block. After `orchestrator.run(payload)`, attach observable audit metadata:

```python
        result = await orchestrator.run(payload)
        result.audit_metadata["chunk_source"] = chunk_source
        result.audit_metadata["fallback_reason"] = fallback_reason
        return result
```

This keeps graph construction based on `StudyDocumentEvidence` and avoids raw content in audit metadata.

- [ ] **Step 4: Run runtime tests**

Run:

```bash
pytest tests/test_study_agent_runtime.py -q
```

Expected: PASS.

- [ ] **Step 5: Run the two reviews for Task 3**

Spec review checklist:

```text
- Runtime attempts persisted chunks before query-time chunking.
- Owner id and requested document ids are passed into persisted chunk loading.
- Fallback remains available when persisted chunks are absent.
- Fallback reason is observable without exposing content.
```

Quality review checklist:

```text
- Runtime still validates authenticated user before loading chunks.
- Runtime does not mix owner scopes.
- Existing retrieval-miss behavior remains intact.
- Audit metadata contains small scalar fields only.
```

- [ ] **Step 6: Commit Task 3**

Run:

```bash
git add src/services/study_agent_runtime.py tests/test_study_agent_runtime.py
git commit -m "feat: use persisted chunks in study runtime"
```

### Task 4: Worker Indexing

**Files:**
- Modify: `src/workers/tasks.py`
- Modify: `tests/test_workers_product_flow.py`

- [ ] **Step 1: Write the failing worker tests**

Add import in `tests/test_workers_product_flow.py`:

```python
from src.db.models import Base, ContentVersionRecord, Document, DocumentArtifactRecord, DocumentChunkRecord
```

Update `test_product_document_task_creates_artifact_outline_and_questions` to query chunks:

```python
        chunks = (
            session.query(DocumentChunkRecord)
            .filter(DocumentChunkRecord.document_id == upload.document.id)
            .all()
        )
```

Add assertions:

```python
    assert len(chunks) == 1
    assert chunks[0].owner_id == "user-1"
    assert chunks[0].artifact_id == artifacts[0].id
    assert chunks[0].chunk_metadata["source_kind"] == "persisted_document_chunk"
```

Add this idempotency test:

```python
def test_product_document_task_reprocessing_replaces_chunks_without_duplicates(tmp_path: Path):
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
        job = session.get(Document, upload.document.id).jobs[0]
        job.status = "queued"
        job.progress = 0
        session.commit()

    run_product_document_task(
        job_id=upload.job.id,
        document_id=upload.document.id,
        owner_id="user-1",
        session_factory=Session,
        storage=service.storage,
    )

    with Session() as session:
        artifacts = session.query(DocumentArtifactRecord).all()
        chunks = session.query(DocumentChunkRecord).all()

    assert len(artifacts) == 2
    assert len({chunk.artifact_id for chunk in chunks}) == 1
    assert len(chunks) == chunks[0].chunk_count
```

- [ ] **Step 2: Run tests to verify worker does not create chunks yet**

Run:

```bash
pytest tests/test_workers_product_flow.py::test_product_document_task_creates_artifact_outline_and_questions tests/test_workers_product_flow.py::test_product_document_task_reprocessing_replaces_chunks_without_duplicates -q
```

Expected: FAIL because no persisted chunks are created by the worker.

- [ ] **Step 3: Index the normalized artifact in the worker flow**

In `src/workers/tasks.py`, import:

```python
from src.services.study_agent_index import StudyDocumentIndexService
```

Change artifact creation to keep the artifact id:

```python
        artifact_id = f"artifact:{document_id}:normalized:{uuid4().hex}"
        with session_factory() as session:
            session.add(
                DocumentArtifactRecord(
                    id=artifact_id,
                    document_id=document_id,
                    artifact_type="normalized_document",
                    content=normalized,
                    artifact_metadata={"source": "deterministic_worker"},
                    created_at=_utc_now(),
                )
            )
            session.commit()

        StudyDocumentIndexService(session_factory=session_factory).index_artifact(
            owner_id=owner_id,
            document_id=document_id,
            artifact_id=artifact_id,
            require_ready=False,
        )
```

Keep the existing outline and question generation after indexing. The public `index_document` and API path remain strict about ready documents; the worker-only `index_artifact(..., require_ready=False)` path is allowed because the worker already owns the processing transition for that document and job.

- [ ] **Step 4: Preserve final job completion behavior**

Ensure the final completion block still sets:

```python
document.status = "ready"
job.status = "completed"
job.progress = 100
job.completed_at = completed_at
job.updated_at = completed_at
```

If indexing raises, allow the existing `except` block to mark the document and job failed with the indexing error message.

- [ ] **Step 5: Run worker tests**

Run:

```bash
pytest tests/test_workers_product_flow.py -q
```

Expected: PASS.

- [ ] **Step 6: Run the two reviews for Task 4**

Spec review checklist:

```text
- Worker indexes after creating normalized_document.
- Indexing failure prevents a healthy ready evidence path.
- Outline and question generation still run for successful jobs.
- Reprocessing does not leave duplicate active chunks.
```

Quality review checklist:

```text
- Worker keeps owner_id checks.
- Failure path updates document and job to failed.
- No external model, vector, or network dependency is introduced.
- Tests use deterministic local storage only.
```

- [ ] **Step 7: Commit Task 4**

Run:

```bash
git add src/workers/tasks.py tests/test_workers_product_flow.py
git commit -m "feat: persist study chunks during processing"
```

### Task 5: Reindex API And Document Status

**Files:**
- Modify: `src/api/routes/documents.py`
- Modify: `frontend/src/api.ts`
- Modify: `tests/test_study_agent_api.py`

- [ ] **Step 1: Write failing API tests**

Add imports in `tests/test_study_agent_api.py`:

```python
from src.db.models import DocumentChunkRecord
```

Add this helper:

```python
def _insert_ready_document_for_api(Session, *, document_id: str = "doc-api", owner_id: str = "user-1") -> None:
    now = datetime.now(timezone.utc)
    with Session() as session:
        session.add(
            Document(
                id=document_id,
                owner_id=owner_id,
                title="API Notes",
                source_type="pdf",
                storage_uri=f"local://uploads/{document_id}.pdf",
                content_hash=f"hash-{document_id}",
                original_filename=f"{document_id}.pdf",
                status="ready",
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            DocumentArtifactRecord(
                id=f"artifact-{document_id}",
                document_id=document_id,
                artifact_type="normalized_document",
                content="Derivatives measure instantaneous rate of change.",
                artifact_metadata={"source": "api-test"},
                created_at=now,
            )
        )
        session.commit()
```

Add this document status test:

```python
def test_document_payload_includes_compact_study_index_status(tmp_path: Path):
    client, _orchestrator, Session = _client(tmp_path)
    headers = _login(client)
    _insert_ready_document_for_api(Session)

    response = client.get("/api/documents", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["study_index"] == {
        "document_id": "doc-api",
        "status": "fallback_available",
        "artifact_id": "artifact-doc-api",
        "chunk_count": 0,
        "indexed_at": None,
        "fallback_reason": "persisted_chunks_missing",
    }
```

Add this reindex success test:

```python
def test_reindex_endpoint_indexes_owned_ready_document(tmp_path: Path):
    client, _orchestrator, Session = _client(tmp_path)
    headers = _login(client)
    _insert_ready_document_for_api(Session)

    response = client.post("/api/documents/doc-api/study-index/reindex", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["document_id"] == "doc-api"
    assert payload["status"] == "indexed"
    assert payload["artifact_id"] == "artifact-doc-api"
    assert payload["chunk_count"] == 1
    assert payload["fallback_reason"] is None
    with Session() as session:
        chunks = session.query(DocumentChunkRecord).all()
    assert len(chunks) == 1
    assert chunks[0].owner_id == "user-1"
```

Add this cross-owner test:

```python
def test_reindex_endpoint_returns_404_for_cross_owner_document(tmp_path: Path):
    client, _orchestrator, Session = _client(tmp_path)
    headers = _login(client)
    _insert_ready_document_for_api(Session, document_id="doc-private", owner_id="user-2")

    response = client.post("/api/documents/doc-private/study-index/reindex", headers=headers)

    assert response.status_code == 404
```

Add this non-ready test:

```python
def test_reindex_endpoint_rejects_processing_document(tmp_path: Path):
    client, _orchestrator, Session = _client(tmp_path)
    headers = _login(client)
    _insert_ready_document_for_api(Session, document_id="doc-processing", owner_id="user-1")
    with Session() as session:
        document = session.get(Document, "doc-processing")
        document.status = "processing"
        session.commit()

    response = client.post("/api/documents/doc-processing/study-index/reindex", headers=headers)

    assert response.status_code == 422
```

- [ ] **Step 2: Run tests to verify route and payload are missing**

Run:

```bash
pytest tests/test_study_agent_api.py::test_document_payload_includes_compact_study_index_status tests/test_study_agent_api.py::test_reindex_endpoint_indexes_owned_ready_document tests/test_study_agent_api.py::test_reindex_endpoint_returns_404_for_cross_owner_document tests/test_study_agent_api.py::test_reindex_endpoint_rejects_processing_document -q
```

Expected: FAIL because `_document_payload` has no `study_index` field and the route is not registered.

- [ ] **Step 3: Add index status serialization to document payloads**

In `src/api/routes/documents.py`, import:

```python
from src.services.study_agent_documents import StudyAgentDocumentError
from src.services.study_agent_index import StudyDocumentIndexService
```

Change `_document_payload` signature:

```python
def _document_payload(document, study_index: dict[str, Any] | None = None) -> dict[str, Any]:
```

Build the existing payload in a variable and attach compact status:

```python
    payload = {
        "id": document.id,
        "owner_id": document.owner_id,
        "title": document.title,
        "source_type": document.source_type,
        "storage_uri": document.storage_uri,
        "content_hash": document.content_hash,
        "original_filename": document.original_filename,
        "status": document.status,
        "created_at": _format_datetime(document.created_at),
        "updated_at": _format_datetime(document.updated_at),
    }
    if study_index is not None:
        payload["study_index"] = study_index
    return payload
```

Add helper:

```python
def _study_index_service(request: Request) -> StudyDocumentIndexService | None:
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None and hasattr(request.app.state.document_service, "session_factory"):
        session_factory = request.app.state.document_service.session_factory
    if session_factory is None:
        return None
    return StudyDocumentIndexService(session_factory=session_factory)


def _study_index_payload(request: Request, *, owner_id: str, document_id: str) -> dict[str, Any] | None:
    service = _study_index_service(request)
    if service is None:
        return None
    try:
        return service.status(owner_id=owner_id, document_id=document_id).to_dict()
    except StudyAgentDocumentError:
        return None
```

Update `list_documents`:

```python
    documents = document_service.list_documents(owner_id=context.user_id)
    return [
        _document_payload(
            document,
            study_index=_study_index_payload(
                request,
                owner_id=context.user_id,
                document_id=document.id,
            ),
        )
        for document in documents
    ]
```

Update `get_document` similarly:

```python
    return _document_payload(
        document,
        study_index=_study_index_payload(
            request,
            owner_id=context.user_id,
            document_id=document.id,
        ),
    )
```

- [ ] **Step 4: Add the reindex endpoint**

In `src/api/routes/documents.py`, add:

```python
@router.post("/documents/{document_id}/study-index/reindex")
def reindex_document_study_index(request: Request, document_id: str) -> dict[str, Any]:
    context = get_user_context(request)
    service = _study_index_service(request)
    if service is None:
        raise HTTPException(status_code=503, detail="Study document index is not configured")
    try:
        status_payload = service.index_document(
            owner_id=context.user_id,
            document_id=document_id,
        ).to_dict()
    except StudyAgentDocumentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    _record_api_audit(
        request,
        actor_id=context.user_id,
        request_id=context.request_id,
        action="document.study_index.reindexed",
        resource_type="document",
        resource_id=document_id,
        metadata={
            "document_id": status_payload["document_id"],
            "artifact_id": status_payload["artifact_id"],
            "chunk_count": status_payload["chunk_count"],
            "index_status": status_payload["status"],
            "fallback_used": status_payload["fallback_reason"] is not None,
        },
    )
    return status_payload
```

If `_record_api_audit` is unavailable in tests because the document service has no `session_factory`, it already no-ops.

- [ ] **Step 5: Update frontend API type only**

In `frontend/src/api.ts`, add:

```ts
export interface StudyIndexStatus {
  document_id: string;
  status: "indexed" | "missing" | "stale" | "fallback_available";
  artifact_id?: string | null;
  chunk_count: number;
  indexed_at?: string | null;
  fallback_reason?: string | null;
}
```

Add to `ApiDocument`:

```ts
  study_index?: StudyIndexStatus | null;
```

Do not add UI controls in this phase.

- [ ] **Step 6: Run API and frontend type tests**

Run:

```bash
pytest tests/test_study_agent_api.py -q
cd frontend && npm run build
```

Expected: PASS.

- [ ] **Step 7: Run the two reviews for Task 5**

Spec review checklist:

```text
- POST /api/documents/{document_id}/study-index/reindex exists.
- 401 remains handled by global auth middleware.
- Cross-owner documents are unavailable.
- Processing documents return 422.
- Document payloads include compact study_index when DB-backed services are configured.
```

Quality review checklist:

```text
- Audit metadata contains only document_id, artifact_id, chunk_count, index_status, fallback_used.
- Route does not leak cross-owner existence through content.
- Frontend change is type-only.
- API errors reuse StudyAgentDocumentError status codes.
```

- [ ] **Step 8: Commit Task 5**

Run:

```bash
git add src/api/routes/documents.py frontend/src/api.ts tests/test_study_agent_api.py
git commit -m "feat: expose study index status"
```

### Task 6: Final Verification And Docs Sync

**Files:**
- Optional modify: `README.md`
- Optional modify: `SPEC.md`
- Modify this plan only to check off completed task boxes during execution if the implementation workflow tracks progress in the plan file.

- [ ] **Step 1: Run focused backend verification**

Run:

```bash
pytest tests/test_study_agent_documents.py tests/test_study_agent_runtime.py tests/test_workers_product_flow.py -q
pytest tests/test_study_agent_api.py -q
pytest tests/test_db_migrations.py tests/test_db_models.py -q
```

Expected: PASS for all three commands.

- [ ] **Step 2: Run frontend verification**

Run:

```bash
cd frontend && npm run build
```

Expected: PASS.

- [ ] **Step 3: Inspect changed public docs**

Run:

```bash
rg -n "Study Agent|chunk|index|document" README.md SPEC.md docs -g "*.md"
```

If `README.md` or `SPEC.md` already has a Study Agent architecture or document processing section, add this concise note:

```markdown
Phase 2 persists Study Agent document chunks after `normalized_document` artifacts are created. Query-time chunking remains as an observable fallback while the persisted index rolls out.
```

If those files do not summarize Study Agent internals, leave them unchanged and keep the phase detail in `docs/superpowers/specs/2026-06-26-persistent-chunk-index-design.md`.

- [ ] **Step 4: Run the two final reviews**

Spec review checklist:

```text
- Document processing creates persisted chunks for ready documents with non-empty normalized_document artifacts.
- Study Agent uses persisted chunks without re-chunking when chunks exist.
- Fallback is intentional and observable.
- Owner and document scope are enforced.
- Reindexing does not duplicate chunks.
- Newer artifacts replace stale chunks deterministically.
- Owned ready documents can be reindexed through the API.
- Non-ready and missing-artifact documents return product errors.
- Existing upload, processing, Study Agent, frontend build, and focused backend tests pass.
```

Quality review checklist:

```text
- Migrations upgrade and downgrade on SQLite test database.
- No out-of-scope embedding provider, vector search, Graph RAG tuning, or frontend panel was added.
- Audit metadata is sanitized.
- Tests are deterministic and do not require network services.
- Commit history is task-scoped and readable.
```

- [ ] **Step 5: Commit documentation updates if files changed**

If `README.md`, `SPEC.md`, or the plan checklist changed, run:

```bash
git add README.md SPEC.md docs/superpowers/plans/2026-06-26-persistent-chunk-index.md
git commit -m "docs: document persistent chunk index"
```

If no docs changed during implementation, do not create an empty commit.

- [ ] **Step 6: Report final implementation status**

Include:

```text
- Commits created for Tasks 1-5 and optional Task 6 docs.
- Verification commands run and pass/fail status.
- Any skipped optional docs update with reason.
- Remaining rollout note: fallback can be removed only after persisted indexing has production visibility.
```
