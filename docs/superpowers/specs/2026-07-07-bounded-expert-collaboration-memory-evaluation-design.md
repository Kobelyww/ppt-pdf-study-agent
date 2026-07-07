# Bounded Expert Collaboration And Memory Evaluation Design

## Purpose

The previous productization slice stabilized the Study Agent workflow supervisor, review tasks, owner-scoped safe memory, versioned skill metadata, and legacy agent boundaries. The next stage can now add more agentic behavior, but it should remain bounded, observable, and reversible.

This design combines two related vertical slices:

1. Bounded expert collaboration for high-value study categories.
2. Memory-guided evaluation for skill and routing quality signals.

The two slices are implemented together because expert execution needs quality telemetry, and skill quality telemetry becomes more useful when it can compare serial and expert-assisted paths. They remain separate service boundaries so either slice can be disabled without breaking the core Study Agent runtime.

## Current State

The product mainline already includes:

- `StudyAgentRuntimeService` as the authenticated Study Agent runtime path.
- `StudyAgentOrchestrator`, `EvidenceCollector`, `StudyContentGenerator`, and `StudyVerifier`.
- `RAGStrategyRouter` and `RAGRoutePolicyService` for category, budget, readiness, index-health, and feature-flag gating.
- `ReviewGate` and safe workflow metadata.
- `StudyAgentTraceService` with privacy-safe policy and skill metadata.
- `StudyAgentReviewTaskService` for idempotent review task creation.
- `StudyAgentMemoryService` for owner-scoped safe preferences and review outcomes.
- `StudySkillRegistry` for versioned study skills.

The product still lacks:

- Optional parallel expert branches for synthesis-heavy categories.
- Explicit expert execution contracts and timeout/fallback behavior.
- Skill performance aggregation from trace/review/memory metadata.
- A compact way to inspect skill quality without reading raw conversations.

## Decisions

- Keep the deterministic Study Agent workflow as the product mainline.
- Add expert collaboration as an optional runtime extension, not a replacement.
- Enable expert branches only when route policy, readiness, index health, category, and budget gates all allow advanced retrieval.
- Default to safe serial fallback when an expert branch fails, times out, or is disabled.
- Keep expert branch outputs bounded and typed.
- Persist only safe expert metadata in workflow, trace, audit, and memory paths.
- Use memory-guided evaluation for aggregate quality signals only.
- Do not implement automatic prompt mutation, DSPy/GEPA optimization, hidden self-improvement loops, or model-generated skill changes in this stage.
- Do not introduce a graph database; reuse the existing in-memory/service-level graph and persisted document chunk infrastructure.

## Scope

### In Scope

- Expert branch policy gate.
- Expert branch result contracts.
- Serial fallback and timeout handling.
- Runtime workflow/trace metadata for expert execution counts and safe failure labels.
- Skill performance aggregate service based on safe trace/review/memory metadata.
- Read-only skill performance API.
- Compact frontend diagnostics for expert execution and skill performance.
- Tests for owner isolation, privacy filtering, policy blocking, timeout fallback, and deterministic aggregates.

### Out Of Scope

- Open-ended autonomous agent loops.
- Automatic prompt evolution or skill contract mutation.
- DSPy/GEPA execution.
- Long-form expert reasoning display.
- Raw memory or conversation replay.
- Admin-wide cross-user memory search.
- A large analytics dashboard.
- New vector provider or graph database integration.

## Bounded Expert Collaboration

### Eligible Categories

Expert collaboration may run only when the routed category is one of:

- `multi_document_synthesis`
- `question_generation`

All of the following must also be true:

- `RAGRoutePolicyDecision.status == "allowed"`.
- `RAGRoutePolicyDecision.selected_mode` is `agentic_rag` or `graph_rag_lite`.
- The selected skill allows the selected retrieval mode.
- Persisted chunks are indexed and healthy for requested documents when advanced retrieval requires them.
- The request budget allows the selected advanced mode.
- Expert collaboration feature flag is enabled.

If any gate fails, the runtime must use the existing serial Study Agent path and record only a safe skip reason.

### Expert Roles

`RetrievalExpert`

- Reads owner-scoped evidence chunks already selected for the request.
- Emits source ids, chunk counts, and confidence only.
- Does not emit raw chunk text into workflow/trace metadata.

`GraphExpert`

- Uses existing graph structures when available.
- Emits concept ids, graph hop counts, and fallback reason codes.
- Falls back safely when no graph is configured or no seed concept matches.

`QuestionExpert`

- Runs only for `question_generation`.
- Produces a bounded structured question draft for synthesizer input.
- Does not persist generated question text in workflow/trace metadata.

`SynthesisExpert`

- Merges typed branch outputs into one bounded synthesis payload.
- Records selected source ids, branch counts, timeout counts, confidence, and reason codes.
- The final user-visible answer/question still flows through the existing generator/verifier/review gate path.

### Expert Result Contract

Each expert branch may produce two layers of output:

1. Internal typed payload for the current request only. This can be used by the synthesizer and generator, but it must not be persisted in workflow, trace, audit, memory, or review task metadata.
2. Safe branch metadata for persistence and diagnostics.

The safe metadata contract is:

```python
ExpertBranchResult(
    branch_name: str,
    status: Literal["passed", "skipped", "failed", "timeout"],
    source_ids: tuple[str, ...],
    concept_ids: tuple[str, ...],
    confidence: float,
    metrics: dict[str, int | float | bool | str],
    safe_reason_code: str | None,
)
```

Allowed `branch_name` values:

- `retrieval_expert`
- `graph_expert`
- `question_expert`
- `synthesis_expert`

Allowed `safe_reason_code` values:

- `expert_disabled`
- `category_not_eligible`
- `policy_not_allowed`
- `mode_not_allowed_by_skill`
- `index_not_ready`
- `budget_not_allowed`
- `branch_timeout`
- `branch_error`
- `graph_unavailable`
- `serial_fallback`

The contract must reject or sanitize:

- raw query text;
- generated answer/question text;
- raw chunk content;
- source snippets;
- prompts;
- hidden reasoning;
- exception strings;
- paths, tokens, passwords, authorization headers, API keys, and secrets.

### Runtime Flow

Recommended high-level flow:

```text
intake
-> skill_select
-> plan
-> retrieve
-> expert_gate
-> expert_branches (optional)
-> generate
-> verify
-> review_gate
-> memory_update
-> trace
```

The first implementation may keep expert execution inside a single `expert_gate` workflow stage if that keeps metadata simpler. Separate branch stage labels can be added later only if the sanitizer and frontend need them.

### Timeout And Fallback

- Expert execution must have a configured branch timeout.
- Branch timeout must produce `status="timeout"` and `safe_reason_code="branch_timeout"`.
- If one branch times out, the runtime should continue with available safe branch results when possible.
- If all branches fail or time out, the runtime must fall back to the serial Study Agent path.
- Fallback must set safe workflow metadata:
  - `expert_branch_count`
  - `expert_timeout_count`
  - `expert_failure_count`
  - `expert_fallback_reason`

### Owner Isolation

Expert branches must only receive evidence already scoped to:

- `authenticated_user_id`
- requested `document_ids`
- current runtime evidence source

Tests must prove a branch cannot receive cross-owner chunks or source ids.

## Memory-Guided Evaluation

### Goal

Use safe memory, review task, and trace metadata to evaluate skill and routing quality. This slice produces read-only quality signals. It does not change prompts, mutate skill definitions, or automatically promote/demote skill versions.

### Aggregate Metrics

The service should aggregate by owner and optionally by skill:

- `run_count`
- `needs_review_count`
- `review_rate`
- `fallback_count`
- `fallback_rate`
- `expert_run_count`
- `expert_timeout_count`
- `average_confidence`
- `average_source_recall`
- `average_answer_term_recall`
- `review_reason_counts`

The first version can compute aggregates from:

- `StudyAgentTraceRecord.trace_metadata.policy`
- `StudyAgentTraceRecord.trace_metadata.skill`
- `StudyAgentTraceRecord.trace_metadata.workflow`
- safe `StudyAgentMemoryRecord` categories such as `review_outcome`
- review task status/reason metadata

It must not read raw query text, generated content, chunk text, source snippets, or prompts.

### API Boundary

Add a narrow read-only endpoint:

```text
GET /api/study-agent/skills/performance
```

Optional query parameters:

- `skill_name`
- `skill_version`

The endpoint returns owner-scoped aggregate metrics only. It must not expose cross-owner totals unless a future admin-specific API is designed and reviewed.

Example response:

```json
{
  "skills": [
    {
      "skill_name": "concept_explanation",
      "skill_version": "v1",
      "run_count": 12,
      "review_rate": 0.17,
      "fallback_rate": 0.08,
      "expert_run_count": 0,
      "expert_timeout_count": 0,
      "average_confidence": 0.74,
      "average_source_recall": 0.91,
      "average_answer_term_recall": 0.83,
      "review_reason_counts": {
        "low_confidence": 2
      }
    }
  ]
}
```

The literal authenticated owner id should not be included in this endpoint unless a future product convention explicitly requires it.

### Frontend Boundary

The frontend may show compact diagnostics near existing Study Agent skill/workflow diagnostics:

- selected skill name/version;
- expert branch count;
- expert timeout count;
- fallback reason code;
- skill review rate;
- skill fallback rate.

Avoid:

- raw memory inspection;
- raw trace inspection;
- expert reasoning text;
- large dashboards;
- admin-wide comparisons.

## Data And Metadata

### Workflow Metadata

Allowed new workflow summary keys:

- `expert_branch_count`
- `expert_timeout_count`
- `expert_failure_count`
- `expert_fallback_reason`
- `expert_enabled`

Allowed values must be booleans, non-negative counts, or allowlisted reason codes.

### Trace Metadata

Trace metadata may include:

```json
{
  "expert": {
    "enabled": true,
    "branch_count": 3,
    "timeout_count": 0,
    "failure_count": 0,
    "fallback_reason": null,
    "branch_statuses": {
      "retrieval_expert": "passed",
      "graph_expert": "passed",
      "question_expert": "skipped"
    }
  }
}
```

All keys and values must be sanitized through explicit allowlists.

### Memory Metadata

Memory-guided evaluation should not create broad new memory records in the first implementation. If a `skill_performance` memory record is added later, it must be aggregate only and owner scoped.

## Error Handling

- Invalid expert configuration should disable expert branches and use serial fallback.
- Branch exceptions should be converted to safe reason codes, not exposed.
- Timeout should be deterministic in tests.
- Missing graph should not fail the request.
- Missing memory store should not fail the Study Agent response or performance summary endpoint; it should return empty aggregates or a clear configured 503 depending on existing API pattern.

## Tests

Required backend tests:

- Expert branches do not run for non-eligible categories.
- Expert branches run for eligible categories only when policy/readiness/index/budget gates allow them.
- Budget block prevents expert execution.
- Readiness block prevents expert execution.
- Skill retrieval-mode mismatch prevents expert execution.
- Branch timeout records safe timeout metadata and falls back.
- Branch exception records safe failure metadata and falls back.
- Synthesizer/expert branches do not receive cross-owner evidence.
- Workflow metadata contains only safe expert labels/counts.
- Trace metadata contains only safe expert labels/counts.
- Skill performance summary is owner scoped.
- Skill performance summary is deterministic.
- Skill performance summary aggregates review/fallback/confidence/recall without raw content.
- API response omits raw query, generated text, chunk content, prompt, hidden reasoning, paths, tokens, and secrets.

Required frontend checks:

- TypeScript build passes.
- Expert diagnostics render compact labels/counts only.
- Skill performance diagnostics do not render raw memory or trace text.

## Acceptance Criteria

- Expert collaboration is disabled by default unless explicit config/policy gates allow it.
- Expert collaboration runs only for eligible categories.
- Expert branch failure or timeout does not break the serial Study Agent path.
- Expert workflow/trace metadata contains labels and counts only.
- Memory-guided evaluation returns owner-scoped aggregate metrics only.
- No raw query, generated answer/question text, chunk content, source snippets, prompts, hidden reasoning, paths, tokens, passwords, authorization headers, API keys, or secrets are persisted in expert or evaluation metadata.
- Frontend build passes if frontend diagnostics are touched.
- Existing Study Agent review task, memory, skill, trace, and route policy tests remain passing.

## Implementation Slices

### Slice 1: Expert Contracts And Policy Gate

- Add expert config and result schemas.
- Add expert eligibility service.
- Add sanitizer tests.

### Slice 2: Runtime Expert Execution

- Add optional expert branch runner.
- Wire timeout/fallback into runtime.
- Persist safe workflow and trace metadata.

### Slice 3: Skill Performance Aggregation

- Add owner-scoped aggregate service.
- Add read-only API endpoint.
- Add deterministic tests.

### Slice 4: Frontend Compact Diagnostics

- Add API types.
- Render expert counts and skill performance summary.
- Keep UI compact and non-dashboard.

### Slice 5: Documentation And Verification

- Update README/SPEC status.
- Run targeted backend and frontend verification.
- Review spec compliance and quality/privacy before merge.
