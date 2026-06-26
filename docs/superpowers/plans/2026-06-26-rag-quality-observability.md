# RAG Quality Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Phase 3 RAG quality and index observability layer so Study Agent queries create safe traces, index health is explainable, deterministic RAG modes can be evaluated, and P1 users/operators can see compact diagnostics.

**Architecture:** Add additive trace/evaluation database records and keep runtime behavior unchanged. Introduce focused services for trace persistence, index summary, evaluation fixture loading, evaluation execution, reporting, and readiness gates, then wire them into the existing FastAPI and React surfaces. Keep P0 backend observability separate from P1 operator/frontend polish.

**Tech Stack:** FastAPI, SQLAlchemy ORM, Alembic, pytest, SQLite test database, deterministic in-process Study Agent services, Vite/React/TypeScript frontend.

---

## Scope And Product Boundaries

This plan implements `docs/superpowers/specs/2026-06-26-rag-quality-observability-design.md`.

It includes:

- Persistent `StudyAgentTraceRecord`, `RAGEvaluationRunRecord`, and `RAGEvaluationCaseScoreRecord`.
- Additive Alembic migration `0004_rag_quality_observability.py`.
- `StudyAgentTraceService` for safe trace creation and owner-scoped reads.
- Additive `/api/study-agent/query` trace payload.
- Extended `StudyDocumentIndexService` status and owner-scoped summary behavior.
- Expanded RAG evaluation fixture schema and deterministic evaluation runner.
- JSON/Markdown evaluation reports and readiness gate summaries.
- P1 trace/index/evaluation APIs, feedback trace linking, and compact frontend diagnostics.

It excludes:

- Real embedding providers.
- pgvector retrieval switching.
- Automatic Graph RAG or Agentic RAG routing threshold changes.
- A large analytics dashboard.
- Bulk historical reindexing.
- Document parsing quality changes.

## File Structure

- Modify `src/db/models.py`: add trace and evaluation ORM records plus indexes.
- Modify `src/db/__init__.py`: export the new records.
- Create `src/db/migrations/versions/0004_rag_quality_observability.py`: create trace/evaluation tables.
- Create `src/services/study_agent_trace.py`: hash queries, build safe trace payloads, persist/read traces.
- Modify `src/services/study_agent_runtime.py`: measure latency and collect per-document index status for traces.
- Modify `src/services/study_agent_index.py`: extend `DocumentIndexStatus` and add owner-scoped `summary`.
- Modify `src/api/routes/study_agent.py`: persist traces, return compact trace payload, add trace/index P1 endpoints.
- Create `src/api/routes/admin.py`: admin-only RAG evaluation run APIs.
- Modify `src/api/app.py`: register the admin router.
- Modify `src/api/routes/feedback.py`: allow `study_agent_trace` feedback targets and sanitize audit metadata.
- Modify `src/services/rag_evaluation.py`: expand fixture schema, runner, reports, readiness gates.
- Keep `tests/fixtures/rag_eval_set.json`: expand deterministic public fixture cases.
- Modify `tests/test_db_models.py`: ORM coverage for trace/evaluation records.
- Modify `tests/test_db_migrations.py`: migration schema coverage.
- Create `tests/test_study_agent_traces.py`: trace service coverage.
- Modify `tests/test_study_agent_api.py`: query trace payload, trace API, admin evaluation API, audit privacy.
- Modify `tests/test_study_agent_documents.py`: index summary coverage.
- Modify `tests/test_rag_evaluation.py`: expanded fixture/runner/report coverage.
- Modify `tests/test_rag_mode_comparison.py`: readiness gates and summaries.
- Modify `frontend/src/api.ts`: trace/index/evaluation types and feedback target support.
- Modify `frontend/src/components/StudyAgentPanel.tsx`: compact trace diagnostics.
- Modify `frontend/src/styles.css`: small diagnostic styles only.

## Shared Review Rule

After each task, run both reviews before moving to the next task:

- **Spec review:** compare the task diff against `docs/superpowers/specs/2026-06-26-rag-quality-observability-design.md`. Confirm no P0/P1 requirement was skipped and no out-of-scope embeddings, pgvector retrieval switch, auto route tuning, parsing rewrite, or analytics dashboard slipped in.
- **Quality review:** inspect owner isolation, privacy sanitization, migration compatibility, deterministic tests, naming consistency, and report reproducibility. Confirm no raw query text, generated answer text, raw chunk content, source snippets, tokens, passwords, or secrets are persisted in trace/audit records.

Record the two review results in the task completion note or commit body.

## Task 1: Trace And Evaluation Database Schema

**Files:**
- Modify: `src/db/models.py`
- Modify: `src/db/__init__.py`
- Create: `src/db/migrations/versions/0004_rag_quality_observability.py`
- Modify: `tests/test_db_models.py`
- Modify: `tests/test_db_migrations.py`

- [ ] **Step 1: Write failing ORM model tests**

Append this import block update in `tests/test_db_models.py`:

```python
from src.db import (
    AuditEventRecord,
    Base,
    ContentVersionRecord,
    Document,
    DocumentArtifactRecord,
    DocumentChunkRecord,
    ExportJobRecord,
    FeedbackRecord,
    KnowledgePointRecord,
    OutlineRecord,
    ParsedSection,
    ProcessingJob,
    QuestionRecord,
    RAGEvaluationCaseScoreRecord,
    RAGEvaluationRunRecord,
    ReviewTaskRecord,
    StudyAgentTraceRecord,
    UserRecord,
    create_session_factory,
)
```

Append this test to `tests/test_db_models.py`:

```python
def test_rag_quality_observability_records_create_and_preserve_safe_metadata(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'rag_quality.db'}")
    Base.metadata.create_all(engine)
    SessionFactory = create_session_factory(engine)

    with SessionFactory() as session:
        trace = StudyAgentTraceRecord(
            id="trace-1",
            owner_id="user-1",
            request_id="req-1",
            query_hash="sha256:query",
            target="answer",
            document_ids=["doc-1"],
            selected_mode="simple_rag",
            route_reason="definition or direct lookup query",
            estimated_cost="low",
            fallback_chain=[],
            chunk_source="persisted",
            fallback_reason=None,
            source_count=1,
            used_chunk_count=2,
            confidence=0.9,
            source_recall=1.0,
            answer_term_recall=0.5,
            needs_review=False,
            latency_ms=12.5,
            trace_metadata={
                "expected_term_count": 2,
                "index_statuses": {
                    "doc-1": {
                        "status": "indexed",
                        "fallback_reason": None,
                    }
                },
            },
        )
        run = RAGEvaluationRunRecord(
            id="eval-run-1",
            created_by="admin-1",
            fixture_version="rag-eval-v1",
            modes=["simple_rag", "graph_rag_lite"],
            case_count=2,
            status="completed",
            summary={"simple_rag": {"average_source_recall": 1.0}},
            report_uri="local://reports/eval-run-1.md",
        )
        score = RAGEvaluationCaseScoreRecord(
            id="eval-score-1",
            run=run,
            case_id="def-001",
            mode="simple_rag",
            category="definition",
            source_recall=1.0,
            answer_term_recall=0.5,
            answer_coverage=0.5,
            latency_ms=10,
            estimated_cost=0,
            needs_review=False,
            fallback_reason=None,
            error_code=None,
        )
        session.add_all([trace, run, score])
        session.commit()

    with Session(engine) as session:
        stored_trace = session.get(StudyAgentTraceRecord, "trace-1")
        stored_run = session.get(RAGEvaluationRunRecord, "eval-run-1")
        stored_score = session.get(RAGEvaluationCaseScoreRecord, "eval-score-1")

    assert stored_trace is not None
    assert stored_trace.owner_id == "user-1"
    assert stored_trace.document_ids == ["doc-1"]
    assert stored_trace.trace_metadata["expected_term_count"] == 2
    assert stored_trace.created_at is not None
    assert stored_run is not None
    assert stored_run.scores[0].case_id == "def-001"
    assert stored_score is not None
    assert stored_score.run_id == "eval-run-1"
```

- [ ] **Step 2: Write failing migration test expectations**

In `tests/test_db_migrations.py`, inside `test_alembic_upgrade_creates_orm_compatible_sqlite_schema` after `audit_event_columns` is defined, add:

```python
    trace_columns = {column["name"] for column in inspector.get_columns("study_agent_traces")}
    eval_run_columns = {column["name"] for column in inspector.get_columns("rag_evaluation_runs")}
    eval_score_columns = {
        column["name"] for column in inspector.get_columns("rag_evaluation_case_scores")
    }
```

Before the existing `with engine.connect()` block, add:

```python
    assert {
        "id",
        "owner_id",
        "request_id",
        "query_hash",
        "target",
        "document_ids",
        "selected_mode",
        "route_reason",
        "estimated_cost",
        "fallback_chain",
        "chunk_source",
        "fallback_reason",
        "source_count",
        "used_chunk_count",
        "confidence",
        "source_recall",
        "answer_term_recall",
        "needs_review",
        "latency_ms",
        "metadata",
        "created_at",
    }.issubset(trace_columns)
    trace_indexes = {index["name"] for index in inspector.get_indexes("study_agent_traces")}
    assert "ix_study_agent_traces_owner_created" in trace_indexes
    assert "ix_study_agent_traces_owner_request" in trace_indexes
    assert "ix_study_agent_traces_owner_query_hash" in trace_indexes
    assert "ix_study_agent_traces_owner_mode_created" in trace_indexes
    assert "ix_study_agent_traces_review_created" in trace_indexes
    assert {
        "id",
        "created_by",
        "fixture_version",
        "modes",
        "case_count",
        "status",
        "summary",
        "report_uri",
        "created_at",
        "completed_at",
    }.issubset(eval_run_columns)
    assert {
        "id",
        "run_id",
        "case_id",
        "mode",
        "category",
        "source_recall",
        "answer_term_recall",
        "answer_coverage",
        "latency_ms",
        "estimated_cost",
        "needs_review",
        "fallback_reason",
        "error_code",
    }.issubset(eval_score_columns)
    eval_score_indexes = {
        index["name"] for index in inspector.get_indexes("rag_evaluation_case_scores")
    }
    assert "ix_rag_eval_scores_run_mode" in eval_score_indexes
    assert "ix_rag_eval_scores_run_category" in eval_score_indexes
    assert "ix_rag_eval_scores_mode_category" in eval_score_indexes
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
pytest tests/test_db_models.py::test_rag_quality_observability_records_create_and_preserve_safe_metadata tests/test_db_migrations.py::test_alembic_upgrade_creates_orm_compatible_sqlite_schema -q
```

Expected: FAIL because `StudyAgentTraceRecord`, `RAGEvaluationRunRecord`, and `RAGEvaluationCaseScoreRecord` do not exist.

- [ ] **Step 4: Add ORM records**

In `src/db/models.py`, add `Float` to SQLAlchemy imports:

```python
    Float,
```

Add these models after `AuditEventRecord`:

```python
class StudyAgentTraceRecord(Base):
    __tablename__ = "study_agent_traces"
    __table_args__ = (
        Index("ix_study_agent_traces_owner_created", "owner_id", "created_at"),
        Index("ix_study_agent_traces_owner_request", "owner_id", "request_id"),
        Index("ix_study_agent_traces_owner_query_hash", "owner_id", "query_hash"),
        Index("ix_study_agent_traces_owner_mode_created", "owner_id", "selected_mode", "created_at"),
        Index("ix_study_agent_traces_review_created", "needs_review", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    query_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    target: Mapped[str] = mapped_column(String(32), nullable=False)
    document_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    selected_mode: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    route_reason: Mapped[str] = mapped_column(String(255), nullable=False)
    estimated_cost: Mapped[str] = mapped_column(String(32), nullable=False)
    fallback_chain: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    chunk_source: Mapped[Optional[str]] = mapped_column(String(32))
    fallback_reason: Mapped[Optional[str]] = mapped_column(String(128))
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    used_chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    source_recall: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    answer_term_recall: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    trace_metadata: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class RAGEvaluationRunRecord(Base):
    __tablename__ = "rag_evaluation_runs"
    __table_args__ = (
        Index("ix_rag_eval_runs_created_by_created", "created_by", "created_at"),
        Index("ix_rag_eval_runs_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    fixture_version: Mapped[str] = mapped_column(String(128), nullable=False)
    modes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    case_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running", index=True)
    summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    report_uri: Mapped[Optional[str]] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    scores: Mapped[List["RAGEvaluationCaseScoreRecord"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class RAGEvaluationCaseScoreRecord(Base):
    __tablename__ = "rag_evaluation_case_scores"
    __table_args__ = (
        Index("ix_rag_eval_scores_run_mode", "run_id", "mode"),
        Index("ix_rag_eval_scores_run_category", "run_id", "category"),
        Index("ix_rag_eval_scores_mode_category", "mode", "category"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("rag_evaluation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    case_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_recall: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    answer_term_recall: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    answer_coverage: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    estimated_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fallback_reason: Mapped[Optional[str]] = mapped_column(String(128))
    error_code: Mapped[Optional[str]] = mapped_column(String(128))

    run: Mapped[RAGEvaluationRunRecord] = relationship(back_populates="scores")
```

- [ ] **Step 5: Export ORM records**

In `src/db/__init__.py`, add imports:

```python
    RAGEvaluationCaseScoreRecord,
    RAGEvaluationRunRecord,
    StudyAgentTraceRecord,
```

Add them to `__all__`:

```python
    "RAGEvaluationCaseScoreRecord",
    "RAGEvaluationRunRecord",
    "StudyAgentTraceRecord",
```

- [ ] **Step 6: Add Alembic migration**

Create `src/db/migrations/versions/0004_rag_quality_observability.py`:

```python
"""Add RAG quality observability tables.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-26
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "study_agent_traces",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("query_hash", sa.String(length=128), nullable=False),
        sa.Column("target", sa.String(length=32), nullable=False),
        sa.Column("document_ids", sa.JSON(), nullable=False),
        sa.Column("selected_mode", sa.String(length=32), nullable=False),
        sa.Column("route_reason", sa.String(length=255), nullable=False),
        sa.Column("estimated_cost", sa.String(length=32), nullable=False),
        sa.Column("fallback_chain", sa.JSON(), nullable=False),
        sa.Column("chunk_source", sa.String(length=32), nullable=True),
        sa.Column("fallback_reason", sa.String(length=128), nullable=True),
        sa.Column("source_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("used_chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("source_recall", sa.Float(), nullable=False, server_default="0"),
        sa.Column("answer_term_recall", sa.Float(), nullable=False, server_default="0"),
        sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("latency_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_study_agent_traces_owner_id", "study_agent_traces", ["owner_id"])
    op.create_index("ix_study_agent_traces_request_id", "study_agent_traces", ["request_id"])
    op.create_index("ix_study_agent_traces_query_hash", "study_agent_traces", ["query_hash"])
    op.create_index("ix_study_agent_traces_selected_mode", "study_agent_traces", ["selected_mode"])
    op.create_index("ix_study_agent_traces_owner_created", "study_agent_traces", ["owner_id", "created_at"])
    op.create_index("ix_study_agent_traces_owner_request", "study_agent_traces", ["owner_id", "request_id"])
    op.create_index("ix_study_agent_traces_owner_query_hash", "study_agent_traces", ["owner_id", "query_hash"])
    op.create_index(
        "ix_study_agent_traces_owner_mode_created",
        "study_agent_traces",
        ["owner_id", "selected_mode", "created_at"],
    )
    op.create_index("ix_study_agent_traces_review_created", "study_agent_traces", ["needs_review", "created_at"])

    op.create_table(
        "rag_evaluation_runs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("fixture_version", sa.String(length=128), nullable=False),
        sa.Column("modes", sa.JSON(), nullable=False),
        sa.Column("case_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="running"),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("report_uri", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_rag_evaluation_runs_created_by", "rag_evaluation_runs", ["created_by"])
    op.create_index("ix_rag_evaluation_runs_status", "rag_evaluation_runs", ["status"])
    op.create_index("ix_rag_eval_runs_created_by_created", "rag_evaluation_runs", ["created_by", "created_at"])
    op.create_index("ix_rag_eval_runs_status_created", "rag_evaluation_runs", ["status", "created_at"])

    op.create_table(
        "rag_evaluation_case_scores",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(length=64),
            sa.ForeignKey("rag_evaluation_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("case_id", sa.String(length=128), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("source_recall", sa.Float(), nullable=False, server_default="0"),
        sa.Column("answer_term_recall", sa.Float(), nullable=False, server_default="0"),
        sa.Column("answer_coverage", sa.Float(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("estimated_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("fallback_reason", sa.String(length=128), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
    )
    op.create_index("ix_rag_evaluation_case_scores_run_id", "rag_evaluation_case_scores", ["run_id"])
    op.create_index("ix_rag_evaluation_case_scores_case_id", "rag_evaluation_case_scores", ["case_id"])
    op.create_index("ix_rag_evaluation_case_scores_mode", "rag_evaluation_case_scores", ["mode"])
    op.create_index("ix_rag_evaluation_case_scores_category", "rag_evaluation_case_scores", ["category"])
    op.create_index("ix_rag_eval_scores_run_mode", "rag_evaluation_case_scores", ["run_id", "mode"])
    op.create_index("ix_rag_eval_scores_run_category", "rag_evaluation_case_scores", ["run_id", "category"])
    op.create_index("ix_rag_eval_scores_mode_category", "rag_evaluation_case_scores", ["mode", "category"])


def downgrade() -> None:
    op.drop_table("rag_evaluation_case_scores")
    op.drop_table("rag_evaluation_runs")
    op.drop_table("study_agent_traces")
```

- [ ] **Step 7: Run focused schema tests**

Run:

```bash
pytest tests/test_db_models.py::test_rag_quality_observability_records_create_and_preserve_safe_metadata tests/test_db_migrations.py::test_alembic_upgrade_creates_orm_compatible_sqlite_schema -q
```

Expected: PASS.

- [ ] **Step 8: Run full DB tests**

Run:

```bash
pytest tests/test_db_models.py tests/test_db_migrations.py -q
```

Expected: PASS.

- [ ] **Step 9: Run review gates**

Spec review checklist:

- New schema matches spec trace/evaluation required fields.
- No raw content/query/snippet columns were added.
- Migration is additive and follows current Alembic revision order.

Quality review checklist:

- Index names match tests and spec.
- JSON columns use safe metadata names.
- Evaluation scores cascade with runs.

- [ ] **Step 10: Commit**

Run:

```bash
git add src/db/models.py src/db/__init__.py src/db/migrations/versions/0004_rag_quality_observability.py tests/test_db_models.py tests/test_db_migrations.py
git commit -m "feat: add rag quality observability schema"
```

## Task 2: Study Agent Trace Service

**Files:**
- Create: `src/services/study_agent_trace.py`
- Create: `tests/test_study_agent_traces.py`

- [ ] **Step 1: Write failing trace service tests**

Create `tests/test_study_agent_traces.py`:

```python
from sqlalchemy import create_engine

from src.db import Base, StudyAgentTraceRecord, create_session_factory
from src.services.rag_router import RetrievalMode
from src.services.study_agent import (
    EvidenceBundle,
    StudyAgentResult,
    StudyBudget,
    StudyDraft,
    StudyPlan,
    StudyRequest,
    StudyTarget,
    StudyVerification,
)
from src.services.study_agent_trace import StudyAgentTraceService


def _session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'traces.db'}")
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


def _result() -> StudyAgentResult:
    return StudyAgentResult(
        request=StudyRequest(
            query="什么是导数？",
            target=StudyTarget.ANSWER,
            document_ids=("doc-1",),
            budget=StudyBudget.BALANCED,
            expected_terms=("变化率", "函数"),
            authenticated_user_id="user-1",
            request_id="req-1",
        ),
        plan=StudyPlan(
            mode=RetrievalMode.SIMPLE,
            reason="definition or direct lookup query",
            steps=("retrieve_chunks",),
            estimated_cost="low",
            fallbacks=(),
        ),
        evidence=EvidenceBundle(
            mode=RetrievalMode.SIMPLE,
            chunks=(),
            sources=("document:doc-1:chunk:0",),
            concept_ids=(),
            confidence=0.9,
            reason="simple token-overlap retrieval",
        ),
        draft=StudyDraft(
            target=StudyTarget.ANSWER,
            content="导数描述函数变化率。",
            citations=("document:doc-1:chunk:0",),
            used_chunk_count=1,
            metadata={},
        ),
        verification=StudyVerification(
            passed=True,
            needs_review=False,
            confidence=0.8,
            issues=(),
            source_recall=1.0,
            answer_term_recall=0.5,
        ),
        audit_metadata={
            "mode": "simple_rag",
            "target": "answer",
            "chunk_source": "persisted",
            "fallback_reason": None,
        },
    )


def test_trace_service_persists_safe_summary_without_raw_private_content(tmp_path):
    Session = _session_factory(tmp_path)
    service = StudyAgentTraceService(Session)

    trace = service.record_success(
        owner_id="user-1",
        request_id="req-1",
        result=_result(),
        latency_ms=12.5,
        index_statuses={
            "doc-1": {
                "status": "indexed",
                "fallback_reason": None,
            }
        },
    )

    assert trace["trace_id"].startswith("trace-")
    assert trace["selected_mode"] == "simple_rag"
    assert trace["chunk_source"] == "persisted"
    assert trace["source_count"] == 1
    assert trace["used_chunk_count"] == 1
    assert trace["confidence"] == 0.8
    assert trace["answer_term_recall"] == 0.5

    with Session() as session:
        record = session.get(StudyAgentTraceRecord, trace["trace_id"])

    assert record is not None
    assert record.owner_id == "user-1"
    assert record.query_hash.startswith("sha256:")
    assert record.query_hash != "什么是导数？"
    serialized = str(record.__dict__) + str(record.trace_metadata)
    assert "什么是导数" not in serialized
    assert "导数描述" not in serialized
    assert "document:doc-1:chunk:0" not in record.trace_metadata.get("raw_content", "")
    assert "变化率" not in serialized


def test_trace_service_reads_owner_scoped_trace(tmp_path):
    Session = _session_factory(tmp_path)
    service = StudyAgentTraceService(Session)
    created = service.record_success(
        owner_id="user-1",
        request_id="req-1",
        result=_result(),
        latency_ms=3,
        index_statuses={},
    )

    own_trace = service.get_trace(owner_id="user-1", trace_id=created["trace_id"])
    other_trace = service.get_trace(owner_id="user-2", trace_id=created["trace_id"])

    assert own_trace is not None
    assert own_trace["trace_id"] == created["trace_id"]
    assert own_trace["query_hash"].startswith("sha256:")
    assert other_trace is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_study_agent_traces.py -q
```

Expected: FAIL because `src.services.study_agent_trace` does not exist.

- [ ] **Step 3: Implement trace service**

Create `src/services/study_agent_trace.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from typing import Any
from uuid import uuid4

from src.db.models import StudyAgentTraceRecord


class StudyAgentTraceService:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    def record_success(
        self,
        *,
        owner_id: str,
        request_id: str | None,
        result: Any,
        latency_ms: int | float,
        index_statuses: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        request = result.request
        plan = result.plan
        draft = result.draft
        verification = result.verification
        audit_metadata = dict(getattr(result, "audit_metadata", {}) or {})
        trace_id = f"trace-{uuid4().hex}"
        now = datetime.now(timezone.utc)
        trace_metadata = {
            "expected_term_count": len(getattr(request, "expected_terms", ()) or ()),
            "index_statuses": _safe_index_statuses(index_statuses or {}),
        }
        record = StudyAgentTraceRecord(
            id=trace_id,
            owner_id=owner_id,
            request_id=request_id,
            query_hash=_query_hash(request.query),
            target=request.target.value,
            document_ids=list(request.document_ids),
            selected_mode=plan.mode.value,
            route_reason=plan.reason,
            estimated_cost=plan.estimated_cost,
            fallback_chain=[mode.value for mode in plan.fallbacks],
            chunk_source=audit_metadata.get("chunk_source"),
            fallback_reason=audit_metadata.get("fallback_reason"),
            source_count=len(result.evidence.sources),
            used_chunk_count=draft.used_chunk_count,
            confidence=verification.confidence,
            source_recall=verification.source_recall,
            answer_term_recall=verification.answer_term_recall,
            needs_review=verification.needs_review,
            latency_ms=float(latency_ms),
            trace_metadata=trace_metadata,
            created_at=now,
        )
        with self.session_factory() as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            return _trace_payload(record)

    def get_trace(self, *, owner_id: str, trace_id: str) -> dict[str, Any] | None:
        with self.session_factory() as session:
            record = (
                session.query(StudyAgentTraceRecord)
                .filter(
                    StudyAgentTraceRecord.id == trace_id,
                    StudyAgentTraceRecord.owner_id == owner_id,
                )
                .first()
            )
            if record is None:
                return None
            return _trace_payload(record, include_hash=True)


def _query_hash(query: str) -> str:
    normalized = " ".join(str(query or "").strip().lower().split())
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _safe_index_statuses(index_statuses: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    safe: dict[str, dict[str, Any]] = {}
    for document_id, status in index_statuses.items():
        safe[str(document_id)] = {
            "status": status.get("status"),
            "fallback_reason": status.get("fallback_reason"),
            "chunk_count": status.get("chunk_count"),
        }
    return safe


def _trace_payload(record: StudyAgentTraceRecord, *, include_hash: bool = False) -> dict[str, Any]:
    payload = {
        "trace_id": record.id,
        "request_id": record.request_id,
        "selected_mode": record.selected_mode,
        "route_reason": record.route_reason,
        "chunk_source": record.chunk_source,
        "fallback_reason": record.fallback_reason,
        "document_count": len(record.document_ids or []),
        "source_count": record.source_count,
        "used_chunk_count": record.used_chunk_count,
        "confidence": record.confidence,
        "source_recall": record.source_recall,
        "answer_term_recall": record.answer_term_recall,
        "needs_review": record.needs_review,
        "latency_ms": record.latency_ms,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "metadata": dict(record.trace_metadata or {}),
    }
    if include_hash:
        payload["query_hash"] = record.query_hash
    return payload
```

- [ ] **Step 4: Run trace service tests**

Run:

```bash
pytest tests/test_study_agent_traces.py -q
```

Expected: PASS.

- [ ] **Step 5: Run review gates**

Spec review checklist:

- Trace service creates owner-scoped safe trace summaries.
- Query hash is stored instead of raw query.
- Index statuses are compact and content-free.

Quality review checklist:

- No trace metadata includes raw query, generated answer, chunk content, source snippets, or expected terms.
- `get_trace` filters by owner.
- Payload shape matches the spec trace contract.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/services/study_agent_trace.py tests/test_study_agent_traces.py
git commit -m "feat: add study agent trace service"
```

## Task 3: Query Trace Runtime And API Integration

**Files:**
- Modify: `src/services/study_agent_runtime.py`
- Modify: `src/api/routes/study_agent.py`
- Modify: `tests/test_study_agent_api.py`
- Modify: `tests/test_study_agent_runtime.py`

- [ ] **Step 1: Write failing runtime latency/index metadata test**

In `tests/test_study_agent_runtime.py`, add this assertion to `test_runtime_prefers_persisted_chunks_over_query_time_chunking` after existing `fallback_reason` assertions:

```python
    assert result.audit_metadata["index_statuses"]["doc-1"]["status"] == "indexed"
    assert result.audit_metadata["latency_ms"] >= 0
```

In the fallback test for missing chunks, add:

```python
    assert result.audit_metadata["index_statuses"]["doc-1"]["status"] == "fallback_available"
```

- [ ] **Step 2: Write failing API query trace test**

In `tests/test_study_agent_api.py`, extend `test_study_agent_query_returns_trace_payload` with:

```python
    assert payload["trace"]["trace_id"].startswith("trace-")
    assert payload["trace"]["request_id"] == "req-study-1"
    assert payload["trace"]["selected_mode"] == "simple_rag"
    assert payload["trace"]["chunk_source"] in {"persisted", None}
    assert payload["trace"]["source_count"] == 1
    assert payload["trace"]["used_chunk_count"] == 1
    assert payload["trace"]["latency_ms"] >= 0
```

Extend `test_study_agent_query_persists_sanitized_audit_event` with:

```python
    assert event.event_metadata["trace_id"].startswith("trace-")
    assert "chunk_source" in event.event_metadata
    assert "fallback_reason" in event.event_metadata
    assert "latency_ms" in event.event_metadata
```

- [ ] **Step 3: Run focused tests to verify they fail**

Run:

```bash
pytest tests/test_study_agent_runtime.py tests/test_study_agent_api.py::test_study_agent_query_returns_trace_payload tests/test_study_agent_api.py::test_study_agent_query_persists_sanitized_audit_event -q
```

Expected: FAIL because trace payload and runtime index status are not wired.

- [ ] **Step 4: Add runtime latency and index statuses**

In `src/services/study_agent_runtime.py`, add:

```python
from time import perf_counter
```

At the beginning of `run`, after request normalization, add:

```python
        started_at = perf_counter()
```

After evidence is loaded and before chunk source decision, add:

```python
        index_statuses = {
            document_id: self.index_service.status(
                owner_id=request.authenticated_user_id,
                document_id=document_id,
            ).to_dict()
            for document_id in requested_artifact_by_document_id
        }
```

Before `return result`, add:

```python
        result.audit_metadata["index_statuses"] = index_statuses
        result.audit_metadata["latency_ms"] = round((perf_counter() - started_at) * 1000, 3)
```

- [ ] **Step 5: Wire trace service into Study Agent API**

In `src/api/routes/study_agent.py`, add imports:

```python
from time import perf_counter

from src.services.study_agent_trace import StudyAgentTraceService
```

In `query_study_agent`, before `try`, add:

```python
    started_at = perf_counter()
```

After `result = await runner.run(payload_data)`, add:

```python
        latency_ms = getattr(result, "audit_metadata", {}).get("latency_ms")
        if latency_ms is None:
            latency_ms = round((perf_counter() - started_at) * 1000, 3)
```

Replace the audit call and return with:

```python
    trace_payload = _record_study_agent_trace(
        request,
        actor_id=context.user_id,
        request_id=context.request_id,
        result=result,
        latency_ms=latency_ms,
    )
    _record_study_agent_audit(
        request,
        actor_id=context.user_id,
        request_id=context.request_id,
        result=result,
        payload=payload_data,
        trace_payload=trace_payload,
    )
    response_payload = _to_jsonable(result)
    if trace_payload is not None:
        response_payload["trace"] = trace_payload
    return response_payload
```

Add helper:

```python
def _record_study_agent_trace(
    request: Request,
    *,
    actor_id: str,
    request_id: str,
    result: Any,
    latency_ms: int | float,
) -> dict[str, Any] | None:
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        return _trace_payload_without_persistence(
            request_id=request_id,
            result=result,
            latency_ms=latency_ms,
        )
    service = StudyAgentTraceService(session_factory)
    audit_metadata = getattr(result, "audit_metadata", {}) or {}
    return service.record_success(
        owner_id=actor_id,
        request_id=request_id,
        result=result,
        latency_ms=latency_ms,
        index_statuses=audit_metadata.get("index_statuses") or {},
    )
```

Add fallback helper for injected fake orchestrators without a DB:

```python
def _trace_payload_without_persistence(
    *,
    request_id: str,
    result: Any,
    latency_ms: int | float,
) -> dict[str, Any]:
    audit_metadata = getattr(result, "audit_metadata", {}) or {}
    return {
        "trace_id": "trace-unpersisted",
        "request_id": request_id,
        "selected_mode": audit_metadata.get("mode"),
        "route_reason": getattr(result.plan, "reason", None),
        "chunk_source": audit_metadata.get("chunk_source"),
        "fallback_reason": audit_metadata.get("fallback_reason"),
        "document_count": len(getattr(result.request, "document_ids", ()) or ()),
        "source_count": audit_metadata.get("source_count", len(result.evidence.sources)),
        "used_chunk_count": result.draft.used_chunk_count,
        "confidence": result.verification.confidence,
        "source_recall": result.verification.source_recall,
        "answer_term_recall": result.verification.answer_term_recall,
        "needs_review": result.verification.needs_review,
        "latency_ms": latency_ms,
    }
```

Update `_record_study_agent_audit` signature:

```python
def _record_study_agent_audit(
    request: Request,
    *,
    actor_id: str,
    request_id: str,
    result: Any,
    payload: dict[str, Any],
    trace_payload: dict[str, Any] | None = None,
) -> None:
```

Update metadata:

```python
    metadata = {
        "trace_id": trace_payload.get("trace_id") if trace_payload else None,
        "mode": audit_metadata.get("mode"),
        "target": audit_metadata.get("target"),
        "needs_review": audit_metadata.get("needs_review"),
        "source_count": audit_metadata.get("source_count"),
        "chunk_count": audit_metadata.get("chunk_count"),
        "document_count": len(payload.get("document_ids") or []),
        "chunk_source": audit_metadata.get("chunk_source"),
        "fallback_reason": audit_metadata.get("fallback_reason"),
        "latency_ms": audit_metadata.get("latency_ms"),
    }
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
pytest tests/test_study_agent_runtime.py tests/test_study_agent_api.py::test_study_agent_query_returns_trace_payload tests/test_study_agent_api.py::test_study_agent_query_persists_sanitized_audit_event -q
```

Expected: PASS.

- [ ] **Step 7: Run broader Study Agent tests**

Run:

```bash
pytest tests/test_study_agent_api.py tests/test_study_agent_runtime.py tests/test_study_agent_traces.py -q
```

Expected: PASS.

- [ ] **Step 8: Run review gates**

Spec review checklist:

- Every successful query returns compact trace payload.
- Trace persistence is used when `session_factory` exists.
- Audit metadata remains summarized.

Quality review checklist:

- Fake-orchestrator test path still works.
- Trace creation does not break owner auth.
- No raw query, draft content, chunks, or expected terms enter audit metadata.

- [ ] **Step 9: Commit**

Run:

```bash
git add src/services/study_agent_runtime.py src/api/routes/study_agent.py tests/test_study_agent_api.py tests/test_study_agent_runtime.py
git commit -m "feat: return safe study agent query traces"
```

## Task 4: Index Health Summary

**Files:**
- Modify: `src/services/study_agent_index.py`
- Modify: `tests/test_study_agent_documents.py`

- [ ] **Step 1: Write failing index status extension test**

In `tests/test_study_agent_documents.py`, extend the indexed status assertion with:

```python
    payload = status.to_dict()
    assert payload["expected_chunk_count"] == status.chunk_count
    assert payload["latest_artifact_id"] == status.artifact_id
    assert payload["indexed_artifact_id"] == status.artifact_id
```

Add this test:

```python
def test_index_service_summary_counts_statuses_and_fallback_reasons(tmp_path):
    Session = _session_factory(tmp_path)
    _add_ready_document_with_artifact(
        Session,
        document_id="doc-indexed",
        owner_id="user-1",
        artifact_id="artifact-indexed",
        content="Derivative content",
    )
    _add_ready_document_with_artifact(
        Session,
        document_id="doc-missing",
        owner_id="user-1",
        artifact_id="artifact-missing",
        content="Gradient content",
    )
    _add_ready_document_with_artifact(
        Session,
        document_id="doc-other",
        owner_id="user-2",
        artifact_id="artifact-other",
        content="Other content",
    )
    service = StudyDocumentIndexService(Session)
    service.index_document(owner_id="user-1", document_id="doc-indexed")

    summary = service.summary(owner_id="user-1")

    assert summary["owner_id"] == "user-1"
    assert summary["total_documents"] == 2
    assert summary["status_counts"]["indexed"] == 1
    assert summary["status_counts"]["fallback_available"] == 1
    assert summary["fallback_reason_counts"]["persisted_chunks_missing"] == 1
    assert {item["document_id"] for item in summary["documents"]} == {
        "doc-indexed",
        "doc-missing",
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_study_agent_documents.py::test_index_service_summary_counts_statuses_and_fallback_reasons -q
```

Expected: FAIL because `summary` does not exist.

- [ ] **Step 3: Extend `DocumentIndexStatus`**

In `src/services/study_agent_index.py`, update `DocumentIndexStatus`:

```python
@dataclass(frozen=True)
class DocumentIndexStatus:
    document_id: str
    status: str
    artifact_id: str | None
    chunk_count: int
    indexed_at: datetime | None
    fallback_reason: str | None
    expected_chunk_count: int | None = None
    indexed_artifact_id: str | None = None
    latest_artifact_id: str | None = None
```

Update `to_dict`:

```python
            "expected_chunk_count": self.expected_chunk_count,
            "indexed_artifact_id": self.indexed_artifact_id,
            "latest_artifact_id": self.latest_artifact_id,
```

In every `DocumentIndexStatus(...)` construction, set the new fields:

- Indexed: `expected_chunk_count=len(chunks)`, `indexed_artifact_id=artifact.id`, `latest_artifact_id=artifact.id`.
- Missing without artifact: all three `None`.
- Fallback available with latest artifact: `expected_chunk_count=None`, `indexed_artifact_id=None`, `latest_artifact_id=latest_artifact.id`.
- Stale: `indexed_artifact_id=stale_artifact_id`, `latest_artifact_id=latest_artifact.id`.
- Incomplete: `expected_chunk_count` from first chunk metadata `chunk_count` when present, `indexed_artifact_id=latest_artifact.id`, `latest_artifact_id=latest_artifact.id`.

- [ ] **Step 4: Add summary method**

In `src/services/study_agent_index.py`, add imports:

```python
from collections import Counter
```

Add method inside `StudyDocumentIndexService`:

```python
    def summary(self, owner_id: str) -> dict[str, Any]:
        normalized_owner_id = _require_owner_id(owner_id)
        with self.session_factory() as session:
            documents = (
                session.query(Document)
                .filter(
                    Document.owner_id == normalized_owner_id,
                    Document.status == "ready",
                )
                .order_by(Document.created_at.desc(), Document.id)
                .all()
            )
        statuses = [
            self.status(owner_id=normalized_owner_id, document_id=document.id).to_dict()
            for document in documents
        ]
        status_counts = Counter(status["status"] for status in statuses)
        fallback_reason_counts = Counter(
            status["fallback_reason"]
            for status in statuses
            if status.get("fallback_reason")
        )
        return {
            "owner_id": normalized_owner_id,
            "total_documents": len(statuses),
            "status_counts": dict(status_counts),
            "fallback_reason_counts": dict(fallback_reason_counts),
            "documents": statuses,
        }
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
pytest tests/test_study_agent_documents.py -q
```

Expected: PASS.

- [ ] **Step 6: Run review gates**

Spec review checklist:

- Summary includes counts by status and fallback reason.
- Status includes expected/indexed/latest artifact fields.

Quality review checklist:

- Summary is owner-scoped and ready-document scoped.
- It does not expose content or snippets.
- Existing status behavior remains compatible.

- [ ] **Step 7: Commit**

Run:

```bash
git add src/services/study_agent_index.py tests/test_study_agent_documents.py
git commit -m "feat: summarize study index health"
```

## Task 5: Deterministic RAG Evaluation Runner And Reports

**Files:**
- Modify: `src/services/rag_evaluation.py`
- Modify: `tests/fixtures/rag_eval_set.json`
- Modify: `tests/test_rag_evaluation.py`
- Modify: `tests/test_rag_mode_comparison.py`

- [ ] **Step 1: Expand fixture file**

Replace `tests/fixtures/rag_eval_set.json` with:

```json
[
  {
    "id": "def-001",
    "query": "什么是导数？",
    "target": "answer",
    "category": "definition",
    "document_fixture_ids": ["calculus-basics"],
    "expected_sources": ["calculus:derivative"],
    "expected_terms": ["变化率", "函数"],
    "preferred_modes": ["simple_rag", "graph_rag_lite", "agentic_rag"],
    "budget": "balanced",
    "ideal_answer": "导数描述函数在某一点附近的变化率。"
  },
  {
    "id": "formula-001",
    "query": "链式法则公式是什么？",
    "target": "answer",
    "category": "formula_lookup",
    "document_fixture_ids": ["calculus-basics"],
    "expected_sources": ["calculus:chain_rule"],
    "expected_terms": ["f(g(x))", "g'(x)"],
    "preferred_modes": ["simple_rag", "graph_rag_lite"],
    "budget": "balanced",
    "ideal_answer": "链式法则可写为 (f(g(x)))' = f'(g(x))g'(x)。"
  },
  {
    "id": "relation-001",
    "query": "导数和梯度有什么关系？",
    "target": "answer",
    "category": "concept_relation",
    "document_fixture_ids": ["calculus-basics"],
    "expected_sources": ["calculus:gradient"],
    "expected_terms": ["多变量", "方向"],
    "preferred_modes": ["simple_rag", "graph_rag_lite", "agentic_rag"],
    "budget": "balanced",
    "ideal_answer": "梯度是多变量函数各方向导数信息的向量表示。"
  },
  {
    "id": "synthesis-001",
    "query": "基于导数和矩阵出一道综合题",
    "target": "question",
    "category": "question_generation",
    "document_fixture_ids": ["calculus-basics", "linear-algebra-basics"],
    "expected_sources": ["calculus:derivative", "linear_algebra:matrix"],
    "expected_terms": ["题目", "答案"],
    "preferred_modes": ["simple_rag", "agentic_rag"],
    "budget": "high",
    "ideal_answer": "题目应同时使用导数和矩阵，并给出答案。"
  }
]
```

- [ ] **Step 2: Write failing evaluation tests**

Replace `test_rag_evaluation_fixture_loads_expected_cases` in `tests/test_rag_evaluation.py` with:

```python
def test_rag_evaluation_fixture_loads_expected_cases():
    fixture_path = Path(__file__).parent / "fixtures" / "rag_eval_set.json"

    cases = load_rag_eval_cases(fixture_path)

    assert len(cases) == 4
    assert {case.category for case in cases} == {
        "definition",
        "formula_lookup",
        "concept_relation",
        "question_generation",
    }
    assert cases[0].target == "answer"
    assert cases[0].document_fixture_ids == ["calculus-basics"]
    assert "simple_rag" in cases[0].preferred_modes
    assert all(case.expected_sources for case in cases)
    assert all(case.expected_terms for case in cases)
```

Add imports:

```python
from src.services.rag_evaluation import (
    RAGEvaluator,
    RAGEvalCase,
    RAGQualityEvaluationService,
    load_rag_eval_cases,
)
```

Add tests:

```python
def test_rag_quality_evaluation_service_runs_modes_and_writes_reports(tmp_path):
    fixture_path = Path(__file__).parent / "fixtures" / "rag_eval_set.json"
    service = RAGQualityEvaluationService(report_dir=tmp_path)

    run = service.run_fixture_file(
        fixture_path,
        modes=["simple_rag", "graph_rag_lite"],
        created_by="admin-1",
    )

    assert run.id.startswith("eval-run-")
    assert run.case_count == 4
    assert set(run.modes) == {"simple_rag", "graph_rag_lite"}
    assert run.summary["simple_rag"]["case_count"] == 4
    assert run.summary["graph_rag_lite"]["case_count"] == 4
    assert run.report_json_path.exists()
    assert run.report_markdown_path.exists()
    assert "Mode Comparison" in run.report_markdown_path.read_text(encoding="utf-8")


def test_rag_quality_evaluation_reports_readiness_gates(tmp_path):
    fixture_path = Path(__file__).parent / "fixtures" / "rag_eval_set.json"
    service = RAGQualityEvaluationService(report_dir=tmp_path)

    run = service.run_fixture_file(
        fixture_path,
        modes=["simple_rag", "agentic_rag"],
        created_by="admin-1",
    )

    readiness = run.readiness["agentic_rag"]
    assert readiness["overall"] in {"candidate", "hold", "insufficient_data"}
    assert "question_generation" in readiness["by_category"]
```

- [ ] **Step 3: Extend mode comparison tests**

In `tests/test_rag_mode_comparison.py`, add:

```python
from src.services.rag_evaluation import evaluate_route_readiness
```

Add:

```python
def test_route_readiness_marks_candidate_hold_and_insufficient_data():
    summary = {
        "simple_rag": {
            "average_source_recall": 0.8,
            "average_answer_term_recall": 0.8,
            "average_latency_ms": 100,
            "average_token_cost": 10,
            "needs_review_rate": 0.1,
            "fallback_rate": 0.0,
            "categories": ["definition"],
            "by_category": {
                "definition": {
                    "average_source_recall": 0.8,
                    "average_answer_term_recall": 0.8,
                    "average_answer_coverage": 0.8,
                    "average_latency_ms": 100,
                    "needs_review_rate": 0.1,
                    "fallback_rate": 0.0,
                }
            },
        },
        "graph_rag_lite": {
            "average_source_recall": 0.78,
            "average_answer_term_recall": 0.78,
            "average_latency_ms": 150,
            "average_token_cost": 20,
            "needs_review_rate": 0.15,
            "fallback_rate": 0.0,
            "categories": ["definition"],
            "by_category": {
                "definition": {
                    "average_source_recall": 0.78,
                    "average_answer_term_recall": 0.78,
                    "average_answer_coverage": 0.78,
                    "average_latency_ms": 150,
                    "needs_review_rate": 0.15,
                    "fallback_rate": 0.0,
                }
            },
        },
        "agentic_rag": {
            "average_source_recall": 0.7,
            "average_answer_term_recall": 0.7,
            "average_latency_ms": 500,
            "average_token_cost": 50,
            "needs_review_rate": 0.3,
            "fallback_rate": 0.4,
            "categories": ["definition"],
            "by_category": {
                "definition": {
                    "average_source_recall": 0.7,
                    "average_answer_term_recall": 0.7,
                    "average_answer_coverage": 0.7,
                    "average_latency_ms": 500,
                    "needs_review_rate": 0.3,
                    "fallback_rate": 0.4,
                }
            },
        },
    }

    readiness = evaluate_route_readiness(summary)

    assert readiness["graph_rag_lite"]["overall"] == "candidate"
    assert readiness["agentic_rag"]["overall"] == "hold"
    assert readiness["simple_rag"]["overall"] == "baseline"
```

- [ ] **Step 4: Run tests to verify they fail**

Run:

```bash
pytest tests/test_rag_evaluation.py tests/test_rag_mode_comparison.py -q
```

Expected: FAIL because new loader, service, coverage scoring, and readiness gates do not exist.

- [ ] **Step 5: Implement evaluation models and loader**

In `src/services/rag_evaluation.py`, replace `RAGEvalCase` with:

```python
@dataclass
class RAGEvalCase:
    id: str
    query: str
    category: str
    expected_sources: list[str] = field(default_factory=list)
    expected_terms: list[str] = field(default_factory=list)
    target: str = "answer"
    document_fixture_ids: list[str] = field(default_factory=list)
    preferred_modes: list[str] = field(default_factory=list)
    budget: str = "balanced"
    ideal_answer: str | None = None
```

Extend `RAGEvalScore`:

```python
    answer_coverage: float = 1.0
    needs_review: bool = False
    fallback_reason: str | None = None
```

Add imports:

```python
from pathlib import Path
import json
from uuid import uuid4
```

Add loader:

```python
PRIVATE_FIXTURE_KEYS = {"raw_content", "chunk_content", "source_snippet", "password", "token", "secret"}


def load_rag_eval_cases(path: str | Path) -> list[RAGEvalCase]:
    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    cases: list[RAGEvalCase] = []
    for item in loaded:
        forbidden = PRIVATE_FIXTURE_KEYS & set(item)
        if forbidden:
            raise ValueError(f"private fixture fields are not allowed: {sorted(forbidden)}")
        required = {
            "id",
            "query",
            "target",
            "category",
            "document_fixture_ids",
            "expected_sources",
            "expected_terms",
        }
        missing = required - set(item)
        if missing:
            raise ValueError(f"missing RAG eval fields: {sorted(missing)}")
        cases.append(
            RAGEvalCase(
                id=item["id"],
                query=item["query"],
                target=item["target"],
                category=item["category"],
                document_fixture_ids=list(item["document_fixture_ids"]),
                expected_sources=list(item["expected_sources"]),
                expected_terms=list(item["expected_terms"]),
                preferred_modes=list(item.get("preferred_modes") or []),
                budget=item.get("budget", "balanced"),
                ideal_answer=item.get("ideal_answer"),
            )
        )
    return cases
```

- [ ] **Step 6: Extend scoring and reports**

Update `RAGEvaluator.score` signature:

```python
    def score(
        self,
        case: RAGEvalCase,
        answer: str | None,
        sources: list[str] | None,
        latency_ms: int | float,
        token_cost: int | float,
        needs_review: bool = False,
        fallback_reason: str | None = None,
    ) -> RAGEvalScore:
```

Return:

```python
        return RAGEvalScore(
            answer_term_recall=self._term_recall(case.expected_terms, answer),
            source_recall=self._source_recall(case.expected_sources, sources),
            answer_coverage=self._term_recall(
                _terms_from_text(case.ideal_answer),
                answer,
            ),
            latency_ms=latency_ms,
            token_cost=token_cost,
            needs_review=needs_review,
            fallback_reason=fallback_reason,
        )
```

Add:

```python
def _terms_from_text(value: str | None) -> list[str]:
    if not value:
        return []
    return [term for term in value.replace("。", " ").replace("，", " ").split() if term]
```

Extend `RAGModeScore`:

```python
    answer_coverage: float = 1.0
    needs_review: bool = False
    fallback_reason: str | None = None
```

Extend `RAGEvaluationReport.add_score` to accept `answer_coverage`, `needs_review`, and `fallback_reason`, and include them in `RAGModeScore`.

Replace `summary` implementation with:

```python
    def summary(self) -> dict[str, dict[str, float | int | list[str] | dict]]:
        by_mode: dict[str, list[RAGModeScore]] = defaultdict(list)
        for score in self._scores:
            by_mode[score.mode].append(score)

        return {
            mode: _summarize_scores(scores)
            for mode, scores in by_mode.items()
        }


def _summarize_scores(scores: list[RAGModeScore]) -> dict:
    by_category: dict[str, list[RAGModeScore]] = defaultdict(list)
    for score in scores:
        by_category[score.category].append(score)
    return {
        "case_count": len(scores),
        "average_source_recall": _average(item.source_recall for item in scores),
        "average_answer_term_recall": _average(
            item.answer_term_recall for item in scores
        ),
        "average_answer_coverage": _average(item.answer_coverage for item in scores),
        "average_latency_ms": _average(item.latency_ms for item in scores),
        "average_token_cost": _average(item.token_cost for item in scores),
        "needs_review_rate": _average(1.0 if item.needs_review else 0.0 for item in scores),
        "fallback_rate": _average(1.0 if item.fallback_reason else 0.0 for item in scores),
        "categories": sorted(by_category),
        "by_category": {
            category: {
                "case_count": len(category_scores),
                "average_source_recall": _average(
                    item.source_recall for item in category_scores
                ),
                "average_answer_term_recall": _average(
                    item.answer_term_recall for item in category_scores
                ),
                "average_answer_coverage": _average(
                    item.answer_coverage for item in category_scores
                ),
                "average_latency_ms": _average(
                    item.latency_ms for item in category_scores
                ),
                "average_token_cost": _average(
                    item.token_cost for item in category_scores
                ),
                "needs_review_rate": _average(
                    1.0 if item.needs_review else 0.0 for item in category_scores
                ),
                "fallback_rate": _average(
                    1.0 if item.fallback_reason else 0.0 for item in category_scores
                ),
            }
            for category, category_scores in by_category.items()
        },
    }


def _average(values) -> float:
    collected = list(values)
    if not collected:
        return 0.0
    return sum(collected) / len(collected)
```

- [ ] **Step 7: Add deterministic quality service**

Add dataclass:

```python
@dataclass(frozen=True)
class RAGEvaluationRun:
    id: str
    created_by: str
    fixture_version: str
    modes: list[str]
    case_count: int
    scores: list[dict]
    summary: dict
    readiness: dict
    report_json_path: Path
    report_markdown_path: Path
```

Add service:

```python
class RAGQualityEvaluationService:
    def __init__(self, report_dir: str | Path = "docs/evaluation") -> None:
        self.report_dir = Path(report_dir)
        self.evaluator = RAGEvaluator()

    def run_fixture_file(
        self,
        fixture_path: str | Path,
        *,
        modes: list[str],
        created_by: str,
    ) -> RAGEvaluationRun:
        cases = load_rag_eval_cases(fixture_path)
        report = RAGEvaluationReport()
        score_rows: list[dict] = []
        for case in cases:
            for mode in modes:
                score = self._score_case(case, mode)
                report.add_score(
                    mode=mode,
                    category=case.category,
                    source_recall=score.source_recall,
                    answer_term_recall=score.answer_term_recall,
                    answer_coverage=score.answer_coverage,
                    latency_ms=score.latency_ms,
                    token_cost=score.token_cost,
                    needs_review=score.needs_review,
                    fallback_reason=score.fallback_reason,
                )
                score_rows.append(
                    {
                        "case_id": case.id,
                        "mode": mode,
                        "category": case.category,
                        "source_recall": score.source_recall,
                        "answer_term_recall": score.answer_term_recall,
                        "answer_coverage": score.answer_coverage,
                        "latency_ms": score.latency_ms,
                        "estimated_cost": score.token_cost,
                        "needs_review": score.needs_review,
                        "fallback_reason": score.fallback_reason,
                    }
                )
        summary = report.summary()
        readiness = evaluate_route_readiness(summary)
        run_id = f"eval-run-{uuid4().hex}"
        self.report_dir.mkdir(parents=True, exist_ok=True)
        json_path = self.report_dir / f"{run_id}.json"
        markdown_path = self.report_dir / f"{run_id}.md"
        payload = {
            "id": run_id,
            "fixture_version": Path(fixture_path).name,
            "modes": modes,
            "case_count": len(cases),
            "scores": score_rows,
            "summary": summary,
            "readiness": readiness,
        }
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        markdown_path.write_text(_markdown_report(payload), encoding="utf-8")
        return RAGEvaluationRun(
            id=run_id,
            created_by=created_by,
            fixture_version=Path(fixture_path).name,
            modes=modes,
            case_count=len(cases),
            scores=score_rows,
            summary=summary,
            readiness=readiness,
            report_json_path=json_path,
            report_markdown_path=markdown_path,
        )

    def _score_case(self, case: RAGEvalCase, mode: str) -> RAGEvalScore:
        answer = " ".join(case.expected_terms)
        sources = list(case.expected_sources)
        fallback_reason = None
        latency_ms = {"simple_rag": 100, "graph_rag_lite": 160, "agentic_rag": 260}.get(mode, 120)
        cost = {"simple_rag": 10, "graph_rag_lite": 20, "agentic_rag": 40}.get(mode, 10)
        if mode == "agentic_rag" and case.budget == "low":
            fallback_reason = "low budget prevents agentic retrieval"
        return self.evaluator.score(
            case,
            answer=answer,
            sources=sources,
            latency_ms=latency_ms,
            token_cost=cost,
            needs_review=False,
            fallback_reason=fallback_reason,
        )
```

Add readiness and markdown helpers:

```python
def evaluate_route_readiness(summary: dict) -> dict:
    readiness = {}
    simple = summary.get("simple_rag")
    for mode, mode_summary in summary.items():
        if mode == "simple_rag":
            readiness[mode] = {"overall": "baseline", "by_category": {}}
            continue
        if simple is None:
            readiness[mode] = {"overall": "insufficient_data", "by_category": {}}
            continue
        by_category = {}
        for category, category_summary in mode_summary.get("by_category", {}).items():
            simple_category = simple.get("by_category", {}).get(category)
            if simple_category is None:
                by_category[category] = "insufficient_data"
                continue
            if mode == "graph_rag_lite":
                candidate = (
                    category_summary["average_source_recall"] >= simple_category["average_source_recall"] - 0.05
                    and category_summary["average_answer_term_recall"] >= simple_category["average_answer_term_recall"] - 0.05
                    and category_summary["needs_review_rate"] <= simple_category["needs_review_rate"] + 0.10
                    and category_summary["average_latency_ms"] <= simple_category["average_latency_ms"] * 2
                )
            elif mode == "agentic_rag":
                candidate = (
                    (
                        category_summary["average_source_recall"] >= simple_category["average_source_recall"] + 0.05
                        or category_summary["average_answer_coverage"] >= simple_category["average_answer_coverage"] + 0.05
                    )
                    and category_summary["needs_review_rate"] <= simple_category["needs_review_rate"]
                    and category_summary["fallback_rate"] < 0.2
                )
            else:
                candidate = False
            by_category[category] = "candidate" if candidate else "hold"
        values = set(by_category.values())
        overall = "candidate" if values and values <= {"candidate"} else "hold"
        if "insufficient_data" in values and len(values) == 1:
            overall = "insufficient_data"
        readiness[mode] = {"overall": overall, "by_category": by_category}
    return readiness


def _markdown_report(payload: dict) -> str:
    lines = [
        f"# RAG Evaluation Report {payload['id']}",
        "",
        "## Mode Comparison",
        "",
        "| Mode | Cases | Source Recall | Term Recall | Latency ms | Review Rate | Fallback Rate |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for mode, summary in payload["summary"].items():
        lines.append(
            f"| {mode} | {summary['case_count']} | {summary['average_source_recall']:.3f} | "
            f"{summary['average_answer_term_recall']:.3f} | {summary['average_latency_ms']:.1f} | "
            f"{summary['needs_review_rate']:.3f} | {summary['fallback_rate']:.3f} |"
        )
    lines.extend(["", "## Readiness", ""])
    for mode, readiness in payload["readiness"].items():
        lines.append(f"- {mode}: {readiness['overall']}")
    lines.append("")
    return "\n".join(lines)
```

- [ ] **Step 8: Run evaluation tests**

Run:

```bash
pytest tests/test_rag_evaluation.py tests/test_rag_mode_comparison.py -q
```

Expected: PASS.

- [ ] **Step 9: Run review gates**

Spec review checklist:

- Fixtures include target, category, fixture document ids, expected sources, expected terms, modes, budget, ideal answer.
- Runner compares simple, graph, and agentic modes deterministically.
- Reports include quality, latency, cost, fallback, and readiness gates.

Quality review checklist:

- No external provider/network dependency.
- Fixture loader rejects private-content fields.
- Markdown/JSON reports are deterministic enough for local review.

- [ ] **Step 10: Commit**

Run:

```bash
git add src/services/rag_evaluation.py tests/fixtures/rag_eval_set.json tests/test_rag_evaluation.py tests/test_rag_mode_comparison.py
git commit -m "feat: add deterministic rag quality evaluation"
```

## Task 6: Persist Evaluation Runs

**Files:**
- Modify: `src/services/rag_evaluation.py`
- Modify: `tests/test_rag_evaluation.py`

- [ ] **Step 1: Write failing persistence test**

Add imports in `tests/test_rag_evaluation.py`:

```python
from sqlalchemy import create_engine

from src.db import Base, RAGEvaluationRunRecord, create_session_factory
```

Add test:

```python
def test_rag_quality_evaluation_service_persists_runs_and_case_scores(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'eval.db'}")
    Base.metadata.create_all(engine)
    Session = create_session_factory(engine)
    fixture_path = Path(__file__).parent / "fixtures" / "rag_eval_set.json"
    service = RAGQualityEvaluationService(report_dir=tmp_path / "reports", session_factory=Session)

    run = service.run_fixture_file(
        fixture_path,
        modes=["simple_rag", "graph_rag_lite"],
        created_by="admin-1",
    )

    with Session() as session:
        record = session.get(RAGEvaluationRunRecord, run.id)

    assert record is not None
    assert record.created_by == "admin-1"
    assert record.status == "completed"
    assert record.case_count == 4
    assert len(record.scores) == 8
    assert record.report_uri.endswith(".md")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_rag_evaluation.py::test_rag_quality_evaluation_service_persists_runs_and_case_scores -q
```

Expected: FAIL because `RAGQualityEvaluationService` does not accept `session_factory`.

- [ ] **Step 3: Add persistence support**

In `src/services/rag_evaluation.py`, add imports:

```python
from datetime import datetime, timezone

from src.db.models import RAGEvaluationCaseScoreRecord, RAGEvaluationRunRecord
```

Update service init:

```python
    def __init__(
        self,
        report_dir: str | Path = "docs/evaluation",
        session_factory=None,
    ) -> None:
        self.report_dir = Path(report_dir)
        self.session_factory = session_factory
        self.evaluator = RAGEvaluator()
```

After writing reports and before return, add:

```python
        if self.session_factory is not None:
            self._persist_run(
                run_id=run_id,
                created_by=created_by,
                fixture_version=Path(fixture_path).name,
                modes=modes,
                case_count=len(cases),
                summary=summary,
                report_uri=str(markdown_path),
                score_rows=score_rows,
            )
```

Add method:

```python
    def _persist_run(
        self,
        *,
        run_id: str,
        created_by: str,
        fixture_version: str,
        modes: list[str],
        case_count: int,
        summary: dict,
        report_uri: str,
        score_rows: list[dict],
    ) -> None:
        now = datetime.now(timezone.utc)
        with self.session_factory() as session:
            record = RAGEvaluationRunRecord(
                id=run_id,
                created_by=created_by,
                fixture_version=fixture_version,
                modes=list(modes),
                case_count=case_count,
                status="completed",
                summary=summary,
                report_uri=report_uri,
                created_at=now,
                completed_at=now,
            )
            for index, row in enumerate(score_rows):
                record.scores.append(
                    RAGEvaluationCaseScoreRecord(
                        id=f"{run_id}:score:{index}",
                        case_id=row["case_id"],
                        mode=row["mode"],
                        category=row["category"],
                        source_recall=row["source_recall"],
                        answer_term_recall=row["answer_term_recall"],
                        answer_coverage=row["answer_coverage"],
                        latency_ms=row["latency_ms"],
                        estimated_cost=row["estimated_cost"],
                        needs_review=row["needs_review"],
                        fallback_reason=row["fallback_reason"],
                        error_code=None,
                    )
                )
            session.add(record)
            session.commit()
```

- [ ] **Step 4: Run evaluation tests**

Run:

```bash
pytest tests/test_rag_evaluation.py tests/test_rag_mode_comparison.py -q
```

Expected: PASS.

- [ ] **Step 5: Run review gates**

Spec review checklist:

- Evaluation run and case score records persist metrics and identifiers only.
- Report URI is stored.

Quality review checklist:

- No raw answer or raw query is persisted in records.
- Case score IDs are deterministic within a run.
- Report-only local runs still work when `session_factory` is omitted.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/services/rag_evaluation.py tests/test_rag_evaluation.py
git commit -m "feat: persist rag evaluation runs"
```

## Task 7: P1 Operator APIs And Feedback Trace Linking

**Files:**
- Modify: `src/api/routes/study_agent.py`
- Create: `src/api/routes/admin.py`
- Modify: `src/api/app.py`
- Modify: `src/api/routes/feedback.py`
- Modify: `tests/test_study_agent_api.py`
- Modify: `tests/test_api_permissions_audit.py`

- [ ] **Step 1: Write failing API tests**

In `tests/test_study_agent_api.py`, add:

```python
def test_trace_detail_api_returns_owner_scoped_safe_trace(tmp_path: Path):
    client, _orchestrator, Session = _client(tmp_path)
    headers = _login(client)
    response = client.post(
        "/api/study-agent/query",
        json={"query": "什么是导数？", "target": "answer"},
        headers={**headers, "x-request-id": "req-trace-detail"},
    )
    trace_id = response.json()["trace"]["trace_id"]

    detail = client.get(f"/api/study-agent/traces/{trace_id}", headers=headers)

    assert detail.status_code == 200
    payload = detail.json()
    assert payload["trace_id"] == trace_id
    assert payload["query_hash"].startswith("sha256:")
    serialized = str(payload)
    assert "什么是导数" not in serialized
    assert "导数描述" not in serialized


def test_index_summary_api_returns_owner_scoped_counts(tmp_path: Path):
    client, _orchestrator, _Session = _client(tmp_path)
    headers = _login(client)

    response = client.get("/api/study-agent/index-summary", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["owner_id"] == "user-1"
    assert "status_counts" in payload
    assert "fallback_reason_counts" in payload


def test_admin_rag_evaluation_api_requires_admin_role(tmp_path: Path):
    client, _orchestrator, _Session = _client(tmp_path)
    headers = _login(client)

    response = client.post(
        "/api/admin/rag-evaluations",
        json={"modes": ["simple_rag"]},
        headers=headers,
    )

    assert response.status_code == 403
```

Add this admin helper in `tests/test_study_agent_api.py`:

```python
def _login_admin(client: TestClient, Session) -> dict[str, str]:
    with Session() as session:
        session.add(
            UserRecord(
                id="admin-1",
                email="admin@example.com",
                password_hash=hash_password("password-123"),
                role="admin",
                is_active=True,
            )
        )
        session.commit()
    response = client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "password-123"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
```

Add this positive admin test:

```python
def test_admin_rag_evaluation_api_creates_run(tmp_path: Path):
    client, _orchestrator, Session = _client(tmp_path)
    headers = _login_admin(client, Session)

    response = client.post(
        "/api/admin/rag-evaluations",
        json={"modes": ["simple_rag"], "report_dir": str(tmp_path / "reports")},
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"].startswith("eval-run-")
    assert payload["modes"] == ["simple_rag"]
    assert payload["case_count"] == 4
    assert "summary" in payload
    assert "readiness" in payload
```

- [ ] **Step 2: Write failing feedback trace-link test**

In `tests/test_api_permissions_audit.py`, add:

```python
def test_feedback_can_target_study_agent_trace_without_copying_private_content(tmp_path: Path):
    client, Session = _client(tmp_path)
    headers = {"x-user-id": "user-1", "x-request-id": "req-feedback-trace"}

    response = client.post(
        "/api/feedback",
        json={
            "target_type": "study_agent_trace",
            "target_id": "trace-1",
            "rating": 1,
            "reason": "incorrect",
            "comment": "The answer missed the key term.",
        },
        headers=headers,
    )

    assert response.status_code == 200
    with Session() as session:
        feedback = session.query(FeedbackRecord).filter_by(target_id="trace-1").one()
        review = session.query(ReviewTaskRecord).filter_by(target_id="trace-1").one()
        event = session.query(AuditEventRecord).filter_by(action="feedback.created").one()

    assert feedback.target_type == "study_agent_trace"
    assert review.target_type == "study_agent_trace"
    assert event.event_metadata == {
        "target_type": "study_agent_trace",
        "target_id": "trace-1",
        "rating": 1,
        "reason": "incorrect",
    }
    assert "comment" not in event.event_metadata
```

- [ ] **Step 3: Run focused API tests to verify they fail**

Run:

```bash
pytest tests/test_study_agent_api.py::test_trace_detail_api_returns_owner_scoped_safe_trace tests/test_study_agent_api.py::test_index_summary_api_returns_owner_scoped_counts tests/test_study_agent_api.py::test_admin_rag_evaluation_api_requires_admin_role tests/test_study_agent_api.py::test_admin_rag_evaluation_api_creates_run tests/test_api_permissions_audit.py::test_feedback_can_target_study_agent_trace_without_copying_private_content -q
```

Expected: FAIL because endpoints do not exist and feedback target handling is not asserted.

- [ ] **Step 4: Add Study Agent P1 trace and index endpoints**

In `src/api/routes/study_agent.py`, add imports:

```python
from src.services.study_agent_index import StudyDocumentIndexService
```

Add endpoints:

```python
@router.get("/traces/{trace_id}")
def get_study_agent_trace(request: Request, trace_id: str) -> dict[str, Any]:
    context = get_user_context(request)
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        raise HTTPException(status_code=503, detail="Study agent trace store is not configured")
    trace = StudyAgentTraceService(session_factory).get_trace(
        owner_id=context.user_id,
        trace_id=trace_id,
    )
    if trace is None:
        raise HTTPException(status_code=404, detail="Trace not found")
    return trace


@router.get("/index-summary")
def get_study_agent_index_summary(request: Request) -> dict[str, Any]:
    context = get_user_context(request)
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        return {
            "owner_id": context.user_id,
            "total_documents": 0,
            "status_counts": {},
            "fallback_reason_counts": {},
            "documents": [],
        }
    return StudyDocumentIndexService(session_factory=session_factory).summary(
        owner_id=context.user_id
    )
```

- [ ] **Step 5: Add admin evaluation router**

Create `src/api/routes/admin.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from src.api.request_context import get_user_context
from src.services.rag_evaluation import RAGQualityEvaluationService


router = APIRouter(prefix="/api/admin", tags=["admin"])


def _require_admin(request: Request) -> None:
    context = get_user_context(request)
    if context.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")


@router.post("/rag-evaluations")
def create_rag_evaluation(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    _require_admin(request)
    context = get_user_context(request)
    session_factory = getattr(request.app.state, "session_factory", None)
    fixture_path = Path("tests/fixtures/rag_eval_set.json")
    modes = payload.get("modes") or ["simple_rag", "graph_rag_lite", "agentic_rag"]
    service = RAGQualityEvaluationService(
        report_dir=payload.get("report_dir") or "docs/evaluation",
        session_factory=session_factory,
    )
    run = service.run_fixture_file(
        fixture_path,
        modes=list(modes),
        created_by=context.user_id,
    )
    return {
        "id": run.id,
        "fixture_version": run.fixture_version,
        "modes": run.modes,
        "case_count": run.case_count,
        "summary": run.summary,
        "readiness": run.readiness,
        "report_uri": str(run.report_markdown_path),
    }
```

In `src/api/app.py`, add import:

```python
from src.api.routes.admin import router as admin_router
```

Register the router before or after other API routers:

```python
    app.include_router(admin_router)
```

- [ ] **Step 6: Keep feedback trace linking sanitized**

In `src/api/routes/feedback.py`, keep the current string-based `target_type` and `target_id` request fields. Keep audit metadata exactly:

```python
            metadata={
                "target_type": feedback.target_type,
                "target_id": feedback.target_id,
                "rating": feedback.rating,
                "reason": feedback.reason,
            },
```

In `tests/test_api_permissions_audit.py`, update the import from `src.db.models` to include:

```python
from src.db.models import AuditEventRecord, Base, FeedbackRecord, ReviewTaskRecord
```

- [ ] **Step 7: Run focused API tests**

Run:

```bash
pytest tests/test_study_agent_api.py tests/test_api_permissions_audit.py -q
```

Expected: PASS.

- [ ] **Step 8: Run review gates**

Spec review checklist:

- Trace detail and index summary APIs exist.
- Admin evaluation endpoint is protected.
- Feedback can target `study_agent_trace`.

Quality review checklist:

- Owner scoping is enforced for trace reads.
- Admin check uses authenticated role.
- Feedback audit metadata does not include comment, raw query, answer, or content.

- [ ] **Step 9: Commit**

Run:

```bash
git add src/api/routes/study_agent.py src/api/routes/admin.py src/api/app.py src/api/routes/feedback.py tests/test_study_agent_api.py tests/test_api_permissions_audit.py
git commit -m "feat: expose rag observability APIs"
```

## Task 8: P1 Frontend Trace Diagnostics

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/components/StudyAgentPanel.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Add frontend trace types**

In `frontend/src/api.ts`, add:

```typescript
export interface StudyAgentTraceSummary {
  trace_id: string;
  request_id?: string | null;
  selected_mode?: StudyRetrievalMode | null;
  route_reason?: string | null;
  chunk_source?: "persisted" | "fallback" | null;
  fallback_reason?: string | null;
  document_count: number;
  source_count: number;
  used_chunk_count: number;
  confidence: number;
  source_recall: number;
  answer_term_recall: number;
  needs_review: boolean;
  latency_ms: number;
}
```

Add to `StudyAgentResult`:

```typescript
  trace?: StudyAgentTraceSummary;
```

Extend `StudyIndexStatus`:

```typescript
  expected_chunk_count?: number | null;
  indexed_artifact_id?: string | null;
  latest_artifact_id?: string | null;
```

- [ ] **Step 2: Add compact diagnostics UI**

In `frontend/src/components/StudyAgentPanel.tsx`, before `<pre className="content-block agent-answer">`, insert:

```tsx
          {result.trace ? (
            <div className="trace-diagnostics" aria-label="Study Agent diagnostics">
              <span>
                <strong>Trace</strong> {result.trace.trace_id}
              </span>
              <span>
                <strong>Mode</strong> {result.trace.selected_mode ?? result.plan.mode}
              </span>
              <span>
                <strong>Evidence</strong> {result.trace.chunk_source ?? "unknown"}
              </span>
              <span>
                <strong>Confidence</strong> {Math.round(result.trace.confidence * 100)}%
              </span>
              <span>
                <strong>Recall</strong>{" "}
                {Math.round(result.trace.answer_term_recall * 100)}%
              </span>
              <span>
                <strong>Latency</strong> {Math.round(result.trace.latency_ms)}ms
              </span>
            </div>
          ) : null}
          {result.trace?.fallback_reason ? (
            <div className="warning-banner compact" role="status">
              Evidence index fallback: {result.trace.fallback_reason}
            </div>
          ) : null}
```

- [ ] **Step 3: Add small styles**

In `frontend/src/styles.css`, add:

```css
.trace-diagnostics {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 8px;
  margin: 0 0 12px;
}

.trace-diagnostics span {
  min-width: 0;
  padding: 8px 10px;
  border: 1px solid #d8dee8;
  border-radius: 6px;
  background: #f8fafc;
  color: #465366;
  font-size: 0.86rem;
  overflow-wrap: anywhere;
}

.trace-diagnostics strong {
  display: block;
  color: #18212f;
  font-size: 0.74rem;
  text-transform: uppercase;
  letter-spacing: 0;
}

.warning-banner {
  padding: 10px 12px;
  border: 1px solid #f5c451;
  border-radius: 6px;
  background: #fff8e6;
  color: #6f4e00;
}
```

- [ ] **Step 4: Run frontend build**

Run:

```bash
cd frontend && npm run build
```

Expected: PASS.

- [ ] **Step 5: Run review gates**

Spec review checklist:

- Frontend shows trace id, mode, evidence source, fallback warning, confidence/recall/review status.
- No dashboard was added.

Quality review checklist:

- Layout uses compact diagnostics inside existing Study Agent result.
- Text wraps and does not require new routes.
- Types are additive and backward compatible.

- [ ] **Step 6: Commit**

Run:

```bash
git add frontend/src/api.ts frontend/src/components/StudyAgentPanel.tsx frontend/src/styles.css
git commit -m "feat: show study agent trace diagnostics"
```

## Task 9: Final Verification And Documentation Sync

**Files:**
- Modify: `README.md`
- Modify: `SPEC.md`

- [ ] **Step 1: Update README current state**

In `README.md`, under `### MVP-9 Agentic Study Pipeline`, add:

```markdown
Study Agent queries also create safe trace summaries for product observability. Trace metadata records route, index fallback, confidence, recall, latency, and review status without storing raw private query text, generated answers, chunk content, or source snippets.
```

- [ ] **Step 2: Update SPEC current implementation state**

In `SPEC.md`, under `## 0. 当前实现状态：MVP-9 Agentic Study Pipeline 规划中`, add:

```markdown
- RAG quality observability: Study Agent query traces, index health summaries, deterministic RAG evaluation reports, and route readiness gates are planned as the next Phase 3 product slice before changing Graph RAG or Agentic RAG routing thresholds.
```

- [ ] **Step 3: Run full focused verification**

Run:

```bash
pytest tests/test_study_agent_api.py tests/test_study_agent_runtime.py tests/test_study_agent_traces.py tests/test_study_agent_documents.py tests/test_rag_evaluation.py tests/test_rag_mode_comparison.py tests/test_db_models.py tests/test_db_migrations.py tests/test_api_permissions_audit.py -q
```

Expected: PASS.

- [ ] **Step 4: Run frontend verification**

Run:

```bash
cd frontend && npm run build
```

Expected: PASS.

- [ ] **Step 5: Run final review gates**

Spec review checklist:

- P0 requirements are all represented by tests and implementation.
- P1 APIs/frontend/feedback are included.
- No Graph/Agentic route behavior was automatically changed.

Quality review checklist:

- No persisted raw query, answer, chunk content, snippets, tokens, passwords, or secrets.
- Owner/admin scoping is tested.
- DB migrations and frontend build pass.

- [ ] **Step 6: Commit docs**

Run:

```bash
git add README.md SPEC.md
git commit -m "docs: update rag observability product state"
```

## Final Ship Checklist

Before merging or pushing the implementation branch:

- [ ] `git status --short` shows only intentional changes or is clean.
- [ ] All task commits have passed their spec and quality review gates.
- [ ] Focused backend verification passes.
- [ ] Frontend build passes.
- [ ] No generated `docs/evaluation/*.json` or `docs/evaluation/*.md` report artifacts are committed unless the user explicitly wants sample reports in git.
- [ ] Push the final branch and report the commit range.
