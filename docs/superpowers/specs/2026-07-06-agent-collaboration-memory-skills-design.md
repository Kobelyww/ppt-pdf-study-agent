# Agent Collaboration, Skills, And Memory Productization Design

## Purpose

The current Study Agent product line has a stable deterministic workflow supervisor, safe trace persistence, route policy gates, frontend workflow diagnostics, and review status metadata. That is the right foundation for a formal product.

The next product slice should not jump directly into an open-ended autonomous agent loop. It should first make the agent collaboration model, skill boundary, and memory behavior explicit, owner-scoped, testable, and privacy-safe.

This design defines the next stage after the Agent Workflow Supervisor:

- Review Gate to persisted review task loop.
- Memory feedback loop for user preferences, review outcomes, and learning state.
- Versioned skill registry for bounded study capabilities.
- Optional expert collaboration only after the above contracts are stable.

## Current State

The product mainline already includes:

- `StudyAgentRuntimeService`, which owns the authenticated Study Agent runtime path.
- `StudyAgentOrchestrator`, which plans, retrieves evidence, generates a draft, and verifies output.
- `RAGRoutePolicyService`, which keeps advanced retrieval behind feature, readiness, index health, budget, and category gates.
- `StudyAgentTraceService`, which persists privacy-safe trace and workflow metadata.
- `ReviewGate`, which emits deterministic review reason codes.
- Review task APIs and review task persistence for product workflows.
- A legacy `BaseAgent` and `MainCoordinator` path that still models specialist agents as a serial pipeline.
- A prototype `MemoryService` with in-process short-term memory and SQLite long-term memory.

The main gap is product alignment. The project now has multiple meanings for "agent":

- Legacy specialist agents used by `MainCoordinator`.
- Study Agent service roles such as planner, retrieval, generator, verifier, and review gate.
- Future expert branches for multi-document synthesis, question generation, and graph-assisted reasoning.

For a formal product, the Study Agent workflow should be the primary path. Legacy agents should either become bounded tools behind clear interfaces or remain explicitly legacy.

## Decisions

- Keep Study Agent workflow supervisor as the product mainline.
- Do not add an open-ended autonomous agent loop in this slice.
- Treat "agent roles" as service boundaries and capability contracts before making any role LLM-backed.
- Convert Review Gate decisions into persisted review tasks before adding more autonomous behavior.
- Make memory owner-scoped, privacy-safe, and opt-in by category.
- Make skills versioned and evaluable before prompt or skill evolution.
- Keep advanced collaboration behind route policy, budget gates, and readiness checks.
- Keep raw query text, generated answer text, chunk content, source snippets, prompts, hidden reasoning, tokens, passwords, authorization headers, API keys, and secrets out of memory, skill telemetry, workflow metadata, and audit metadata unless explicitly stored as user-visible content in the existing product result path.

## P0: Review Gate To Review Task Loop

### Goal

When the Study Agent determines that a result needs review, the product should create or link a persisted review task for the authenticated owner. This turns `needs_review` from a diagnostic flag into an actionable quality workflow.

### Behavior

The Review Gate should create a review task when:

- `workflow.status == needs_review`, or
- review gate stage status is `needs_review`, or
- verifier marks `needs_review`, or
- policy/fallback rules produce one of the configured review reason codes.

The task should include safe metadata only:

- `workflow_id`
- `trace_id`
- `request_id`
- `owner_id`
- target type
- selected mode
- query category
- review reason codes
- confidence and recall metrics
- source count, chunk count, citation count, and issue count

The task must not include:

- raw user query
- generated answer or question text
- chunk content
- source snippets
- prompts
- hidden reasoning
- secrets or credentials

### Idempotency

Repeated calls or retries for the same `workflow_id` and owner must not create duplicate open review tasks.

Recommended unique key:

```text
owner_id + workflow_id + target_type
```

If an existing open task is found, the runtime should return or link it instead of creating another one.

### API And Frontend

The Study Agent query response may add a compact review task summary:

```json
{
  "review_task": {
    "id": "review-...",
    "status": "open",
    "reason": "low_confidence"
  }
}
```

The frontend should show a compact link or status badge near the workflow timeline. It should not add a dashboard in this slice.

### Tests

Required tests:

- Review task is created for low-confidence output.
- Review task is created for fallback-heavy question generation or outline generation.
- Duplicate query retry with the same workflow id does not create duplicate open tasks.
- Review task creation respects owner isolation.
- Audit metadata for review task creation excludes raw content.
- Existing review task APIs keep working.

## P1: Product Memory Service

### Goal

Replace the prototype memory path with a product memory service that supports owner-scoped, privacy-safe, purpose-specific memory records.

This is not a general "remember everything" system. It should store only memory categories that improve study quality and can be explained to a user or operator.

### Memory Categories

`user_preference`

- Examples: preferred answer style, preferred language, desired difficulty, explanation depth.
- Source: explicit user settings or repeated user feedback.
- Retention: long lived until changed or deleted.

`study_state`

- Examples: document progress, mastered concept ids, weak concept ids, recent target types.
- Source: completed study sessions, feedback, review outcomes.
- Retention: owner scoped and document scoped.

`review_outcome`

- Examples: review decision, safe reason code, quality label, accepted correction category.
- Source: review task decisions.
- Retention: used for quality analysis and future routing, not for raw answer replay.

`skill_performance`

- Examples: skill name, skill version, pass/fail counts, review rate, fallback rate.
- Source: Study Agent traces and evaluation runs.
- Retention: aggregate only.

### Data Model

Recommended table: `study_agent_memories`.

Fields:

- `id`
- `owner_id`
- `scope_type`: `user`, `document`, `workflow`, or `skill`
- `scope_id`
- `category`
- `key`
- `value_json`
- `confidence`
- `source_type`
- `source_id`
- `privacy_level`
- `created_at`
- `updated_at`
- `expires_at`

The `value_json` field must be schema-validated per category. Arbitrary strings from users or models must not be stored unless the category explicitly allows it.

### Recall Contract

Memory recall should return safe summaries, not raw conversation logs.

Inputs:

- `owner_id`
- `document_ids`
- `target`
- `selected_mode`
- `skill_name`

Outputs:

- preference labels
- weak concept ids
- mastered concept ids
- prior review reason counts
- skill performance aggregates

### Runtime Integration

Memory should be used in three places:

1. Planner: adjust safe route hints, difficulty, and target expectations.
2. Generator: apply user preference labels such as concise, detailed, bilingual, or exam-focused.
3. Review Gate: increase scrutiny when the same skill, concept, or document repeatedly needs review.

Memory should not directly inject raw previous answers into generation in this slice.

### Tests

Required tests:

- Owner A cannot recall Owner B memory.
- Raw query, generated answer, chunk text, prompt, token, secret, or source snippet is rejected or omitted.
- Review decision can create a `review_outcome` memory.
- User preference can influence generator metadata without changing owner isolation.
- Expired memory is not returned.
- Memory recall is deterministic for identical inputs.

## P1: Versioned Study Skill Registry

### Goal

Make study capabilities explicit and versioned. A skill is a bounded product capability with input schema, output schema, privacy rules, route policy, and evaluation cases.

The registry should not mutate prompts or run self-evolution in this slice. It should make skills observable and testable first.

### Initial Skills

`concept_explanation`

- Target: answer
- Purpose: explain a concept using cited document evidence.

`practice_question`

- Target: question
- Purpose: generate a practice question, answer, explanation, and rubric.

`outline_fragment`

- Target: outline_fragment
- Purpose: produce source-grounded study notes.

`concept_relation`

- Target: answer
- Purpose: compare or relate concepts, usually with Graph RAG Lite.

`multi_document_synthesis`

- Target: answer or question
- Purpose: synthesize across documents when route policy allows advanced retrieval.

### Skill Contract

Each skill version should define:

- `skill_name`
- `version`
- `supported_targets`
- `input_schema`
- `output_schema`
- `allowed_retrieval_modes`
- `default_budget`
- `review_gate_profile`
- `memory_inputs`
- `memory_outputs`
- `privacy_policy`
- `evaluation_cases`

### Runtime Integration

Skill selection should happen after request normalization and before retrieval planning.

Suggested flow:

```text
intake -> skill_select -> plan -> retrieve -> generate -> verify -> review_gate -> memory_update -> trace
```

The existing workflow can add `skill_select` and `memory_update` stages once contracts are stable.

### Tests

Required tests:

- Query target maps to the expected default skill.
- Unsupported skill version is rejected.
- Skill route policy blocks advanced retrieval when not ready.
- Skill output contract is validated before returning result.
- Skill metadata in trace is safe and does not include raw content.

## P2: Bounded Expert Collaboration

### Goal

Add parallel expert branches only for cases where they improve study quality and remain bounded by policy.

This is an extension of the deterministic supervisor, not an autonomous loop.

### Eligible Categories

Parallel expert collaboration is allowed only when:

- query category is `multi_document_synthesis` or `question_generation`, and
- advanced routing is enabled, and
- readiness marks the selected advanced mode as candidate, and
- persisted chunks are healthy, and
- budget allows the selected mode.

### Expert Roles

`Retrieval Expert`

- Finds direct evidence.
- Emits source and chunk counts only in metadata.

`Graph Expert`

- Expands concept ids and prerequisites.
- Emits concept ids, graph hop counts, and fallback reason codes.

`Question Expert`

- Shapes question, answer, explanation, and rubric from evidence.
- Does not persist generated content in workflow metadata.

`Synthesizer`

- Merges expert outputs into one draft.
- Records only safe counts, confidence, and selected evidence ids.

`Verifier`

- Applies existing verifier and review gate profiles.

### Coordination Rules

- Maximum branch count must be configured.
- Maximum branch duration must be configured.
- Every branch must return a typed result or safe failure code.
- Branch outputs must pass the same privacy sanitizer as workflow metadata.
- Branch failure must degrade to serial Study Agent behavior unless the selected skill requires expert output.

### Tests

Required tests:

- Expert branches run only for eligible categories.
- Budget or readiness block prevents parallel expert execution.
- Branch timeout returns safe partial metadata.
- Synthesizer does not receive cross-owner evidence.
- Workflow status reflects fallback or needs-review correctly.

## P2: Legacy Agent Boundary Cleanup

### Goal

Reduce ambiguity between legacy specialist agents and the product Study Agent workflow.

### Required Changes

- Document `MainCoordinator` as legacy or batch pipeline unless it is actively used by the product API.
- Fix `BaseAgent.invoke()` so an `AgentResult(success=False)` does not mark the agent as completed.
- Add structured error codes to `AgentResult`.
- Add optional safe trace metadata to legacy agent results if they remain in use.
- Avoid exposing legacy coordinator checkpoints through product APIs without privacy filtering.

### Tests

Required tests:

- Failed `AgentResult` sets agent status to failed.
- Retry count behavior remains compatible.
- Coordinator stage failure returns safe stage data.
- Legacy coordinator output does not include raw private content in product-facing paths.

## P3: Memory-Guided Evaluation And Skill Tuning

### Goal

Use memory and evaluation data to tune route policy and skill defaults without automatic prompt mutation.

Allowed in this slice:

- aggregate skill pass rate
- aggregate needs-review rate
- fallback rate by skill and category
- recall metrics by skill version
- manual promotion or demotion of skill versions

Not allowed in this slice:

- automatic prompt evolution
- DSPy/GEPA mutation
- hidden self-improvement loops
- model-generated skill changes without human review

## API Boundary

New or extended APIs should remain narrow:

- `GET /api/study-agent/skills`
- `GET /api/study-agent/skills/{skill_name}/versions`
- `GET /api/study-agent/memories/summary`
- `DELETE /api/study-agent/memories/{memory_id}`

Memory write APIs should not be broad user-facing endpoints in the first implementation. Most writes should come from controlled product events such as review decisions, explicit preference changes, and completed study sessions.

## Frontend Boundary

Frontend should stay compact:

- show selected skill and version near Study Agent diagnostics;
- show review task status when created;
- show memory-informed labels only when useful, such as "difficulty preference applied";
- provide a small settings path to clear or disable memory categories.

Avoid:

- a large agent dashboard;
- raw memory inspection by default;
- prompt or hidden reasoning display;
- showing private raw query history as memory.

## Privacy And Security

All new agent collaboration, skill, and memory paths must enforce:

- authenticated owner context;
- owner isolation;
- safe metadata allowlists;
- audit metadata sanitization;
- no raw model hidden reasoning;
- no credential-like fields;
- no cross-owner recall;
- deterministic tests for sanitizer behavior.

Memory deletion must be supported per memory record and preferably per category.

## Observability

Workflow and trace metadata may add safe fields:

- `skill_name`
- `skill_version`
- `memory_categories_used`
- `memory_record_count`
- `review_task_id`
- `expert_branch_count`
- `expert_timeout_count`

These fields must contain labels and counts only.

## Acceptance Criteria

- Review Gate can create an owner-scoped review task without leaking raw content.
- Review task creation is idempotent per owner and workflow.
- Review decisions can write safe `review_outcome` memory.
- Memory recall is owner-scoped, deterministic, and privacy-safe.
- Skill registry can select and validate initial study skills.
- Skill metadata appears in trace/workflow payloads as safe labels only.
- Advanced expert collaboration remains disabled unless route policy, readiness, index health, and budget allow it.
- Legacy agent status handling does not mark failed results as completed.
- Backend tests cover owner isolation, privacy filtering, review task creation, memory recall, skill selection, and fallback behavior.
- Frontend build passes when UI diagnostics are touched.

## Non-Goals

- No open-ended autonomous agent loop.
- No unrestricted memory of raw conversations.
- No prompt mutation or automatic self-evolution.
- No new graph database.
- No large agent analytics dashboard.
- No cross-user or admin memory search in this slice.
- No provider-specific LLM optimization.

## Implementation Slices

### Slice 1: Review Task Loop

- Link Review Gate outcomes to persisted review tasks.
- Add idempotency and audit metadata tests.
- Add compact frontend review task status.

### Slice 2: Product Memory Foundation

- Add owner-scoped memory data model and service.
- Add safe category schemas.
- Integrate review decisions and explicit preferences.

### Slice 3: Skill Registry

- Add versioned skill contracts.
- Add skill selection stage and safe trace metadata.
- Add initial skills and tests.

### Slice 4: Legacy Agent Cleanup

- Fix legacy status semantics.
- Document legacy boundary.
- Add safe result tests.

### Slice 5: Bounded Expert Collaboration

- Add optional expert branch execution for eligible categories.
- Keep defaults disabled behind policy and readiness gates.
- Add timeout, fallback, and privacy tests.

## Development Governance

Implementation must follow the existing project rule:

```text
Spec -> Plan -> Subagent Implementation -> Spec Review -> Quality Review -> Verification -> Merge
```

Every implementation task must include:

- spec compliance review;
- quality and privacy review;
- tests sized to risk;
- final backend verification;
- frontend build if UI/types are touched;
- clean worktree before merge or push.
