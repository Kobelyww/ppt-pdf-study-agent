# Agent Collaboration, Memory, And Skills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Productize the Study Agent quality loop by linking Review Gate outcomes to review tasks, adding owner-scoped safe memory, adding a versioned skill registry, and cleaning up legacy agent status semantics.

**Architecture:** Keep `StudyAgentRuntimeService` and the deterministic workflow supervisor as the product mainline. Add narrow services for review task linking, memory, and skill selection; expose only compact safe metadata through API and frontend diagnostics. Keep bounded expert collaboration out of this Phase 1 implementation because the spec requires review-task, memory, and skill contracts to stabilize first.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy/Alembic, pytest, React/Vite/TypeScript.

---

## Phase 1 Scope

This plan implements:

- P0 Review Gate to persisted review task loop.
- P1 product memory foundation and safe memory summary API.
- P1 versioned Study Skill Registry and skill diagnostics.
- P2 legacy agent boundary cleanup.
- Documentation and verification sync.

This plan intentionally does not implement bounded parallel expert branches. That gets a follow-up plan after review task, memory, and skill metadata contracts are stable.

## File Structure

- `src/db/models.py`: add review task metadata and `StudyAgentMemoryRecord`.
- `src/db/migrations/versions/0005_review_task_metadata.py`: add review task metadata and idempotency lookup index.
- `src/db/migrations/versions/0006_study_agent_memories.py`: add owner-scoped memory table and indexes.
- `src/services/study_agent_review_tasks.py`: create or link safe review tasks from Study Agent results.
- `src/services/study_agent_memory.py`: product memory schemas, sanitizer, store/recall/delete service.
- `src/services/study_agent_skills.py`: versioned skill registry and deterministic skill selection.
- `src/services/study_agent.py`: add optional skill fields to `StudyRequest`, `StudyAgentResult.audit_metadata`, and generator metadata.
- `src/services/study_agent_runtime.py`: add skill selection and memory update summaries to safe workflow metadata.
- `src/services/study_agent_workflow.py`: allow new safe stage labels and metadata keys.
- `src/services/study_agent_trace.py`: persist safe skill, memory, and review task labels/counts.
- `src/api/routes/study_agent.py`: wire review task creation, memory summary/delete endpoints, and skill endpoints.
- `src/api/routes/review.py`: write safe `review_outcome` memory after review decisions.
- `src/agents/base_agent.py`: fix failed-result status semantics and structured error fields.
- `src/coordinator/main_coordinator.py`: keep legacy coordinator output safe and explicit.
- `frontend/src/api.ts`: add review task, skill, and memory API types.
- `frontend/src/components/StudyAgentPanel.tsx`: show compact skill/review task/memory diagnostics.
- `frontend/src/pages/ReviewTasksPage.tsx`: display safe review task metadata when present.
- `frontend/src/styles.css`: compact diagnostic styling.
- Tests:
  - `tests/test_study_agent_review_tasks.py`
  - `tests/test_study_agent_memory.py`
  - `tests/test_study_agent_skills.py`
  - extend `tests/test_study_agent_api.py`
  - extend `tests/test_study_agent_runtime.py`
  - extend `tests/test_study_agent_traces.py`
  - extend `tests/test_agents.py`
  - extend `tests/test_coordinator.py`
  - extend `tests/test_db_models.py`
  - extend `tests/test_db_migrations.py`

## Task 1: Review Task Metadata Schema

**Files:**
- Modify: `src/db/models.py`
- Create: `src/db/migrations/versions/0005_review_task_metadata.py`
- Test: `tests/test_db_models.py`
- Test: `tests/test_db_migrations.py`

- [ ] **Step 1: Write failing model tests**

Append tests to `tests/test_db_models.py`:

```python
def test_review_task_record_accepts_safe_metadata(db_session):
    from src.db.models import ReviewTaskRecord

    task = ReviewTaskRecord(
        id="review-workflow-1",
        owner_id="owner-1",
        target_type="study_agent_workflow",
        target_id="workflow-0123456789abcdef0123456789abcdef",
        status="open",
        reason="low_confidence",
        task_metadata={
            "workflow_id": "workflow-0123456789abcdef0123456789abcdef",
            "trace_id": "trace-abc",
            "selected_mode": "simple_rag",
            "review_reasons": ["low_confidence"],
            "confidence": 0.2,
            "source_count": 1,
            "chunk_count": 1,
            "citation_count": 0,
            "issue_count": 1,
        },
    )
    db_session.add(task)
    db_session.commit()

    stored = db_session.get(ReviewTaskRecord, "review-workflow-1")
    assert stored.task_metadata["workflow_id"] == "workflow-0123456789abcdef0123456789abcdef"
    assert stored.task_metadata["review_reasons"] == ["low_confidence"]
    assert "raw query" not in str(stored.task_metadata).lower()
```

- [ ] **Step 2: Run the failing model test**

Run:

```bash
pytest tests/test_db_models.py::test_review_task_record_accepts_safe_metadata -q
```

Expected: FAIL because `ReviewTaskRecord` has no `task_metadata` field.

- [ ] **Step 3: Add review task metadata model field**

Modify `src/db/models.py` `ReviewTaskRecord`:

```python
class ReviewTaskRecord(Base):
    __tablename__ = "review_tasks"
    __table_args__ = (
        Index(
            "ix_review_tasks_owner_target_status",
            "owner_id",
            "target_type",
            "target_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    reason: Mapped[str] = mapped_column(String(128), nullable=False)
    assignee: Mapped[Optional[str]] = mapped_column(String(255))
    decision: Mapped[Optional[str]] = mapped_column(String(64))
    comment: Mapped[Optional[str]] = mapped_column(Text)
    task_metadata: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
```

- [ ] **Step 4: Add Alembic migration**

Create `src/db/migrations/versions/0005_review_task_metadata.py`:

```python
"""Add review task metadata.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-06
"""

from alembic import op
import sqlalchemy as sa


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "review_tasks",
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.create_index(
        "ix_review_tasks_owner_target_status",
        "review_tasks",
        ["owner_id", "target_type", "target_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_review_tasks_owner_target_status", table_name="review_tasks")
    op.drop_column("review_tasks", "metadata")
```

- [ ] **Step 5: Run schema tests**

Run:

```bash
pytest tests/test_db_models.py::test_review_task_record_accepts_safe_metadata tests/test_db_migrations.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit schema change**

Run:

```bash
git add src/db/models.py src/db/migrations/versions/0005_review_task_metadata.py tests/test_db_models.py tests/test_db_migrations.py
git commit -m "feat: add review task metadata schema"
```

- [ ] **Step 7: Run required reviews**

Run Spec review and Quality review for Task 1 before continuing.

## Task 2: Study Agent Review Task Loop

**Files:**
- Create: `src/services/study_agent_review_tasks.py`
- Modify: `src/api/routes/study_agent.py`
- Modify: `src/api/routes/review.py`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/components/StudyAgentPanel.tsx`
- Modify: `frontend/src/pages/ReviewTasksPage.tsx`
- Modify: `frontend/src/styles.css`
- Test: `tests/test_study_agent_review_tasks.py`
- Test: `tests/test_study_agent_api.py`

- [ ] **Step 1: Write failing service tests**

Create `tests/test_study_agent_review_tasks.py` with:

```python
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base, ReviewTaskRecord
from src.services.study_agent_review_tasks import (
    StudyAgentReviewTaskService,
    safe_review_task_metadata,
)


def _session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def test_safe_review_task_metadata_omits_raw_content():
    metadata = safe_review_task_metadata(
        workflow={
            "workflow_id": "workflow-0123456789abcdef0123456789abcdef",
            "status": "needs_review",
            "stages": [
                {
                    "stage": "review_gate",
                    "status": "needs_review",
                    "review_reason": "low_confidence",
                    "output_summary": {
                        "needs_review": True,
                        "review_reason": "low_confidence",
                        "query": "raw private question",
                        "chunk_content": "raw chunk text",
                    },
                }
            ],
        },
        trace_payload={
            "trace_id": "trace-1",
            "selected_mode": "simple_rag",
            "confidence": 0.2,
            "source_recall": 1.0,
            "answer_term_recall": 0.0,
        },
        result_audit_metadata={
            "source_count": 1,
            "chunk_count": 1,
        },
    )

    serialized = str(metadata).lower()
    assert metadata["workflow_id"] == "workflow-0123456789abcdef0123456789abcdef"
    assert metadata["review_reasons"] == ["low_confidence"]
    assert "raw private question" not in serialized
    assert "raw chunk text" not in serialized


def test_ensure_review_task_is_idempotent_for_owner_workflow():
    Session = _session_factory()
    service = StudyAgentReviewTaskService(Session)
    workflow = {
        "workflow_id": "workflow-0123456789abcdef0123456789abcdef",
        "status": "needs_review",
        "needs_review": True,
        "stages": [
            {
                "stage": "review_gate",
                "status": "needs_review",
                "review_reason": "low_confidence",
                "output_summary": {"review_reason": "low_confidence"},
            }
        ],
    }

    first = service.ensure_for_workflow(
        owner_id="owner-1",
        request_id="req-1",
        workflow=workflow,
        trace_payload={"trace_id": "trace-1", "selected_mode": "simple_rag"},
        result_audit_metadata={"source_count": 1, "chunk_count": 1},
    )
    second = service.ensure_for_workflow(
        owner_id="owner-1",
        request_id="req-1",
        workflow=workflow,
        trace_payload={"trace_id": "trace-1", "selected_mode": "simple_rag"},
        result_audit_metadata={"source_count": 1, "chunk_count": 1},
    )

    assert first["id"] == second["id"]
    with Session() as session:
        assert session.query(ReviewTaskRecord).count() == 1
```

- [ ] **Step 2: Run failing service tests**

Run:

```bash
pytest tests/test_study_agent_review_tasks.py -q
```

Expected: FAIL because `src.services.study_agent_review_tasks` does not exist.

- [ ] **Step 3: Implement review task service**

Create `src/services/study_agent_review_tasks.py`:

```python
from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import select

from src.db.models import ReviewTaskRecord, utc_now


_SAFE_REVIEW_REASONS = {
    "verification_failed",
    "low_confidence",
    "missing_citations",
    "empty_evidence",
    "policy_blocked_without_fallback",
    "target_used_fallback_evidence",
    "agentic_step_budget_exhausted",
}
_SAFE_MODES = {"simple_rag", "graph_rag_lite", "agentic_rag"}
_SAFE_STATUSES = {"needs_review", "completed_with_fallback", "failed", "partial"}


def workflow_needs_review(workflow: dict[str, Any] | None) -> bool:
    if not isinstance(workflow, dict):
        return False
    if workflow.get("needs_review") is True:
        return True
    if workflow.get("status") == "needs_review":
        return True
    for stage in workflow.get("stages") or []:
        if isinstance(stage, dict) and stage.get("stage") == "review_gate":
            return stage.get("status") == "needs_review"
    return False


def review_reasons_from_workflow(workflow: dict[str, Any] | None) -> list[str]:
    reasons: list[str] = []
    if not isinstance(workflow, dict):
        return reasons
    for stage in workflow.get("stages") or []:
        if not isinstance(stage, dict):
            continue
        for candidate in (
            stage.get("review_reason"),
            (stage.get("output_summary") or {}).get("review_reason")
            if isinstance(stage.get("output_summary"), dict)
            else None,
        ):
            if isinstance(candidate, str) and candidate in _SAFE_REVIEW_REASONS:
                reasons.append(candidate)
    return list(dict.fromkeys(reasons))


def safe_review_task_metadata(
    *,
    workflow: dict[str, Any],
    trace_payload: dict[str, Any] | None,
    result_audit_metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    trace_payload = trace_payload or {}
    result_audit_metadata = result_audit_metadata or {}
    reasons = review_reasons_from_workflow(workflow)
    metadata: dict[str, Any] = {
        "workflow_id": workflow.get("workflow_id"),
        "trace_id": trace_payload.get("trace_id"),
        "request_id": trace_payload.get("request_id"),
        "workflow_status": workflow.get("status") if workflow.get("status") in _SAFE_STATUSES else None,
        "selected_mode": trace_payload.get("selected_mode")
        if trace_payload.get("selected_mode") in _SAFE_MODES
        else None,
        "review_reasons": reasons,
        "confidence": _safe_float(trace_payload.get("confidence")),
        "source_recall": _safe_float(trace_payload.get("source_recall")),
        "answer_term_recall": _safe_float(trace_payload.get("answer_term_recall")),
        "source_count": _safe_int(result_audit_metadata.get("source_count")),
        "chunk_count": _safe_int(result_audit_metadata.get("chunk_count")),
        "citation_count": _safe_int(result_audit_metadata.get("citation_count")),
        "issue_count": _safe_int(result_audit_metadata.get("issue_count")),
    }
    return {key: value for key, value in metadata.items() if value not in (None, [], "")}


class StudyAgentReviewTaskService:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    def ensure_for_workflow(
        self,
        *,
        owner_id: str,
        request_id: str,
        workflow: dict[str, Any] | None,
        trace_payload: dict[str, Any] | None,
        result_audit_metadata: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if not workflow_needs_review(workflow):
            return None
        workflow_id = str((workflow or {}).get("workflow_id") or "").strip()
        if not workflow_id:
            return None

        with self.session_factory() as session:
            existing = session.scalar(
                select(ReviewTaskRecord).where(
                    ReviewTaskRecord.owner_id == owner_id,
                    ReviewTaskRecord.target_type == "study_agent_workflow",
                    ReviewTaskRecord.target_id == workflow_id,
                    ReviewTaskRecord.status == "open",
                )
            )
            if existing is not None:
                return _review_task_summary(existing)

            metadata = safe_review_task_metadata(
                workflow=workflow or {},
                trace_payload=trace_payload,
                result_audit_metadata=result_audit_metadata,
            )
            reasons = metadata.get("review_reasons") or ["verification_failed"]
            record = ReviewTaskRecord(
                id=f"review-{uuid4().hex}",
                owner_id=owner_id,
                target_type="study_agent_workflow",
                target_id=workflow_id,
                status="open",
                reason=reasons[0],
                task_metadata=metadata,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return _review_task_summary(record)


def _review_task_summary(record: ReviewTaskRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "target_type": record.target_type,
        "target_id": record.target_id,
        "status": record.status,
        "reason": record.reason,
        "metadata": record.task_metadata or {},
    }


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float | None:
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return None
```

- [ ] **Step 4: Run service tests**

Run:

```bash
pytest tests/test_study_agent_review_tasks.py -q
```

Expected: PASS.

- [ ] **Step 5: Wire review task creation into Study Agent API**

Modify `src/api/routes/study_agent.py` imports:

```python
from src.services.study_agent_review_tasks import StudyAgentReviewTaskService
```

In `query_study_agent`, after `_record_study_agent_audit(...)`, add:

```python
    review_task_payload = _ensure_study_agent_review_task(
        request,
        actor_id=context.user_id,
        request_id=context.request_id,
        result=result,
        trace_payload=trace_payload,
    )
```

Before returning `response_payload`, add:

```python
    if review_task_payload is not None:
        response_payload["review_task"] = review_task_payload
```

Add helper:

```python
def _ensure_study_agent_review_task(
    request: Request,
    *,
    actor_id: str,
    request_id: str,
    result: Any,
    trace_payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        return None
    audit_metadata = getattr(result, "audit_metadata", {}) or {}
    workflow = sanitize_workflow_payload(audit_metadata.get("workflow"))
    payload = StudyAgentReviewTaskService(
        _non_expiring_session_factory(session_factory)
    ).ensure_for_workflow(
        owner_id=actor_id,
        request_id=request_id,
        workflow=workflow,
        trace_payload=trace_payload,
        result_audit_metadata=audit_metadata,
    )
    if payload is not None:
        record_audit_event(
            session_factory=session_factory,
            actor_id=actor_id,
            action="review_task.created",
            resource_type="review_task",
            resource_id=payload["id"],
            request_id=request_id,
            metadata={
                "target_type": payload["target_type"],
                "target_id": payload["target_id"],
                "reason": payload["reason"],
                "workflow_id": (payload.get("metadata") or {}).get("workflow_id"),
                "trace_id": (payload.get("metadata") or {}).get("trace_id"),
            },
        )
    return payload
```

- [ ] **Step 6: Add API tests**

Append to `tests/test_study_agent_api.py`:

```python
def test_study_agent_query_creates_review_task_for_needs_review_workflow(tmp_path):
    workflow_id = new_workflow_id()
    client, orchestrator, Session = _client(tmp_path)
    app = client.app
    app.state.study_agent_orchestrator = WorkflowStudyAgentOrchestrator(workflow_id=workflow_id)

    response = client.post(
        "/api/study-agent/query",
        headers={"Authorization": "Bearer " + _token_for_user("user-1")},
        json={"query": "什么是导数？", "target": "answer", "document_ids": []},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["review_task"]["target_id"] == workflow_id
    assert payload["review_task"]["reason"] in {"low_confidence", "verification_failed"}
    serialized = str(payload["review_task"]).lower()
    assert "什么是导数" not in serialized
    assert "导数原文" not in serialized


def test_study_agent_query_review_task_is_idempotent(tmp_path):
    workflow_id = new_workflow_id()
    client, orchestrator, Session = _client(tmp_path)
    client.app.state.study_agent_orchestrator = WorkflowStudyAgentOrchestrator(workflow_id=workflow_id)
    headers = {"Authorization": "Bearer " + _token_for_user("user-1")}
    body = {"query": "什么是导数？", "target": "answer", "document_ids": []}

    first = client.post("/api/study-agent/query", headers=headers, json=body)
    second = client.post("/api/study-agent/query", headers=headers, json=body)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["review_task"]["id"] == second.json()["review_task"]["id"]
```

If `_token_for_user` is not present in this test file, add a local helper that logs in through `/api/auth/login` or reuse the file's existing auth helper.

- [ ] **Step 7: Add frontend types and compact status**

Modify `frontend/src/api.ts`:

```ts
export interface StudyAgentReviewTaskDiagnostic {
  id: string;
  target_type: string;
  target_id: string;
  status: string;
  reason: string;
  metadata?: Record<string, unknown>;
}

export interface StudyAgentResult {
  // existing fields stay unchanged
  review_task?: StudyAgentReviewTaskDiagnostic | null;
}
```

Modify `frontend/src/components/StudyAgentPanel.tsx` below workflow timeline:

```tsx
          {result.review_task ? (
            <div className="study-agent-review-task" role="status">
              <span>
                <strong>Review task</strong> {result.review_task.status}
              </span>
              <span>{result.review_task.reason}</span>
            </div>
          ) : null}
```

Modify `frontend/src/styles.css`:

```css
.study-agent-review-task {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  color: #92400e;
  font-size: 0.85rem;
}

.study-agent-review-task span {
  min-width: 0;
  padding: 6px 9px;
  border: 1px solid #f5c451;
  border-radius: 6px;
  background: #fff8e6;
  overflow-wrap: anywhere;
}
```

- [ ] **Step 8: Run Task 2 verification**

Run:

```bash
pytest tests/test_study_agent_review_tasks.py tests/test_study_agent_api.py -q
cd frontend && npm run build
```

Expected: PASS.

- [ ] **Step 9: Commit review task loop**

Run:

```bash
git add src/services/study_agent_review_tasks.py src/api/routes/study_agent.py src/api/routes/review.py frontend/src/api.ts frontend/src/components/StudyAgentPanel.tsx frontend/src/pages/ReviewTasksPage.tsx frontend/src/styles.css tests/test_study_agent_review_tasks.py tests/test_study_agent_api.py
git commit -m "feat: link study agent review tasks"
```

- [ ] **Step 10: Run required reviews**

Run Spec review and Quality review for Task 2 before continuing.

## Task 3: Product Memory Schema And Service

**Files:**
- Modify: `src/db/models.py`
- Modify: `src/db/__init__.py`
- Create: `src/db/migrations/versions/0006_study_agent_memories.py`
- Create: `src/services/study_agent_memory.py`
- Test: `tests/test_study_agent_memory.py`
- Test: `tests/test_db_models.py`
- Test: `tests/test_db_migrations.py`

- [ ] **Step 1: Write failing memory service tests**

Create `tests/test_study_agent_memory.py`:

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base
from src.services.study_agent_memory import StudyAgentMemoryService


def _session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def test_memory_store_and_recall_is_owner_scoped():
    Session = _session_factory()
    service = StudyAgentMemoryService(Session)
    service.store_preference(
        owner_id="owner-1",
        key="answer_style",
        value="concise",
        source_id="settings",
    )
    service.store_preference(
        owner_id="owner-2",
        key="answer_style",
        value="detailed",
        source_id="settings",
    )

    summary = service.summary(owner_id="owner-1")

    assert summary["preferences"]["answer_style"] == "concise"
    assert "detailed" not in str(summary)


def test_memory_rejects_raw_content_like_values():
    Session = _session_factory()
    service = StudyAgentMemoryService(Session)

    record_id = service.store_review_outcome(
        owner_id="owner-1",
        workflow_id="workflow-0123456789abcdef0123456789abcdef",
        review_task_id="review-1",
        reasons=["low_confidence"],
        decision="accepted",
        metadata={
            "query": "raw private query",
            "chunk_content": "raw chunk text",
            "token": "sk-secret",
            "confidence": 0.2,
        },
    )

    summary = service.summary(owner_id="owner-1")
    serialized = str(summary).lower()
    assert record_id.startswith("memory-")
    assert "low_confidence" in serialized
    assert "raw private query" not in serialized
    assert "raw chunk text" not in serialized
    assert "sk-secret" not in serialized


def test_expired_memory_is_not_recalled():
    Session = _session_factory()
    service = StudyAgentMemoryService(Session)
    service.store_preference(
        owner_id="owner-1",
        key="answer_style",
        value="concise",
        source_id="settings",
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )

    assert service.summary(owner_id="owner-1")["preferences"] == {}
```

- [ ] **Step 2: Run failing memory tests**

Run:

```bash
pytest tests/test_study_agent_memory.py -q
```

Expected: FAIL because `StudyAgentMemoryService` does not exist.

- [ ] **Step 3: Add memory model**

Modify `src/db/models.py` after `StudyAgentTraceRecord`:

```python
class StudyAgentMemoryRecord(Base):
    __tablename__ = "study_agent_memories"
    __table_args__ = (
        Index("ix_study_agent_memories_owner_category", "owner_id", "category"),
        Index("ix_study_agent_memories_owner_scope", "owner_id", "scope_type", "scope_id"),
        Index("ix_study_agent_memories_owner_key", "owner_id", "category", "key"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_id: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    value_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    privacy_level: Mapped[str] = mapped_column(String(32), nullable=False, default="safe_metadata")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
```

Modify `src/db/__init__.py` imports and `__all__` to include `StudyAgentMemoryRecord`.

- [ ] **Step 4: Add memory migration**

Create `src/db/migrations/versions/0006_study_agent_memories.py`:

```python
"""Add study agent memories.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-06
"""

from alembic import op
import sqlalchemy as sa


revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "study_agent_memories",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("scope_id", sa.String(length=128), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("privacy_level", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_study_agent_memories_owner_category",
        "study_agent_memories",
        ["owner_id", "category"],
    )
    op.create_index(
        "ix_study_agent_memories_owner_scope",
        "study_agent_memories",
        ["owner_id", "scope_type", "scope_id"],
    )
    op.create_index(
        "ix_study_agent_memories_owner_key",
        "study_agent_memories",
        ["owner_id", "category", "key"],
    )


def downgrade() -> None:
    op.drop_index("ix_study_agent_memories_owner_key", table_name="study_agent_memories")
    op.drop_index("ix_study_agent_memories_owner_scope", table_name="study_agent_memories")
    op.drop_index("ix_study_agent_memories_owner_category", table_name="study_agent_memories")
    op.drop_table("study_agent_memories")
```

- [ ] **Step 5: Implement memory service**

Create `src/services/study_agent_memory.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from src.db.models import StudyAgentMemoryRecord, utc_now


_PREFERENCE_VALUES = {
    "answer_style": {"concise", "detailed", "exam_focused", "bilingual"},
    "difficulty": {"basic", "intermediate", "advanced"},
    "language": {"zh", "en", "bilingual"},
}
_SAFE_REVIEW_REASONS = {
    "verification_failed",
    "low_confidence",
    "missing_citations",
    "empty_evidence",
    "policy_blocked_without_fallback",
    "target_used_fallback_evidence",
    "agentic_step_budget_exhausted",
}
_SAFE_DECISIONS = {"accepted", "rejected", "needs_revision", "resolved"}


class StudyAgentMemoryService:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    def store_preference(
        self,
        *,
        owner_id: str,
        key: str,
        value: str,
        source_id: str,
        expires_at: datetime | None = None,
    ) -> str:
        if value not in _PREFERENCE_VALUES.get(key, set()):
            raise ValueError("unsupported preference value")
        return self._store(
            owner_id=owner_id,
            scope_type="user",
            scope_id=owner_id,
            category="user_preference",
            key=key,
            value_json={"value": value},
            confidence=1.0,
            source_type="explicit_preference",
            source_id=source_id,
            expires_at=expires_at,
        )

    def store_review_outcome(
        self,
        *,
        owner_id: str,
        workflow_id: str,
        review_task_id: str,
        reasons: list[str],
        decision: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        safe_reasons = [reason for reason in reasons if reason in _SAFE_REVIEW_REASONS]
        safe_decision = decision if decision in _SAFE_DECISIONS else "resolved"
        safe_metadata = {
            "confidence": _safe_float((metadata or {}).get("confidence")),
            "source_count": _safe_int((metadata or {}).get("source_count")),
            "chunk_count": _safe_int((metadata or {}).get("chunk_count")),
        }
        return self._store(
            owner_id=owner_id,
            scope_type="workflow",
            scope_id=workflow_id,
            category="review_outcome",
            key=review_task_id,
            value_json={
                "workflow_id": workflow_id,
                "review_task_id": review_task_id,
                "review_reasons": safe_reasons,
                "decision": safe_decision,
                "metrics": {
                    key: value
                    for key, value in safe_metadata.items()
                    if value is not None
                },
            },
            confidence=1.0,
            source_type="review_task",
            source_id=review_task_id,
        )

    def summary(self, *, owner_id: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        with self.session_factory() as session:
            records = session.scalars(
                select(StudyAgentMemoryRecord).where(
                    StudyAgentMemoryRecord.owner_id == owner_id,
                )
            ).all()

        active = [
            record
            for record in records
            if record.expires_at is None or record.expires_at > now
        ]
        preferences: dict[str, str] = {}
        review_reason_counts: dict[str, int] = {}
        for record in active:
            value = record.value_json or {}
            if record.category == "user_preference":
                preference = value.get("value")
                if isinstance(preference, str):
                    preferences[record.key] = preference
            if record.category == "review_outcome":
                for reason in value.get("review_reasons") or []:
                    if reason in _SAFE_REVIEW_REASONS:
                        review_reason_counts[reason] = review_reason_counts.get(reason, 0) + 1
        return {
            "preferences": preferences,
            "review_reason_counts": review_reason_counts,
            "memory_record_count": len(active),
        }

    def delete_memory(self, *, owner_id: str, memory_id: str) -> bool:
        with self.session_factory() as session:
            record = session.get(StudyAgentMemoryRecord, memory_id)
            if record is None or record.owner_id != owner_id:
                return False
            session.delete(record)
            session.commit()
            return True

    def _store(
        self,
        *,
        owner_id: str,
        scope_type: str,
        scope_id: str,
        category: str,
        key: str,
        value_json: dict[str, Any],
        confidence: float,
        source_type: str,
        source_id: str,
        expires_at: datetime | None = None,
    ) -> str:
        record = StudyAgentMemoryRecord(
            id=f"memory-{uuid4().hex}",
            owner_id=owner_id,
            scope_type=scope_type,
            scope_id=scope_id,
            category=category,
            key=key,
            value_json=value_json,
            confidence=confidence,
            source_type=source_type,
            source_id=source_id,
            privacy_level="safe_metadata",
            created_at=utc_now(),
            updated_at=utc_now(),
            expires_at=expires_at,
        )
        with self.session_factory() as session:
            session.add(record)
            session.commit()
        return record.id


def _safe_int(value: Any) -> int | None:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> float | None:
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return None
```

- [ ] **Step 6: Run memory and migration tests**

Run:

```bash
pytest tests/test_study_agent_memory.py tests/test_db_models.py tests/test_db_migrations.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit memory foundation**

Run:

```bash
git add src/db/models.py src/db/__init__.py src/db/migrations/versions/0006_study_agent_memories.py src/services/study_agent_memory.py tests/test_study_agent_memory.py tests/test_db_models.py tests/test_db_migrations.py
git commit -m "feat: add study agent memory foundation"
```

- [ ] **Step 8: Run required reviews**

Run Spec review and Quality review for Task 3 before continuing.

## Task 4: Memory API And Review Decision Integration

**Files:**
- Modify: `src/api/routes/study_agent.py`
- Modify: `src/api/routes/review.py`
- Modify: `frontend/src/api.ts`
- Test: `tests/test_study_agent_api.py`
- Test: `tests/test_mvp7_product_loop.py`

- [ ] **Step 1: Write failing API tests**

Append to `tests/test_study_agent_api.py`:

```python
def test_memory_summary_endpoint_is_owner_scoped(tmp_path):
    client, orchestrator, Session = _client(tmp_path)
    with Session() as session:
        from src.db.models import StudyAgentMemoryRecord, utc_now

        session.add(
            StudyAgentMemoryRecord(
                id="memory-owner-1",
                owner_id="user-1",
                scope_type="user",
                scope_id="user-1",
                category="user_preference",
                key="answer_style",
                value_json={"value": "concise"},
                confidence=1.0,
                source_type="explicit_preference",
                source_id="settings",
                privacy_level="safe_metadata",
                created_at=utc_now(),
                updated_at=utc_now(),
            )
        )
        session.add(
            StudyAgentMemoryRecord(
                id="memory-owner-2",
                owner_id="user-2",
                scope_type="user",
                scope_id="user-2",
                category="user_preference",
                key="answer_style",
                value_json={"value": "detailed"},
                confidence=1.0,
                source_type="explicit_preference",
                source_id="settings",
                privacy_level="safe_metadata",
                created_at=utc_now(),
                updated_at=utc_now(),
            )
        )
        session.commit()

    response = client.get(
        "/api/study-agent/memories/summary",
        headers={"Authorization": "Bearer " + _token_for_user("user-1")},
    )

    assert response.status_code == 200
    assert response.json()["preferences"]["answer_style"] == "concise"
    assert "detailed" not in str(response.json())
```

- [ ] **Step 2: Run failing API test**

Run:

```bash
pytest tests/test_study_agent_api.py::test_memory_summary_endpoint_is_owner_scoped -q
```

Expected: FAIL because the endpoint does not exist.

- [ ] **Step 3: Add memory endpoints**

Modify `src/api/routes/study_agent.py` imports:

```python
from src.services.study_agent_memory import StudyAgentMemoryService
```

Add routes:

```python
@router.get("/memories/summary")
def get_study_agent_memory_summary(request: Request) -> dict[str, Any]:
    context = get_user_context(request)
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        return {"preferences": {}, "review_reason_counts": {}, "memory_record_count": 0}
    return StudyAgentMemoryService(session_factory).summary(owner_id=context.user_id)


@router.delete("/memories/{memory_id}")
def delete_study_agent_memory(request: Request, memory_id: str) -> dict[str, str]:
    context = get_user_context(request)
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        raise HTTPException(status_code=503, detail="Study Agent memory store is not configured")
    deleted = StudyAgentMemoryService(session_factory).delete_memory(
        owner_id=context.user_id,
        memory_id=memory_id,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"id": memory_id, "status": "deleted"}
```

- [ ] **Step 4: Store review outcome memory after review decisions**

Modify `src/api/routes/review.py` imports:

```python
from src.services.study_agent_memory import StudyAgentMemoryService
```

After persisted review task decision commit and audit event, add:

```python
        if task.target_type == "study_agent_workflow":
            StudyAgentMemoryService(session_factory).store_review_outcome(
                owner_id=task.owner_id,
                workflow_id=task.target_id,
                review_task_id=task.id,
                reasons=[task.reason],
                decision=decision_request.decision,
                metadata=task.task_metadata or {},
            )
```

- [ ] **Step 5: Add frontend memory API type**

Modify `frontend/src/api.ts`:

```ts
export interface StudyAgentMemorySummary {
  preferences: Record<string, string>;
  review_reason_counts: Record<string, number>;
  memory_record_count: number;
}

export async function getStudyAgentMemorySummary(
  apiClient: ApiClient,
): Promise<StudyAgentMemorySummary> {
  const response = await fetch(`${API_BASE}/api/study-agent/memories/summary`, {
    headers: apiClient.headers(),
  });
  return parseJson<StudyAgentMemorySummary>(response, "Failed to load memory summary");
}
```

- [ ] **Step 6: Run Task 4 verification**

Run:

```bash
pytest tests/test_study_agent_api.py tests/test_mvp7_product_loop.py tests/test_study_agent_memory.py -q
cd frontend && npm run build
```

Expected: PASS.

- [ ] **Step 7: Commit memory API integration**

Run:

```bash
git add src/api/routes/study_agent.py src/api/routes/review.py frontend/src/api.ts tests/test_study_agent_api.py tests/test_mvp7_product_loop.py
git commit -m "feat: expose study agent memory summary"
```

- [ ] **Step 8: Run required reviews**

Run Spec review and Quality review for Task 4 before continuing.

## Task 5: Versioned Study Skill Registry

**Files:**
- Create: `src/services/study_agent_skills.py`
- Modify: `src/services/study_agent.py`
- Modify: `src/services/study_agent_runtime.py`
- Modify: `src/services/study_agent_workflow.py`
- Modify: `src/services/study_agent_trace.py`
- Modify: `src/api/routes/study_agent.py`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/components/StudyAgentPanel.tsx`
- Modify: `frontend/src/styles.css`
- Test: `tests/test_study_agent_skills.py`
- Test: `tests/test_study_agent_runtime.py`
- Test: `tests/test_study_agent_traces.py`
- Test: `tests/test_study_agent_api.py`

- [ ] **Step 1: Write failing skill registry tests**

Create `tests/test_study_agent_skills.py`:

```python
from src.services.rag_router import RetrievalMode
from src.services.study_agent import StudyTarget
from src.services.study_agent_skills import StudySkillRegistry


def test_registry_selects_default_skill_by_target_and_category():
    registry = StudySkillRegistry()

    answer_skill = registry.select_skill(
        target=StudyTarget.ANSWER,
        category="definition",
        requested_skill=None,
        requested_version=None,
    )
    question_skill = registry.select_skill(
        target=StudyTarget.QUESTION,
        category="question_generation",
        requested_skill=None,
        requested_version=None,
    )

    assert answer_skill.skill_name == "concept_explanation"
    assert question_skill.skill_name == "practice_question"


def test_registry_rejects_unsupported_skill_version():
    registry = StudySkillRegistry()

    try:
        registry.select_skill(
            target=StudyTarget.ANSWER,
            category="definition",
            requested_skill="concept_explanation",
            requested_version="v999",
        )
    except ValueError as exc:
        assert "unsupported skill version" in str(exc)
    else:
        raise AssertionError("unsupported skill version should fail")


def test_skill_trace_metadata_is_safe():
    registry = StudySkillRegistry()
    skill = registry.select_skill(
        target=StudyTarget.ANSWER,
        category="definition",
        requested_skill=None,
        requested_version=None,
    )

    assert skill.to_safe_dict() == {
        "skill_name": "concept_explanation",
        "skill_version": "v1",
        "supported_targets": ["answer"],
        "allowed_retrieval_modes": ["simple_rag", "graph_rag_lite"],
        "default_budget": "balanced",
        "review_gate_profile": "standard",
        "memory_inputs": ["user_preference", "study_state"],
        "memory_outputs": ["skill_performance"],
    }
```

- [ ] **Step 2: Run failing skill tests**

Run:

```bash
pytest tests/test_study_agent_skills.py -q
```

Expected: FAIL because `StudySkillRegistry` does not exist.

- [ ] **Step 3: Implement skill registry**

Create `src/services/study_agent_skills.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from src.services.rag_router import RetrievalMode
from src.services.study_agent import StudyBudget, StudyTarget


@dataclass(frozen=True)
class StudySkill:
    skill_name: str
    version: str
    supported_targets: tuple[StudyTarget, ...]
    allowed_retrieval_modes: tuple[RetrievalMode, ...]
    default_budget: StudyBudget
    review_gate_profile: str
    memory_inputs: tuple[str, ...]
    memory_outputs: tuple[str, ...]

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "skill_name": self.skill_name,
            "skill_version": self.version,
            "supported_targets": [target.value for target in self.supported_targets],
            "allowed_retrieval_modes": [mode.value for mode in self.allowed_retrieval_modes],
            "default_budget": self.default_budget.value,
            "review_gate_profile": self.review_gate_profile,
            "memory_inputs": list(self.memory_inputs),
            "memory_outputs": list(self.memory_outputs),
        }


class StudySkillRegistry:
    def __init__(self, skills: tuple[StudySkill, ...] | None = None) -> None:
        self.skills = skills or _default_skills()

    def list_skills(self) -> list[dict[str, object]]:
        return [skill.to_safe_dict() for skill in self.skills]

    def select_skill(
        self,
        *,
        target: StudyTarget,
        category: str,
        requested_skill: str | None,
        requested_version: str | None,
    ) -> StudySkill:
        if requested_skill:
            candidates = [skill for skill in self.skills if skill.skill_name == requested_skill]
            if requested_version:
                candidates = [skill for skill in candidates if skill.version == requested_version]
            if not candidates:
                raise ValueError("unsupported skill version")
            skill = candidates[0]
            if target not in skill.supported_targets:
                raise ValueError("skill does not support requested target")
            return skill

        if target == StudyTarget.QUESTION:
            return self._by_name("practice_question")
        if target == StudyTarget.OUTLINE_FRAGMENT:
            return self._by_name("outline_fragment")
        if category == "concept_relation":
            return self._by_name("concept_relation")
        if category == "multi_document_synthesis":
            return self._by_name("multi_document_synthesis")
        return self._by_name("concept_explanation")

    def _by_name(self, skill_name: str) -> StudySkill:
        for skill in self.skills:
            if skill.skill_name == skill_name:
                return skill
        raise ValueError("skill registry is missing default skill")


def _default_skills() -> tuple[StudySkill, ...]:
    return (
        StudySkill(
            skill_name="concept_explanation",
            version="v1",
            supported_targets=(StudyTarget.ANSWER,),
            allowed_retrieval_modes=(RetrievalMode.SIMPLE, RetrievalMode.GRAPH),
            default_budget=StudyBudget.BALANCED,
            review_gate_profile="standard",
            memory_inputs=("user_preference", "study_state"),
            memory_outputs=("skill_performance",),
        ),
        StudySkill(
            skill_name="practice_question",
            version="v1",
            supported_targets=(StudyTarget.QUESTION,),
            allowed_retrieval_modes=(RetrievalMode.SIMPLE, RetrievalMode.GRAPH, RetrievalMode.AGENTIC),
            default_budget=StudyBudget.BALANCED,
            review_gate_profile="strict",
            memory_inputs=("user_preference", "study_state"),
            memory_outputs=("review_outcome", "skill_performance"),
        ),
        StudySkill(
            skill_name="outline_fragment",
            version="v1",
            supported_targets=(StudyTarget.OUTLINE_FRAGMENT,),
            allowed_retrieval_modes=(RetrievalMode.SIMPLE, RetrievalMode.GRAPH),
            default_budget=StudyBudget.BALANCED,
            review_gate_profile="strict",
            memory_inputs=("user_preference", "study_state"),
            memory_outputs=("review_outcome", "skill_performance"),
        ),
        StudySkill(
            skill_name="concept_relation",
            version="v1",
            supported_targets=(StudyTarget.ANSWER,),
            allowed_retrieval_modes=(RetrievalMode.GRAPH, RetrievalMode.SIMPLE),
            default_budget=StudyBudget.BALANCED,
            review_gate_profile="standard",
            memory_inputs=("study_state",),
            memory_outputs=("skill_performance",),
        ),
        StudySkill(
            skill_name="multi_document_synthesis",
            version="v1",
            supported_targets=(StudyTarget.ANSWER, StudyTarget.QUESTION),
            allowed_retrieval_modes=(RetrievalMode.AGENTIC, RetrievalMode.GRAPH, RetrievalMode.SIMPLE),
            default_budget=StudyBudget.HIGH,
            review_gate_profile="strict",
            memory_inputs=("user_preference", "study_state"),
            memory_outputs=("review_outcome", "skill_performance"),
        ),
    )
```

- [ ] **Step 4: Add request fields and skill metadata**

Modify `StudyRequest` in `src/services/study_agent.py`:

```python
    skill_name: str | None = None
    skill_version: str | None = None
```

Modify `normalize_study_request` return:

```python
        skill_name=_optional_nonempty(payload.get("skill_name")),
        skill_version=_optional_nonempty(payload.get("skill_version")),
```

Modify `StudyAgentOrchestrator.run` audit metadata:

```python
        skill = payload.get("skill")
        if isinstance(skill, dict):
            audit_metadata["skill"] = {
                "skill_name": skill.get("skill_name"),
                "skill_version": skill.get("skill_version"),
                "review_gate_profile": skill.get("review_gate_profile"),
            }
```

- [ ] **Step 5: Wire skill selection into runtime**

Modify `src/services/study_agent_runtime.py` imports:

```python
from src.services.study_agent_skills import StudySkillRegistry
```

Add constructor argument and field:

```python
        skill_registry: StudySkillRegistry | None = None,
```

```python
        self.skill_registry = skill_registry or StudySkillRegistry()
```

After `policy_decision`, select skill:

```python
        skill = self.skill_registry.select_skill(
            target=request.target,
            category=policy_decision.category,
            requested_skill=request.skill_name,
            requested_version=request.skill_version,
        )
        add_stage(
            WorkflowStageName.SKILL_SELECT,
            output_summary={
                "skill_name": skill.skill_name,
                "skill_version": skill.version,
                "review_gate_profile": skill.review_gate_profile,
            },
        )
```

Add to `orchestrator_payload`:

```python
            "skill": skill.to_safe_dict(),
```

After result:

```python
        result.audit_metadata["skill"] = skill.to_safe_dict()
```

- [ ] **Step 6: Extend workflow sanitizer for skill labels**

Modify `WorkflowStageName` in `src/services/study_agent_workflow.py`:

```python
    SKILL_SELECT = "skill_select"
    MEMORY_UPDATE = "memory_update"
```

Extend `_SAFE_STRING_VALUES`:

```python
    "skill_name": {
        "concept_explanation",
        "practice_question",
        "outline_fragment",
        "concept_relation",
        "multi_document_synthesis",
    },
    "skill_version": {"v1"},
    "review_gate_profile": {"standard", "strict"},
```

Extend `_SAFE_INT_KEYS`:

```python
    "memory_record_count",
```

- [ ] **Step 7: Persist safe skill metadata in traces**

Modify `src/services/study_agent_trace.py`:

```python
_SAFE_SKILL_NAMES = {
    "concept_explanation",
    "practice_question",
    "outline_fragment",
    "concept_relation",
    "multi_document_synthesis",
}
_SAFE_SKILL_VERSIONS = {"v1"}
_SAFE_REVIEW_GATE_PROFILES = {"standard", "strict"}


def safe_skill_metadata(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    skill_name = value.get("skill_name")
    skill_version = value.get("skill_version")
    profile = value.get("review_gate_profile")
    safe = {
        "skill_name": skill_name if skill_name in _SAFE_SKILL_NAMES else None,
        "skill_version": skill_version if skill_version in _SAFE_SKILL_VERSIONS else None,
        "review_gate_profile": profile if profile in _SAFE_REVIEW_GATE_PROFILES else None,
    }
    return {key: item for key, item in safe.items() if item is not None} or None
```

In `record_success`, add:

```python
        skill = safe_skill_metadata(result.audit_metadata.get("skill"))
        if skill is not None:
            trace_metadata["skill"] = skill
```

In `_trace_payload`, add:

```python
    skill = safe_skill_metadata((record.trace_metadata or {}).get("skill"))
    if skill is not None:
        payload["skill"] = skill
```

- [ ] **Step 8: Add skill endpoints and frontend diagnostics**

Modify `src/api/routes/study_agent.py`:

```python
from src.services.study_agent_skills import StudySkillRegistry
```

Add route:

```python
@router.get("/skills")
def list_study_agent_skills() -> list[dict[str, Any]]:
    return StudySkillRegistry().list_skills()
```

Modify `frontend/src/api.ts`:

```ts
export interface StudyAgentSkillDiagnostic {
  skill_name?: string | null;
  skill_version?: string | null;
  review_gate_profile?: string | null;
}

export interface StudyAgentResult {
  // existing fields stay unchanged
  skill?: StudyAgentSkillDiagnostic | null;
}
```

Modify `StudyAgentPanel.tsx` near policy diagnostics:

```tsx
          {result.skill ? (
            <div className="study-agent-skill" aria-label="Study Agent skill diagnostics">
              <span>
                <strong>Skill</strong> {result.skill.skill_name ?? "unknown"}
              </span>
              <span>{result.skill.skill_version ?? "unknown"}</span>
            </div>
          ) : null}
```

Add compact CSS mirroring `.study-agent-policy`.

- [ ] **Step 9: Run Task 5 verification**

Run:

```bash
pytest tests/test_study_agent_skills.py tests/test_study_agent_runtime.py tests/test_study_agent_traces.py tests/test_study_agent_api.py -q
cd frontend && npm run build
```

Expected: PASS.

- [ ] **Step 10: Commit skill registry**

Run:

```bash
git add src/services/study_agent_skills.py src/services/study_agent.py src/services/study_agent_runtime.py src/services/study_agent_workflow.py src/services/study_agent_trace.py src/api/routes/study_agent.py frontend/src/api.ts frontend/src/components/StudyAgentPanel.tsx frontend/src/styles.css tests/test_study_agent_skills.py tests/test_study_agent_runtime.py tests/test_study_agent_traces.py tests/test_study_agent_api.py
git commit -m "feat: add study agent skill registry"
```

- [ ] **Step 11: Run required reviews**

Run Spec review and Quality review for Task 5 before continuing.

## Task 6: Legacy Agent Boundary Cleanup

**Files:**
- Modify: `src/agents/base_agent.py`
- Modify: `src/coordinator/main_coordinator.py`
- Modify: `SPEC.md`
- Test: `tests/test_agents.py`
- Test: `tests/test_coordinator.py`

- [ ] **Step 1: Write failing agent status test**

Append to `tests/test_agents.py`:

```python
@pytest.mark.asyncio
async def test_base_agent_marks_failed_result_as_failed():
    class SoftFailAgent(BaseAgent):
        role = "soft-fail"
        system_prompt = "test"

        async def process(self, input_data):
            return AgentResult(
                success=False,
                data={"safe": True},
                message="soft failure",
                error_code="soft_failure",
            )

    agent = SoftFailAgent()
    result = await agent.invoke({})

    assert result.success is False
    assert result.error_code == "soft_failure"
    assert agent.status == AgentStatus.FAILED
```

- [ ] **Step 2: Run failing agent test**

Run:

```bash
pytest tests/test_agents.py::test_base_agent_marks_failed_result_as_failed -q
```

Expected: FAIL because `AgentResult` has no `error_code` and failed result still marks agent completed.

- [ ] **Step 3: Fix BaseAgent result contract**

Modify `src/agents/base_agent.py`:

```python
@dataclass
class AgentResult:
    """智能体结果"""

    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    message: str = ""
    status: AgentStatus = AgentStatus.COMPLETED
    error_code: str | None = None
    trace_metadata: Dict[str, Any] = field(default_factory=dict)
```

Modify `BaseAgent.invoke` success block:

```python
                result = await self.process(input_data)
                if result.success:
                    self.status = AgentStatus.COMPLETED
                    result.status = AgentStatus.COMPLETED
                else:
                    self.status = AgentStatus.FAILED
                    result.status = AgentStatus.FAILED
                return result
```

Modify exception result:

```python
                        error_code="agent_retry_exhausted",
                        trace_metadata={"retry_count": self.retry_count},
```

- [ ] **Step 4: Add coordinator safe failure regression**

Append to `tests/test_coordinator.py`:

```python
@pytest.mark.asyncio
async def test_coordinator_failure_response_uses_safe_stage_data():
    coordinator = MainCoordinator()
    response = await coordinator.invoke({"pdf_path": "/missing.pdf"})

    assert response["status"] == "failed"
    assert response["data"]["failed_stage"] == "document_parsing"
    assert "completed_stages" in response["data"]
    assert "raw query" not in str(response).lower()
```

- [ ] **Step 5: Update SPEC legacy boundary**

Add a short note to `SPEC.md` current MVP-9 status section:

```markdown
- Legacy agent boundary: `MainCoordinator` and `BaseAgent` remain available for batch and specialist-agent tests, but the product Study Agent workflow is the main user-facing path. Legacy failed results must not be reported as completed agent status.
```

- [ ] **Step 6: Run legacy tests**

Run:

```bash
pytest tests/test_agents.py tests/test_coordinator.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit legacy cleanup**

Run:

```bash
git add src/agents/base_agent.py src/coordinator/main_coordinator.py SPEC.md tests/test_agents.py tests/test_coordinator.py
git commit -m "fix: clarify legacy agent failure status"
```

- [ ] **Step 8: Run required reviews**

Run Spec review and Quality review for Task 6 before continuing.

## Task 7: Documentation Sync And Final Verification

**Files:**
- Modify: `README.md`
- Modify: `SPEC.md`
- Modify: `docs/superpowers/specs/2026-07-06-agent-collaboration-memory-skills-design.md` only if implementation forces a clarification.

- [ ] **Step 1: Update README status**

Add to `README.md` under MVP-9 status:

```markdown
Study Agent collaboration now links review-gated outputs to persisted review tasks, records owner-scoped safe memory summaries, and labels bounded study skills by version. These additions keep the deterministic supervisor as the product mainline and do not introduce open-ended autonomous agent loops or raw conversation memory.
```

- [ ] **Step 2: Update SPEC status**

Add to `SPEC.md` current MVP-9 implementation status:

```markdown
- Agent collaboration productization: Review Gate outcomes can create idempotent review tasks, safe owner-scoped memory summaries support preferences and review outcomes, and Study Agent skills are versioned as product capabilities before any prompt evolution or autonomous loop.
```

- [ ] **Step 3: Run backend targeted verification**

Run:

```bash
pytest tests/test_study_agent_review_tasks.py tests/test_study_agent_memory.py tests/test_study_agent_skills.py tests/test_study_agent_runtime.py tests/test_study_agent_traces.py tests/test_study_agent_api.py tests/test_agents.py tests/test_coordinator.py tests/test_db_models.py tests/test_db_migrations.py -q
```

Expected: PASS.

- [ ] **Step 4: Run P2/P3 regression suite**

Run:

```bash
pytest tests/test_rag_route_policy.py tests/test_rag_router.py tests/test_study_agent_runtime.py tests/test_graph_rag.py tests/test_agentic_rag.py tests/test_study_agent_api.py tests/test_api_permissions_audit.py tests/test_rag_evaluation.py tests/test_rag_mode_comparison.py tests/test_study_agent_workflow.py tests/test_study_agent_traces.py tests/test_study_agent_memory.py tests/test_study_agent_skills.py tests/test_study_agent_review_tasks.py -q
```

Expected: PASS.

- [ ] **Step 5: Run frontend build**

Run:

```bash
cd frontend && npm run build
```

Expected: PASS.

- [ ] **Step 6: Confirm no generated evaluation artifacts**

Run:

```bash
find docs -path 'docs/evaluation/*' -maxdepth 2 -type f -print
git status --short --branch
```

Expected: no `docs/evaluation` files and only intended docs changes before commit.

- [ ] **Step 7: Commit docs sync**

Run:

```bash
git add README.md SPEC.md docs/superpowers/specs/2026-07-06-agent-collaboration-memory-skills-design.md
git commit -m "docs: sync agent collaboration productization status"
```

- [ ] **Step 8: Run required reviews**

Run Spec review and Quality review for Task 7 before marking this implementation complete.

## Final Verification Before Completion

After all tasks and reviews pass, run:

```bash
pytest tests/test_rag_route_policy.py tests/test_rag_router.py tests/test_study_agent_runtime.py tests/test_graph_rag.py tests/test_agentic_rag.py tests/test_study_agent_api.py tests/test_api_permissions_audit.py tests/test_rag_evaluation.py tests/test_rag_mode_comparison.py tests/test_study_agent_workflow.py tests/test_study_agent_traces.py tests/test_study_agent_memory.py tests/test_study_agent_skills.py tests/test_study_agent_review_tasks.py tests/test_agents.py tests/test_coordinator.py tests/test_db_models.py tests/test_db_migrations.py -q
cd frontend && npm run build
find docs -path 'docs/evaluation/*' -maxdepth 2 -type f -print
git status --short --branch
```

Expected:

- backend tests pass;
- frontend build passes;
- no generated `docs/evaluation/*.json` or `docs/evaluation/*.md` artifacts are tracked or left untracked;
- worktree is clean after final commit.

## Self-Review Checklist For This Plan

- Spec coverage: Tasks 1-7 cover Review Gate review tasks, idempotency, safe review metadata, owner-scoped memory, memory deletion and summary API, review outcome memory, versioned skill registry, skill trace metadata, compact frontend diagnostics, legacy agent status cleanup, docs, and verification governance.
- Deferred scope: bounded parallel expert branches are explicitly excluded from Phase 1 because the spec says optional expert collaboration comes after review-task, memory, and skill contracts are stable.
- Placeholder scan: This plan contains concrete file paths, test snippets, implementation snippets, commands, expected results, and commit messages.
- Type consistency: `task_metadata`, `StudyAgentMemoryRecord`, `StudyAgentMemoryService`, `StudySkillRegistry`, `StudySkill`, `skill_name`, `skill_version`, `review_task`, and `StudyAgentReviewTaskService` names are consistent across tasks.
- Privacy check: Every new persisted path stores labels, IDs, counts, metrics, and allowlisted reason codes only.
