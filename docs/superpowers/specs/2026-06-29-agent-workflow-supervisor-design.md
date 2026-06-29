# Agent Workflow Supervisor Design

## Purpose

The current Study Agent can authenticate a user, load document evidence, apply RAG route policy, collect evidence, generate a draft, verify the result, and record safe trace and audit metadata. That is a solid product chain, but it still behaves like a single service call rather than an explicit multi-agent workflow.

This design adds a formal runtime agent workflow supervisor and a matching development governance workflow. The runtime side makes Planner, Retrieval, Generator, Verifier, and Review Gate responsibilities visible and testable. The development side keeps implementation disciplined through spec review, quality review, verification, and merge gates.

The goal is not to build an open-ended autonomous agent. The first version should be deterministic, observable, owner-scoped, privacy-safe, and easy to extend later with stronger model providers or parallel expert agents.

## Current State

The product mainline already includes:

- `StudyAgentRuntimeService`, which loads owner-scoped document evidence, chooses persisted chunks when healthy, applies route policy, runs the orchestrator, and records latency metadata.
- `StudyAgentOrchestrator`, which plans, collects evidence, generates content, verifies the draft, and returns `StudyAgentResult`.
- `RAGRoutePolicyService`, which selects a safe retrieval mode using feature flags, readiness, budget, index health, and category gates.
- `StudyAgentTraceService`, which persists safe trace summaries and avoids raw query text, generated answers, chunk content, source snippets, prompts, hidden reasoning, tokens, passwords, and secrets.
- Review task APIs and feedback services, currently oriented around user feedback and manual decisions.
- Frontend diagnostics for mode, policy, confidence, recall, fallback, citations, and review status.

The remaining gap is explicit workflow structure. Operators and users can see the result and some diagnostics, but not a structured stage timeline, failed stage, skipped stage, review gate reason, or safe stage-level input/output summary.

## Decisions

- Use a supervisor stage model as the first runtime workflow form.
- Keep the implementation deterministic and service-based. Agent roles are boundaries first; future LLM-backed agent behavior can plug into those boundaries later.
- Do not replace `StudyAgentRuntimeService`; wrap or compose its responsibilities into explicit stages.
- Keep the workflow synchronous for the first version. Async job execution, cancellation, and resume are defined as later extensions.
- Keep Review Gate v1 as a decision stage only. Automatic persisted `review_tasks` creation is a later implementation slice.
- Store only safe stage summaries. Raw user queries, draft text, chunk content, source snippets, prompts, hidden reasoning, credentials, and secrets must not be persisted in workflow metadata.
- Put development governance in the same spec so runtime workflow changes are implemented with repeatable subagent, review, and verification gates.

## Runtime Workflow

### Supervisor

Add a service boundary named `StudyAgentWorkflowSupervisor`.

Responsibilities:

- Normalize the user request.
- Execute named stages in order.
- Pass typed stage context between stages.
- Record stage status, safe summaries, timing, fallback, review reasons, and error codes.
- Produce an aggregate workflow status.
- Return the existing Study Agent result plus a compact workflow payload.
- Persist or forward the workflow timeline through the existing trace path.

The supervisor should be a thin orchestration layer. It should not own retrieval algorithms, generation logic, verification scoring, authorization, or storage internals.

### Stage Order

The first version uses this ordered pipeline:

1. `intake`
2. `plan`
3. `retrieve`
4. `generate`
5. `verify`
6. `review_gate`
7. `trace`

This is intentionally serial. Parallel expert collaboration can be added after the stage contract is stable.

### Agent Roles

`Intake Agent`

- Normalizes `query`, `target`, `document_ids`, `budget`, `preferred_mode`, and `expected_terms`.
- Confirms authenticated user context exists.
- Confirms document scope is supplied when required by the product path.
- Emits safe counts and labels only.

`Planner Agent`

- Calls `RAGStrategyRouter` and `RAGRoutePolicyService`.
- Produces selected mode, router mode, category, policy status, fallback chain, readiness status, and estimated cost.
- Does not include raw query text in stage summaries.

`Retrieval Agent`

- Loads processed document evidence.
- Chooses persisted chunks or query-time fallback.
- Runs simple RAG, Graph RAG Lite, or bounded Agentic RAG evidence collection.
- Emits chunk count, source count, concept count, chunk source, index status counts, fallback reason, and graph/agentic safe metadata.

`Generator Agent`

- Produces answer, question, or outline fragment from evidence.
- Emits target, citation count, used chunk count, and generation metadata.
- Does not persist generated answer text in workflow metadata.

`Verifier Agent`

- Checks citation coverage, evidence confidence, source recall, expected term recall, and empty evidence.
- Emits passed flag, confidence, recall metrics, and issue codes.
- Does not persist raw expected terms beyond counts unless already safe allowlisted labels.

`Review Gate Agent`

- Converts verifier and policy results into a product decision.
- Emits `passed`, `needs_review`, `failed`, or `skipped`.
- Emits structured review reason codes.
- Does not create persisted review tasks in v1.

`Trace Agent`

- Persists or returns the workflow timeline through safe trace metadata.
- Ensures metadata is value-sanitized before persistence or API exposure.
- Emits workflow id, status, stage count, and completed timestamp.

## Stage Contract

Every stage returns a `WorkflowStageResult`-style object:

```python
@dataclass(frozen=True)
class WorkflowStageResult:
    stage_name: str
    status: str
    input_summary: dict[str, Any]
    output_summary: dict[str, Any]
    started_at: datetime
    completed_at: datetime | None
    duration_ms: float | None
    error_code: str | None = None
    review_reason: str | None = None
    trace_metadata: dict[str, Any] = field(default_factory=dict)
```

Allowed stage statuses:

- `pending`
- `running`
- `passed`
- `failed`
- `skipped`
- `needs_review`

Allowed workflow statuses:

- `completed`
- `completed_with_fallback`
- `needs_review`
- `partial`
- `failed`
- `cancelled`

`cancelled` is reserved for future async execution. The synchronous v1 should not expose cancellation controls.

## Stage Summary Privacy

Stage summaries may include:

- IDs already safe for the authenticated owner: `workflow_id`, `request_id`, `document_ids`.
- Counts: document count, chunk count, source count, concept count, issue count.
- Safe labels: target, retrieval mode, query category, policy status, readiness status, fallback reason code, review reason code.
- Safe metrics: confidence, source recall, answer term recall, duration, latency, cost label.
- Safe booleans: needs review, fallback used, persisted chunks used.

Stage summaries must not include:

- Raw query text.
- Generated answer or question text.
- Chunk content.
- Source snippets.
- Prompts or hidden reasoning.
- Tokens, passwords, authorization headers, API keys, secrets.
- Unvalidated arbitrary strings from user or model output.

Any field that can contain arbitrary user or model text must be omitted, hashed, counted, or mapped to an allowlisted code before entering workflow metadata.

## Error Handling

Errors are grouped into four classes.

`recoverable`

- Examples: no graph seed, graph chunk recovery empty, agentic step budget exhausted, persisted chunks missing or stale.
- Behavior: fallback to the next safe mode, continue workflow, record fallback reason.
- Final status: `completed_with_fallback`, `partial`, or `needs_review` depending on verifier output.

`needs_review`

- Examples: low confidence, missing citations, source recall below threshold, expected terms missing, multi-document synthesis using fallback evidence.
- Behavior: return result with `review_gate.status = needs_review`.
- Final status: `needs_review`.

`blocked`

- Examples: route policy blocks advanced routing, readiness unavailable, index health unsuitable for advanced mode.
- Behavior: fallback to simple RAG when configured; otherwise fail the workflow with a safe error code.
- Final status: `completed_with_fallback`, `needs_review`, or `failed`.

`fatal`

- Examples: unauthenticated request, unsupported target, unsupported retrieval mode, forbidden document, processed evidence missing.
- Behavior: stop workflow, return existing API error semantics.
- Final status: `failed`.

## Review Gate Rules

Review Gate v1 marks a workflow as `needs_review` when any of these are true:

- `verification.needs_review` is true.
- `verification.confidence` is below the configured threshold.
- Draft citation count is zero.
- Evidence chunk count is zero.
- Policy status is a blocked status and fallback did not complete successfully.
- Evidence fallback reason is present for `question_generation` or `multi_document_synthesis`.
- Agentic RAG step budget is exhausted.

Review Gate v1 does not automatically create persisted review tasks. The next slice may create review tasks for authenticated owners using the existing review task model, with explicit tests for owner isolation and audit metadata.

## Data Model

Prefer extending the existing Study Agent trace path before adding a large new workflow table.

Recommended persisted fields:

- `workflow_id`
- `request_id`
- `owner_id`
- `workflow_status`
- `target`
- `selected_mode`
- `category`
- `needs_review`
- `stage_timeline`
- `policy_summary`
- `quality_summary`
- `created_at`
- `completed_at`

`stage_timeline` is a JSON list of safe stage summaries:

```json
{
  "stage": "retrieve",
  "status": "passed",
  "duration_ms": 34.2,
  "input_summary": {
    "document_count": 2,
    "mode": "graph_rag_lite"
  },
  "output_summary": {
    "chunk_count": 5,
    "source_count": 3,
    "fallback_reason": null
  },
  "error_code": null,
  "review_reason": null
}
```

If the existing trace table cannot hold the timeline cleanly, add a narrowly scoped `study_agent_workflows` table in a later implementation task. Do not add a general workflow engine schema in v1.

## API Boundary

Extend `POST /api/study-agent/query`.

Response adds:

```json
{
  "workflow": {
    "workflow_id": "workflow-...",
    "status": "completed",
    "current_stage": "trace",
    "needs_review": false,
    "stage_count": 7,
    "stages": []
  }
}
```

The response may include compact stages, but each item must follow the safe summary rules.

Add `GET /api/study-agent/workflows/{workflow_id}` after persistence exists.

Requirements:

- Owner isolation for normal users.
- Admin cross-user query is out of scope for v1.
- No raw audit metadata in public response.
- No raw query, answer, chunks, prompts, hidden reasoning, or secrets in workflow payloads.

`GET /api/study-agent/workflows` is optional for v1. It can wait until the single-workflow detail endpoint is stable.

## Frontend Boundary

The frontend should show a compact workflow timeline near the Study Agent result.

Display:

- Workflow status.
- Selected mode.
- Current or final stage.
- Needs review flag.
- Stage list with icon/status, duration, and reason code.

Avoid:

- A large analytics dashboard.
- Raw debug panels.
- Prompt or chunk inspection.
- User-facing instructional text explaining the workflow mechanics.

The UI should feel operational and scan-friendly, consistent with the current workbench.

## Development Governance Workflow

Runtime workflow work must follow this governance path:

```text
Spec -> Plan -> Subagent Implementation -> Spec Review -> Quality Review -> Verification -> Merge
```

Rules:

- A written spec is required before implementation.
- A written implementation plan is required before code changes.
- Implementation tasks should use subagents when tasks are independent and write scopes can be bounded.
- Every task must include tests sized to the risk.
- After each task, run two reviews:
  - Spec compliance review.
  - Quality and privacy review.
- Review findings must be fixed before moving to the next task.
- Final merge requires backend tests, frontend build when UI/types are touched, clean worktree, and no generated report artifacts.

Quality review must explicitly check:

- Owner isolation.
- Trace and audit privacy.
- Fallback behavior.
- Deterministic behavior.
- Backward compatibility.
- Stage summary allowlists.
- Tests for failure and review paths.

## Implementation Slices

### P0: Workflow Contracts And In-Memory Timeline

- Add workflow dataclasses and status enums.
- Wrap existing Study Agent execution with stage timeline creation.
- Return workflow payload from `POST /api/study-agent/query`.
- Add tests for completed, fallback, failed, and needs-review timelines.

### P1: Trace Persistence And Workflow Detail API

- Persist safe workflow timeline in trace metadata or a narrow workflow table.
- Add `GET /api/study-agent/workflows/{workflow_id}`.
- Add owner isolation and privacy tests.

### P2: Review Gate Integration

- Add Review Gate reason codes.
- Add deterministic review-gate tests for low-confidence, missing-citation, policy-blocked, and fallback-heavy results.
- Keep persisted review task creation as a separate follow-up task after reason codes are stable.
- When review task creation is implemented, add audit events without raw content.

### P3: Parallel Expert Extensions

- Add optional parallel expert branches for multi-document synthesis and question generation.
- Add Synthesizer role only after serial supervisor behavior is stable.
- Keep route policy and budget gates in front of high-cost branches.

## Acceptance Criteria

- Definition query completes all required stages with workflow status `completed`.
- Graph query that falls back to simple RAG records fallback in retrieve stage and returns `completed_with_fallback` or `needs_review`.
- Low confidence result returns workflow status `needs_review`.
- Missing citations trigger Review Gate.
- Policy-blocked advanced mode can fallback to simple RAG and records blocked reason without failing the entire workflow.
- Fatal document evidence errors return existing API status codes and do not expose raw query or content.
- Workflow payload and persisted timeline contain no raw query, generated answer, chunk content, source snippets, prompts, hidden reasoning, token, password, authorization, or secret values.
- Workflow detail API enforces owner isolation.
- Frontend renders compact workflow status and stage timeline.
- Backend tests and frontend build pass.
- Each implementation task passes spec review and quality review before the next task starts.

## Non-Goals

- No open-ended autonomous agent loop in v1.
- No async cancellation or resume in v1.
- No new graph database.
- No prompt mutation, DSPy/GEPA, or self-evolution work.
- No large workflow dashboard.
- No admin cross-user workflow search in v1.
- No provider-specific LLM optimization.

## Open Questions Resolved

- Runtime and development workflows belong in the same spec.
- Runtime implementation is prioritized first.
- Supervisor serial stage orchestration is the first implementation style.
- Parallel expert collaboration and review task creation are later extensions.
