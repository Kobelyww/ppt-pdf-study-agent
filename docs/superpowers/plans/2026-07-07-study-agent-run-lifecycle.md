# Study Agent Run Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a durable, owner-scoped Study Agent run lifecycle with safe run metadata, lifecycle controls, retry linkage, audit events, and compact frontend diagnostics.

**Architecture:** Keep the existing synchronous `StudyAgentRuntimeService` as the execution path for this slice, and wrap it with a dedicated `StudyAgentRunService` plus `study_agent_runs` persistence. The run layer stores only safe request/result summaries and state transitions, so a later queue-backed worker can reuse the same table and APIs without changing the public contract.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy, Alembic, pytest, React/Vite/TypeScript.

---

## Source Spec

Implement:

- `docs/superpowers/specs/2026-07-07-study-agent-run-lifecycle-design.md`

## File Structure

- Modify `src/db/models.py`: add `StudyAgentRunRecord`.
- Modify `src/db/__init__.py`: export `StudyAgentRunRecord`.
- Create `src/db/migrations/versions/0007_study_agent_runs.py`: add table and indexes.
- Create `src/services/study_agent_runs.py`: run status constants, safe request/result helpers, state machine, CRUD/control methods.
- Modify `src/api/routes/study_agent.py`: add run create/list/detail/cancel/pause/resume/retry/archive endpoints and wrap runtime execution.
- Modify `frontend/src/api.ts`: add run types and API calls.
- Modify `frontend/src/components/StudyAgentPanel.tsx`: call create-run endpoint and show compact run lifecycle diagnostics.
- Modify `frontend/src/styles.css`: add compact run diagnostics styles.
- Modify `README.md` and `SPEC.md`: document lifecycle status after implementation.
- Tests:
  - Create `tests/test_study_agent_runs.py`
  - Extend `tests/test_db_models.py`
  - Extend `tests/test_db_migrations.py`
  - Extend `tests/test_study_agent_api.py`

## Implementation Rules

- Do not persist raw query text, generated answers/questions, raw chunk content, source snippets, prompts, hidden reasoning, exception strings, paths, authorization headers, API keys, tokens, passwords, or secrets.
- Retry must require a fresh request payload and must not use stored raw query text.
- Keep `/api/study-agent/query` compatible.
- Every task must pass Spec review and Quality/privacy review before the next task starts.
- Use TDD: write failing tests, watch them fail, implement, then rerun passing tests.

---

## Task 1: Run Persistence And State Machine

**Files:**
- Modify: `src/db/models.py`
- Modify: `src/db/__init__.py`
- Create: `src/db/migrations/versions/0007_study_agent_runs.py`
- Create: `src/services/study_agent_runs.py`
- Test: `tests/test_study_agent_runs.py`
- Test: `tests/test_db_models.py`
- Test: `tests/test_db_migrations.py`

- [ ] **Step 1: Write failing service/model tests**

Create `tests/test_study_agent_runs.py` with tests for safe metadata, owner isolation, transition conflicts, retry linkage, and no raw text leakage:

```python
from __future__ import annotations

import pytest
from sqlalchemy import create_engine

from src.db import Base, StudyAgentRunRecord, create_session_factory
from src.services.study_agent_runs import (
    StudyAgentRunConflict,
    StudyAgentRunNotFound,
    StudyAgentRunService,
)


def _service(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'runs.db'}")
    Base.metadata.create_all(engine)
    return StudyAgentRunService(create_session_factory(engine))


def _payload() -> dict:
    return {
        "query": "Explain the private derivative note",
        "target": "answer",
        "document_ids": ["doc-1"],
        "preferred_mode": "simple_rag",
        "budget": "balanced",
        "expected_terms": ["derivative", "slope"],
        "skill_name": "concept_explanation",
        "skill_version": "v1",
    }


def test_create_run_stores_safe_request_metadata_without_raw_query(tmp_path):
    service = _service(tmp_path)

    run = service.create_run(
        owner_id="user-1",
        request_id="req-1",
        payload=_payload(),
    )

    assert run["id"].startswith("run-")
    assert run["status"] == "queued"
    assert run["query_hash"].startswith("sha256:")
    assert run["target"] == "answer"
    assert run["document_ids"] == ["doc-1"]
    assert run["preferred_mode"] == "simple_rag"
    assert run["budget"] == "balanced"
    assert run["skill_name"] == "concept_explanation"
    assert run["skill_version"] == "v1"
    assert run["expected_term_count"] == 2
    assert "query" not in str(run).lower()
    assert "private derivative note" not in str(run).lower()


def test_mark_completed_stores_safe_result_summary_only(tmp_path):
    service = _service(tmp_path)
    run = service.create_run(owner_id="user-1", request_id="req-1", payload=_payload())
    running = service.mark_running(owner_id="user-1", run_id=run["id"])

    completed = service.mark_terminal(
        owner_id="user-1",
        run_id=running["id"],
        status="completed",
        result_summary={
            "trace_id": "trace-abc",
            "workflow_id": "workflow-" + "a" * 32,
            "review_task_id": "review-1",
            "selected_mode": "simple_rag",
            "policy_status": "allowed",
            "category": "definition",
            "source_count": 1,
            "used_chunk_count": 1,
            "confidence": 0.83,
            "source_recall": 1.0,
            "answer_term_recall": 1.0,
            "needs_review": False,
            "latency_ms": 12.5,
            "stage_count": 8,
            "answer": "raw generated answer",
            "prompt": "hidden prompt",
            "token": "sk-secret-token",
        },
    )

    assert completed["status"] == "completed"
    assert completed["trace_id"] == "trace-abc"
    assert completed["workflow_id"] == "workflow-" + "a" * 32
    assert completed["result_summary"] == {
        "trace_id": "trace-abc",
        "workflow_id": "workflow-" + "a" * 32,
        "review_task_id": "review-1",
        "selected_mode": "simple_rag",
        "policy_status": "allowed",
        "category": "definition",
        "source_count": 1,
        "used_chunk_count": 1,
        "confidence": 0.83,
        "source_recall": 1.0,
        "answer_term_recall": 1.0,
        "needs_review": False,
        "latency_ms": 12.5,
        "stage_count": 8,
    }
    serialized = str(completed).lower()
    assert "raw generated answer" not in serialized
    assert "hidden prompt" not in serialized
    assert "sk-secret-token" not in serialized


def test_control_transitions_enforce_allowed_statuses(tmp_path):
    service = _service(tmp_path)
    run = service.create_run(owner_id="user-1", request_id="req-1", payload=_payload())
    paused = service.pause(owner_id="user-1", run_id=run["id"])
    assert paused["status"] == "paused"
    resumed = service.resume(owner_id="user-1", run_id=run["id"])
    assert resumed["status"] == "queued"
    cancelled = service.cancel(owner_id="user-1", run_id=run["id"])
    assert cancelled["status"] == "cancelled"

    with pytest.raises(StudyAgentRunConflict):
        service.pause(owner_id="user-1", run_id=run["id"])


def test_retry_child_links_to_parent_without_reusing_raw_query(tmp_path):
    service = _service(tmp_path)
    parent = service.create_run(owner_id="user-1", request_id="req-1", payload=_payload())
    service.mark_running(owner_id="user-1", run_id=parent["id"])
    service.mark_terminal(
        owner_id="user-1",
        run_id=parent["id"],
        status="failed",
        error_code="bad_study_request",
        error_message="bad_study_request",
    )

    child = service.create_retry_run(
        owner_id="user-1",
        request_id="req-2",
        parent_run_id=parent["id"],
        payload={**_payload(), "query": "Fresh retry query"},
    )

    assert child["retry_of_run_id"] == parent["id"]
    assert child["attempt"] == 2
    assert "fresh retry query" not in str(child).lower()


def test_owner_isolation_for_detail_and_controls(tmp_path):
    service = _service(tmp_path)
    run = service.create_run(owner_id="user-1", request_id="req-1", payload=_payload())

    assert service.get_run(owner_id="user-1", run_id=run["id"])["id"] == run["id"]
    assert service.get_run(owner_id="user-2", run_id=run["id"]) is None
    assert service.run_exists(run["id"]) is True
    with pytest.raises(StudyAgentRunNotFound):
        service.cancel(owner_id="user-2", run_id=run["id"])
```

- [ ] **Step 2: Extend DB model tests**

Add a test to `tests/test_db_models.py`:

```python
def test_study_agent_run_record_accepts_product_lifecycle_statuses(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'runs.db'}")
    Base.metadata.create_all(engine)
    SessionFactory = create_session_factory(engine)
    statuses = [
        "queued",
        "running",
        "paused",
        "completed",
        "needs_review",
        "failed",
        "cancelled",
        "timed_out",
        "archived",
    ]

    with SessionFactory() as session:
        for status in statuses:
            session.add(
                StudyAgentRunRecord(
                    id=f"run-{status}",
                    owner_id="user-1",
                    request_id=f"req-{status}",
                    status=status,
                    query_hash="sha256:" + "a" * 64,
                    target="answer",
                    document_ids=["doc-1"],
                    expected_term_count=0,
                    attempt=1,
                    result_summary={},
                    lifecycle_metadata={},
                )
            )
        session.commit()

    with SessionFactory() as session:
        stored = {row.status for row in session.query(StudyAgentRunRecord).all()}
    assert stored == set(statuses)
```

- [ ] **Step 3: Extend migration test**

In `tests/test_db_migrations.py`, import `StudyAgentRunRecord` and extend `test_alembic_upgrade_creates_orm_compatible_sqlite_schema` to assert:

```python
run_columns = {
    column["name"] for column in inspector.get_columns("study_agent_runs")
}
assert {
    "id",
    "owner_id",
    "request_id",
    "status",
    "query_hash",
    "target",
    "document_ids",
    "preferred_mode",
    "selected_mode",
    "budget",
    "skill_name",
    "skill_version",
    "expected_term_count",
    "workflow_id",
    "trace_id",
    "review_task_id",
    "retry_of_run_id",
    "attempt",
    "result_summary",
    "error_code",
    "error_message",
    "lifecycle_metadata",
    "created_at",
    "updated_at",
    "started_at",
    "completed_at",
    "cancelled_at",
    "paused_at",
    "archived_at",
}.issubset(run_columns)
run_indexes = {index["name"] for index in inspector.get_indexes("study_agent_runs")}
assert {
    "ix_study_agent_runs_owner_created",
    "ix_study_agent_runs_owner_status_created",
    "ix_study_agent_runs_owner_request",
    "ix_study_agent_runs_owner_retry",
    "ix_study_agent_runs_workflow",
    "ix_study_agent_runs_trace",
}.issubset(run_indexes)
```

- [ ] **Step 4: Run failing tests**

Run:

```bash
pytest tests/test_study_agent_runs.py tests/test_db_models.py::test_study_agent_run_record_accepts_product_lifecycle_statuses tests/test_db_migrations.py::test_alembic_upgrade_creates_orm_compatible_sqlite_schema -q
```

Expected: fail because `StudyAgentRunRecord`, migration `0007`, and `StudyAgentRunService` do not exist yet.

- [ ] **Step 5: Implement model, migration, and service**

Implement:

- `StudyAgentRunRecord` in `src/db/models.py` with status check constraint and indexes.
- `StudyAgentRunRecord` exports in `src/db/__init__.py`.
- `0007_study_agent_runs.py` with `down_revision = "0006"`.
- `StudyAgentRunService` in `src/services/study_agent_runs.py`.

Required public service methods:

```python
class StudyAgentRunService:
    def create_run(self, *, owner_id: str, request_id: str, payload: dict, retry_of_run_id: str | None = None, attempt: int = 1) -> dict: ...
    def create_retry_run(self, *, owner_id: str, request_id: str, parent_run_id: str, payload: dict) -> dict: ...
    def list_runs(self, *, owner_id: str, status: str | None = None, include_archived: bool = False, limit: int = 20) -> list[dict]: ...
    def get_run(self, *, owner_id: str, run_id: str) -> dict | None: ...
    def run_exists(self, run_id: str) -> bool: ...
    def mark_running(self, *, owner_id: str, run_id: str) -> dict: ...
    def mark_terminal(self, *, owner_id: str, run_id: str, status: str, result_summary: dict | None = None, error_code: str | None = None, error_message: str | None = None) -> dict: ...
    def cancel(self, *, owner_id: str, run_id: str) -> dict: ...
    def pause(self, *, owner_id: str, run_id: str) -> dict: ...
    def resume(self, *, owner_id: str, run_id: str) -> dict: ...
    def archive(self, *, owner_id: str, run_id: str) -> dict: ...
```

- [ ] **Step 6: Run passing task tests**

Run:

```bash
pytest tests/test_study_agent_runs.py tests/test_db_models.py::test_study_agent_run_record_accepts_product_lifecycle_statuses tests/test_db_migrations.py::test_alembic_upgrade_creates_orm_compatible_sqlite_schema -q
```

Expected: pass.

- [ ] **Step 7: Commit Task 1**

Run:

```bash
git add src/db/models.py src/db/__init__.py src/db/migrations/versions/0007_study_agent_runs.py src/services/study_agent_runs.py tests/test_study_agent_runs.py tests/test_db_models.py tests/test_db_migrations.py
git commit -m "feat: persist study agent run lifecycle"
```

---

## Task 2: Run Lifecycle API Wrapper And Controls

**Files:**
- Modify: `src/api/routes/study_agent.py`
- Test: `tests/test_study_agent_api.py`

- [ ] **Step 1: Write failing API tests**

Add tests that prove:

- `POST /api/study-agent/runs` returns a normal Study Agent response with `run.status == "completed"` for passing results.
- A needs-review workflow marks `run.status == "needs_review"`.
- A handled `ValueError` marks the persisted run `failed` with safe error code and no raw exception text.
- `GET /api/study-agent/runs` lists only the authenticated owner's runs.
- `GET /api/study-agent/runs/{run_id}` returns `403` for cross-owner existing runs and `404` for missing runs.
- `cancel`, `pause`, `resume`, `retry`, and `archive` endpoints enforce the Task 1 state machine.
- Audit events use safe metadata.

- [ ] **Step 2: Run failing API tests**

Run:

```bash
pytest tests/test_study_agent_api.py -q
```

Expected: fail because run endpoints do not exist.

- [ ] **Step 3: Implement endpoints and execution wrapper**

Add endpoints:

```python
@router.post("/runs")
async def create_study_agent_run(...)

@router.get("/runs")
def list_study_agent_runs(...)

@router.get("/runs/{run_id}")
def get_study_agent_run(...)

@router.post("/runs/{run_id}/cancel")
def cancel_study_agent_run(...)

@router.post("/runs/{run_id}/pause")
def pause_study_agent_run(...)

@router.post("/runs/{run_id}/resume")
def resume_study_agent_run(...)

@router.post("/runs/{run_id}/retry")
async def retry_study_agent_run(...)

@router.post("/runs/{run_id}/archive")
def archive_study_agent_run(...)
```

Reuse `_record_study_agent_trace`, `_record_study_agent_audit`, `_ensure_study_agent_review_task`, `safe_policy_metadata`, `safe_skill_metadata`, `safe_expert_metadata`, and `sanitize_workflow_payload`.

- [ ] **Step 4: Run passing API tests**

Run:

```bash
pytest tests/test_study_agent_api.py tests/test_study_agent_runs.py -q
```

Expected: pass.

- [ ] **Step 5: Commit Task 2**

Run:

```bash
git add src/api/routes/study_agent.py tests/test_study_agent_api.py
git commit -m "feat: expose study agent run lifecycle api"
```

---

## Task 3: Frontend Run Diagnostics And Controls

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/components/StudyAgentPanel.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Add frontend API types and calls**

Add `StudyAgentRunDiagnostic`, `createStudyAgentRun`, `retryStudyAgentRun`, and `archiveStudyAgentRun`. Keep `queryStudyAgent` for compatibility.

- [ ] **Step 2: Update StudyAgentPanel**

Use `createStudyAgentRun` in the submit flow. Display compact run status with:

- status;
- attempt;
- short run id suffix;
- trace/workflow id suffix when present;
- retry button for failed/cancelled/timed_out/needs_review;
- archive button for terminal runs.

Treat `401` from run endpoints with `onAuthExpired()`.

- [ ] **Step 3: Add compact styles**

Add small run lifecycle styles without nesting cards inside cards.

- [ ] **Step 4: Run frontend build**

Run:

```bash
npm --prefix frontend run build
```

Expected: pass.

- [ ] **Step 5: Commit Task 3**

Run:

```bash
git add frontend/src/api.ts frontend/src/components/StudyAgentPanel.tsx frontend/src/styles.css
git commit -m "feat: show study agent run lifecycle controls"
```

---

## Task 4: Docs, Status, And Final Verification

**Files:**
- Modify: `README.md`
- Modify: `SPEC.md`
- Modify: `docs/superpowers/specs/2026-07-07-study-agent-run-lifecycle-design.md` only if implementation forces a clarified boundary.

- [ ] **Step 1: Update README**

Add a short status paragraph:

```markdown
Study Agent runs are now durable, owner-scoped lifecycle records. The product run API can create, inspect, cancel, pause, resume, retry, and archive runs while storing only safe request/result summaries such as query hashes, ids, counts, statuses, workflow ids, trace ids, and review flags.
```

- [ ] **Step 2: Update SPEC**

Add an implementation status bullet:

```markdown
- Study Agent run lifecycle: product runs are persisted as owner-scoped safe metadata with lifecycle controls for cancel, pause, resume, retry, and archive. Retry requires a fresh request payload and does not rely on stored raw query text.
```

- [ ] **Step 3: Run targeted backend verification**

Run:

```bash
pytest tests/test_study_agent_runs.py tests/test_study_agent_api.py tests/test_db_models.py tests/test_db_migrations.py tests/test_study_agent_runtime.py tests/test_study_agent_workflow.py tests/test_study_agent_traces.py -q
```

Expected: pass.

- [ ] **Step 4: Run frontend verification**

Run:

```bash
npm --prefix frontend run build
```

Expected: pass.

- [ ] **Step 5: Run whitespace/status checks**

Run:

```bash
git diff --check
git status --short --branch
```

Expected: `git diff --check` has no output; status shows only intended changes before commit, then clean after commit.

- [ ] **Step 6: Commit docs and final status**

Run:

```bash
git add README.md SPEC.md docs/superpowers/specs/2026-07-07-study-agent-run-lifecycle-design.md docs/superpowers/plans/2026-07-07-study-agent-run-lifecycle.md
git commit -m "docs: specify study agent run lifecycle"
```

## Final Review

After all tasks and per-task reviews pass, run:

```bash
pytest tests/test_study_agent_runs.py tests/test_study_agent_api.py tests/test_db_models.py tests/test_db_migrations.py tests/test_study_agent_runtime.py tests/test_study_agent_workflow.py tests/test_study_agent_traces.py tests/test_rag_route_policy.py tests/test_rag_router.py tests/test_graph_rag.py tests/test_agentic_rag.py tests/test_api_permissions_audit.py tests/test_rag_evaluation.py tests/test_rag_mode_comparison.py tests/test_study_agent_memory.py tests/test_study_agent_skills.py tests/test_study_agent_review_tasks.py -q
npm --prefix frontend run build
git diff --check
git status --short --branch
```

Then run final Spec review and Quality/privacy review across the whole branch before finishing.

## Self-Review

- Spec coverage: Tasks 1-4 cover persistence, safe metadata, owner isolation, lifecycle controls, retry linkage, audit hooks, frontend diagnostics, docs, and verification.
- Placeholder scan: The plan contains no `TBD`, `TODO`, or deferred implementation holes.
- Type consistency: `StudyAgentRunRecord`, `StudyAgentRunService`, `StudyAgentRunConflict`, `StudyAgentRunNotFound`, `StudyAgentRunDiagnostic`, and run statuses are consistently named.
- Scope check: This plan deliberately excludes queue-backed async execution, raw answer replay, raw query persistence, streaming, admin-wide search, and workflow engine replacement.
