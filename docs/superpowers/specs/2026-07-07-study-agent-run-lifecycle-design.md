# Study Agent Run Lifecycle Design

## Purpose

The Study Agent now has route policy, workflow timelines, review tasks, safe memory, skill metadata, and bounded expert diagnostics. The next productization slice must turn each Study Agent execution into a durable run that users and operators can inspect, cancel, pause, resume, retry, and archive without exposing private study content.

This slice creates the lifecycle contract first. It does not replace the current synchronous `StudyAgentRuntimeService` execution path with an asynchronous worker yet. The durable run record becomes the product boundary that a later queue-backed runner can consume.

## Current State

The product mainline already includes:

- `POST /api/study-agent/query` for authenticated, owner-scoped Study Agent execution.
- Safe workflow metadata with intake, plan, skill selection, retrieve, expert gate, generate, verify, review gate, and trace stages.
- `StudyAgentTraceService` persistence with query hashes, safe policy/skill/expert/workflow metadata, and no raw query or answer text.
- `StudyAgentReviewTaskService` for deterministic review task creation when workflow quality gates need human review.
- Audit events for Study Agent query and review task linkage.

The product still lacks:

- A durable Study Agent run id distinct from request id, workflow id, and trace id.
- A run state machine for queued, running, paused, resumed, completed, failed, cancelled, timed out, and archived states.
- Owner-scoped run detail/list endpoints.
- Lifecycle control endpoints for cancel, pause, resume, retry, and archive.
- A compact frontend run control/diagnostic panel.
- Safe run summaries that can be displayed or audited without raw query text, generated answer text, prompts, chunks, or source snippets.

## Decisions

- Add a dedicated `study_agent_runs` table instead of overloading `processing_jobs`.
- Keep document processing jobs and Study Agent reasoning runs separate.
- Keep `POST /api/study-agent/query` working for compatibility.
- Add `POST /api/study-agent/runs` as the product lifecycle entrypoint.
- The first implementation may execute the current runtime synchronously inside run creation, but every execution must create and update a durable run record.
- Lifecycle controls operate on the durable run record. Queue/worker pickup is a later slice.
- Retry does not rely on server-side raw query storage. The retry endpoint must receive a fresh request payload and link the new run to `retry_of_run_id`.
- Pause/resume are state transitions for queued or running run records in this slice. A later worker can honor them before stage execution.
- Archive is a soft lifecycle state, owner-scoped, and must not delete trace/review/audit records.
- Persist only safe request/result metadata:
  - query hash, not raw query;
  - document ids, target, preferred mode, budget, skill labels, expected term count;
  - workflow id, trace id, review task id;
  - safe status/error/reason labels;
  - counts, confidence, recall, latency, selected mode, and stage counts.
- Do not persist generated answer text, generated questions, prompts, raw chunk content, source snippets, hidden reasoning, exception strings, file paths, authorization headers, API keys, tokens, passwords, or secrets.

## Lifecycle Statuses

Allowed run statuses:

- `queued`: run record accepted but not executing.
- `running`: runtime execution has started.
- `paused`: execution should not continue until resumed. In the synchronous first slice this can be applied only to existing queued/running records through the service/API.
- `completed`: runtime returned a result that does not require review.
- `needs_review`: runtime returned a result that triggered workflow/review gates.
- `failed`: runtime failed with a safe error code.
- `cancelled`: user requested cancellation before terminal completion.
- `timed_out`: runtime exceeded the configured timeout boundary or a future worker marks it as timed out.
- `archived`: user hid the run from active views after it reached a terminal state.

Terminal statuses:

- `completed`
- `needs_review`
- `failed`
- `cancelled`
- `timed_out`
- `archived`

Valid transitions:

```text
queued -> running
queued -> paused
queued -> cancelled
running -> completed
running -> needs_review
running -> failed
running -> paused
running -> cancelled
running -> timed_out
paused -> queued
paused -> cancelled
completed -> archived
needs_review -> archived
failed -> archived
cancelled -> archived
timed_out -> archived
failed -> retry_child_queued
cancelled -> retry_child_queued
timed_out -> retry_child_queued
needs_review -> retry_child_queued
```

Invalid transitions must return a conflict response from the API and must not mutate the record.

## Data Contract

`StudyAgentRunRecord` stores:

- `id`: `run-<uuid hex>`.
- `owner_id`: authenticated user id.
- `request_id`: request id from request context.
- `status`: one allowed lifecycle status.
- `query_hash`: SHA-256 hash of the normalized query.
- `target`: safe Study Agent target label.
- `document_ids`: JSON list of safe document ids.
- `preferred_mode`: safe retrieval mode label or null.
- `selected_mode`: safe retrieval mode label or null after execution.
- `budget`: safe budget label or null.
- `skill_name`: safe skill name or null.
- `skill_version`: safe skill version or null.
- `expected_term_count`: integer count only.
- `workflow_id`: safe workflow id or null.
- `trace_id`: safe trace id or null.
- `review_task_id`: safe review task id or null.
- `retry_of_run_id`: safe parent run id or null.
- `attempt`: retry attempt number starting at `1`.
- `result_summary`: safe JSON metadata for display and audit.
- `error_code`: safe lifecycle error code or null.
- `error_message`: safe user-facing error label only, not raw exception text.
- `lifecycle_metadata`: safe JSON transition counters and reason labels.
- timestamps: `created_at`, `updated_at`, `started_at`, `completed_at`, `cancelled_at`, `paused_at`, `archived_at`.

`result_summary` may include only:

- `trace_id`
- `workflow_id`
- `review_task_id`
- `selected_mode`
- `policy_status`
- `category`
- `source_count`
- `used_chunk_count`
- `confidence`
- `source_recall`
- `answer_term_recall`
- `needs_review`
- `latency_ms`
- `stage_count`
- `expert_enabled`
- `expert_branch_count`
- `expert_timeout_count`
- `expert_failure_count`

## API Contract

### Create And Execute Run

`POST /api/study-agent/runs`

Request body is the existing `StudyAgentQueryRequest`.

Behavior:

1. Create owner-scoped run with `status="queued"` and safe request metadata.
2. Mark run `running`.
3. Execute the existing Study Agent runner.
4. Record trace, audit, workflow, and review task using the same safe helpers as `/query`.
5. Mark run:
   - `completed` when workflow does not need review;
   - `needs_review` when workflow or verification needs review;
   - `failed` when a safe handled error occurs.
6. Return the normal Study Agent result plus `run`.

### List Runs

`GET /api/study-agent/runs?status=&limit=`

Returns owner-scoped safe run summaries ordered newest first. Archived runs are included only when `status=archived` or `include_archived=true`.

### Get Run

`GET /api/study-agent/runs/{run_id}`

Returns one owner-scoped safe run detail. Cross-owner existing runs return `403`; missing runs return `404`.

### Cancel Run

`POST /api/study-agent/runs/{run_id}/cancel`

Allowed from `queued`, `running`, and `paused`. Marks `cancelled`, records audit event `study_agent_run.cancel_requested`, and returns the safe run payload. Terminal non-cancellable records return `409`.

### Pause Run

`POST /api/study-agent/runs/{run_id}/pause`

Allowed from `queued` and `running`. Marks `paused`, records audit event `study_agent_run.pause_requested`, and returns the safe run payload.

### Resume Run

`POST /api/study-agent/runs/{run_id}/resume`

Allowed from `paused`. Marks `queued`, records audit event `study_agent_run.resume_requested`, and returns the safe run payload. It does not execute runtime in this slice.

### Retry Run

`POST /api/study-agent/runs/{run_id}/retry`

Request body is `StudyAgentQueryRequest`. Allowed from `failed`, `cancelled`, `timed_out`, and `needs_review`. Creates a new child run with `retry_of_run_id` and `attempt=parent.attempt + 1`, executes it through the same create-run path, and returns the normal Study Agent result plus the new `run`.

### Archive Run

`POST /api/study-agent/runs/{run_id}/archive`

Allowed from `completed`, `needs_review`, `failed`, `cancelled`, and `timed_out`. Marks `archived`, records audit event `study_agent_run.archived`, and returns the safe run payload.

## Frontend Contract

The Study Agent panel should:

- Call `POST /api/study-agent/runs` instead of `/query` for user-triggered runs.
- Continue supporting the old result shape for compatibility.
- Display compact run status near workflow diagnostics.
- Show run id suffix, status, attempt, trace/workflow links when available, and retry/archive controls.
- Avoid displaying raw internal metadata.
- Treat `401` from run diagnostics the same way as existing Study Agent diagnostics.

The first frontend slice should keep the UI compact. It must not add a large admin dashboard.

## Audit And Privacy

Audit events must use safe metadata only:

- `study_agent_run.created`
- `study_agent_run.completed`
- `study_agent_run.failed`
- `study_agent_run.cancel_requested`
- `study_agent_run.pause_requested`
- `study_agent_run.resume_requested`
- `study_agent_run.retry_requested`
- `study_agent_run.archived`

Audit metadata may include run id, workflow id, trace id, status, selected mode, policy status, review flag, and reason code. It must not include raw query, answer, chunk, prompt, source snippet, exception string, token, password, authorization, secret, or file path.

## Out Of Scope

- Queue-backed asynchronous Study Agent worker.
- Streaming per-token output.
- Mid-stage cooperative cancellation inside every runtime subservice.
- Persisting raw query text for automatic retry.
- Raw answer replay from run detail.
- Admin-wide cross-user run search.
- A new workflow engine, Temporal/Celery integration, or external scheduler.
- Prompt mutation, self-improvement, or automatic skill evolution.

## Acceptance Criteria

- Runs are persisted with owner isolation and safe metadata only.
- `/api/study-agent/runs` returns successful Study Agent results with a `run` object.
- Failed runs are persisted with safe error labels and without raw exception text.
- List/detail/control endpoints enforce owner isolation.
- Cancel, pause, resume, retry, and archive follow the transition table.
- Retry links child run to parent and requires a fresh request payload.
- Audit events are recorded with safe metadata.
- Migration tests prove the table and indexes are ORM-compatible.
- Frontend build passes and the Study Agent panel shows compact run lifecycle diagnostics.
- Existing `/api/study-agent/query` behavior remains compatible.
