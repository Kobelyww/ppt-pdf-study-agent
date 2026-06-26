# RAG Route Policy And Advanced Retrieval Experimentation Design

## Purpose

P0/P1 made Study Agent retrieval observable: queries now create safe traces, index health is visible, deterministic RAG evaluations can compare retrieval modes, and readiness gates can recommend whether Graph RAG Lite or Agentic RAG are promising.

P2 turns those recommendations into a controlled routing policy. The product should be able to decide whether a query may use simple RAG, Graph RAG Lite, or Agentic RAG based on feature flags, evaluation readiness, index health, query class, budget, and fallback safety. This phase should make advanced retrieval experimentable without letting high-cost or low-confidence paths silently take over production traffic.

The central product question is:

> Can the system automatically choose a retrieval mode in a way that is explainable, reversible, privacy-safe, and measurably better than simple RAG for the query category?

## Roadmap Alignment

This phase follows `2026-06-26-rag-quality-observability-design.md`.

P0/P1 intentionally did not change production routing thresholds. P2 is the next slice because the product now has the observability needed to evaluate routing decisions before promoting advanced modes. This is still not a full vector database or graph platform migration. It is a policy and experiment layer around the existing deterministic Study Agent pipeline.

## Goals

- Add an explicit route policy service that decides which retrieval mode is allowed for a query.
- Convert readiness reports into configurable route gates for Graph RAG Lite and Agentic RAG.
- Add feature flags that can disable advanced routing globally, per mode, or per category.
- Improve query classification enough to distinguish direct lookup, concept relation, learning path, synthesis, question generation, and outline-fragment requests.
- Strengthen Graph RAG Lite evidence expansion for concept relation and learning-path categories.
- Strengthen Agentic RAG planning controls for synthesis and question-generation categories.
- Record policy decisions in safe trace metadata so operators can explain why a mode was selected or blocked.
- Extend deterministic evaluation fixtures to validate routing decisions, fallback behavior, latency/cost budgets, and category-specific readiness.
- Keep simple RAG as the production baseline and fallback.

## Non-Goals

- Do not add a real embedding provider in P2.
- Do not switch the primary retrieval store to pgvector or a managed vector database.
- Do not build a full knowledge-graph database or graph UI.
- Do not add self-evolution, DSPy/GEPA optimization, or automatic prompt mutation.
- Do not make Agentic RAG the default for all queries.
- Do not allow Graph RAG Lite or Agentic RAG to bypass readiness gates.
- Do not store raw private query text, generated answers, chunk content, source snippets, tokens, passwords, or secrets in policy, trace, audit, or admin metadata.
- Do not build a large analytics dashboard.

## Current State

The codebase already has the required base pieces:

- `RAGStrategyRouter` classifies a query using deterministic rules and returns `simple_rag`, `graph_rag_lite`, or `agentic_rag`.
- `StudyAgentRuntimeService` loads owner-scoped document evidence, prefers persisted chunks, records index status, and falls back to query-time chunking when persisted chunks are missing, stale, or incomplete.
- `StudyAgentOrchestrator` can route, gather evidence, generate drafts, and verify results.
- `StudyAgentTraceService` persists safe trace summaries without raw private content.
- `RAGQualityEvaluationService` compares modes with deterministic fixtures and emits readiness recommendations.
- Admin evaluation APIs can create and read evaluation runs.
- The frontend shows compact diagnostics for selected mode, fallback, confidence, recall, and review status.

The remaining gap is enforcement and experiment control. Readiness exists as a report, but production routing does not yet ask whether a mode is enabled, ready for the category, affordable for the budget, or safe for the current index health.

## P2 Scope

### Route Policy Service

Add a service boundary for controlled retrieval routing.

Recommended service: `RAGRoutePolicyService`.

Responsibilities:

- Accept the router decision, normalized request, index health summary, latest readiness snapshot, feature flags, budget, and optional user preference.
- Decide the final retrieval mode that may run.
- Decide whether the router-selected mode is:
  - `allowed`
  - `blocked_by_flag`
  - `blocked_by_readiness`
  - `blocked_by_budget`
  - `blocked_by_index_health`
  - `blocked_by_category`
  - `forced_by_user_preference`
  - `fallback_to_simple`
- Produce an ordered fallback chain.
- Produce a safe, human-readable route reason.
- Return a compact decision object that can be persisted in trace metadata and returned in API diagnostics.

Recommended contract:

```python
@dataclass(frozen=True)
class RAGRoutePolicyDecision:
    selected_mode: RetrievalMode
    router_mode: RetrievalMode
    category: str
    status: str
    reason: str
    fallback_chain: list[RetrievalMode]
    readiness_status: str | None
    blocked_reason: str | None
    estimated_cost: str
    experiment_enabled: bool
    policy_version: str
```

The decision must not include raw query text or generated content.

### Policy Configuration

Add a small typed policy configuration object. It should be easy to test without environment variables, but app startup may populate it from settings.

Recommended fields:

- `policy_version`: string, for trace/debug stability.
- `advanced_routing_enabled`: global kill switch.
- `graph_rag_enabled`: mode-level flag.
- `agentic_rag_enabled`: mode-level flag.
- `enabled_categories`: optional set of categories allowed for advanced modes.
- `graph_candidate_required`: default `True`.
- `agentic_candidate_required`: default `True`.
- `allow_user_preferred_mode`: default `False` for production safety.
- `max_budget_for_agentic`: default `high`.
- `require_persisted_chunks_for_advanced`: default `True`.
- `fallback_to_simple_on_block`: default `True`.

Recommended defaults should be conservative:

- simple RAG always allowed.
- Graph RAG Lite disabled unless both feature flag and readiness allow it.
- Agentic RAG disabled unless both feature flag and readiness allow it.
- user `preferred_mode` cannot override disabled or not-ready advanced modes unless an explicit test/admin configuration allows it.

### Query Classification

Expand deterministic query classification from mode-only routing to category-aware routing.

Required categories:

- `direct_lookup`
- `definition`
- `concept_relation`
- `learning_path`
- `multi_document_synthesis`
- `question_generation`
- `outline_fragment`
- `unknown`

The category may be derived from deterministic query rules plus request target. It should be stored as a safe label in trace metadata and evaluation outputs.

Examples:

- "什么是导数" -> `definition`
- "学习积分前需要掌握什么" -> `learning_path`
- "A 和 B 有什么关系" -> `concept_relation`
- "综合第 2 章和第 4 章出一道题" -> `question_generation`
- target `outline_fragment` -> `outline_fragment`

The classifier must not require network access or an LLM provider.

### Readiness Snapshot

P2 needs route policy decisions to use readiness without requiring a fresh evaluation run per query.

Add a read model that can provide the latest safe readiness snapshot:

- from the most recent completed evaluation run;
- from a configured static default for tests;
- or from an injected snapshot in service tests.

Recommended shape:

```json
{
  "policy_version": "rag-policy-v1",
  "fixture_version": "rag_eval_set.json",
  "created_at": "2026-06-26T00:00:00Z",
  "modes": {
    "simple_rag": {
      "overall": "baseline",
      "by_category": {}
    },
    "graph_rag_lite": {
      "overall": "candidate",
      "by_category": {
        "concept_relation": "candidate",
        "learning_path": "candidate"
      }
    },
    "agentic_rag": {
      "overall": "hold",
      "by_category": {
        "question_generation": "hold"
      }
    }
  }
}
```

If no snapshot is available, simple RAG remains allowed and advanced modes are blocked with `blocked_by_readiness`.

### Graph RAG Lite Experiment

Improve Graph RAG Lite only within the current deterministic product boundaries.

Required behavior:

- Use concept or keyword seeds from available document evidence.
- Expand one or two hops through existing `KnowledgeGraph` relationships when available.
- Recover chunks linked to seed or neighbor concepts.
- Blend graph-expanded evidence with direct chunk retrieval.
- Record safe graph metadata:
  - seed concept count
  - expanded concept count
  - graph hop count
  - graph fallback reason
- Fall back to simple RAG when no seeds, no graph, or no linked chunks are available.

Do not introduce a new graph database in P2. The experiment should use existing in-memory or service-level graph structures.

### Agentic RAG Experiment

Improve Agentic RAG as a bounded planner, not an open-ended autonomous agent.

Required behavior:

- Only eligible by default for `multi_document_synthesis`, `question_generation`, and optionally `outline_fragment`.
- Enforce `max_steps`.
- Enforce budget labels and a deterministic estimated cost.
- Gather evidence through direct retrieval and optional Graph RAG Lite expansion.
- Stop when enough cited evidence is collected.
- Fall back to Graph RAG Lite or simple RAG when:
  - planner has no useful steps;
  - evidence confidence is too low;
  - step budget is exceeded;
  - index health is not suitable;
  - readiness gate blocks the mode.

Recommended safe planning metadata:

- `planned_step_count`
- `executed_step_count`
- `step_budget_exhausted`
- `fallback_reason`
- `evidence_confidence`

Do not persist chain-of-thought, hidden reasoning, raw prompts, or raw model outputs.

### Runtime Integration

Integrate the policy service before evidence collection.

Flow:

1. Normalize the Study Agent request.
2. Run deterministic query classifier/router.
3. Load index health for requested documents.
4. Load latest readiness snapshot.
5. Apply `RAGRoutePolicyService`.
6. Execute only the policy-selected mode.
7. Apply fallback chain if selected evidence path fails.
8. Persist trace with policy decision labels and fallback outcome.
9. Return compact diagnostics in `/api/study-agent/query`.

Existing clients must remain compatible. New fields are additive.

### API Additions

P2 should keep APIs narrow.

Recommended admin/operator APIs:

```http
GET /api/admin/rag-route-policy
GET /api/admin/rag-route-readiness
POST /api/admin/rag-route-policy/simulate
```

Rules:

- Admin-only.
- Responses contain safe labels, flags, readiness statuses, counts, and reasons only.
- Simulation accepts public test inputs or a query string but must not persist raw simulation query text in audit metadata.
- Simulation may return the computed category, router mode, selected mode, status, and fallback chain.

Normal user query responses may include an additive `policy` diagnostic:

```json
{
  "policy": {
    "policy_version": "rag-policy-v1",
    "router_mode": "agentic_rag",
    "selected_mode": "simple_rag",
    "category": "question_generation",
    "status": "blocked_by_readiness",
    "readiness_status": "hold",
    "blocked_reason": "agentic_rag is not candidate for question_generation",
    "experiment_enabled": false
  }
}
```

### Trace And Audit Metadata

Extend safe trace metadata with policy fields:

- `policy_version`
- `category`
- `router_mode`
- `selected_mode`
- `policy_status`
- `readiness_status`
- `blocked_reason`
- `experiment_enabled`
- `fallback_chain`
- `final_fallback_reason`
- `graph_seed_count`
- `graph_expanded_count`
- `agentic_planned_step_count`
- `agentic_executed_step_count`

Allowed audit metadata:

- `trace_id`
- `policy_version`
- `category`
- `router_mode`
- `selected_mode`
- `policy_status`
- `needs_review`
- `fallback_reason`
- `latency_ms`

Forbidden metadata remains:

- raw query text
- generated answer text
- raw chunk content
- source snippets
- prompts or hidden reasoning
- uploaded file content
- authorization headers
- tokens, passwords, secrets, API keys

### Frontend Diagnostics

Keep frontend changes compact.

Add to the existing Study Agent panel:

- policy status label;
- final selected mode;
- blocked reason when an advanced mode was blocked;
- experiment flag indicator for Graph/Agentic paths;
- fallback message when policy or runtime falls back to simple RAG.

Do not add a standalone route analytics dashboard in P2.

### Evaluation Fixture Expansion

Expand deterministic fixtures so route policy can be tested without private data.

Additional fixture fields:

- `expected_category`
- `expected_router_mode`
- `expected_selected_mode_when_ready`
- `expected_selected_mode_when_not_ready`
- `requires_persisted_chunks`
- `max_allowed_cost`
- `policy_notes`

Each category should have at least one public deterministic case. `question_generation` and `multi_document_synthesis` should have at least two cases because Agentic RAG readiness is more sensitive to false positives.

Fixtures must remain public and committed. They must not contain uploaded user document text or private source snippets.

### Evaluation And CI

Add deterministic tests that compare policy behavior under multiple readiness snapshots:

- no readiness snapshot;
- Graph candidate and Agentic hold;
- Graph hold and Agentic candidate;
- all advanced modes disabled;
- user preferred advanced mode allowed only in explicit test/admin config.

The route policy evaluation should report:

- route accuracy by category;
- blocked advanced route count;
- fallback-to-simple count;
- policy status counts;
- category readiness coverage;
- estimated cost coverage;
- needs-review rate by selected mode.

## Data Flow

### Query Policy Flow

1. User calls `/api/study-agent/query`.
2. Runtime validates authenticated owner and requested documents.
3. Runtime collects index health for requested documents.
4. Router/classifier proposes a mode and category.
5. Readiness provider loads the latest snapshot.
6. Policy service checks feature flags, readiness, index health, budget, and preferred mode.
7. Runtime executes the selected mode.
8. Evidence failure applies fallback chain and records final fallback reason.
9. Generator and verifier produce the result.
10. Trace service persists safe policy and retrieval metadata.
11. API returns existing Study Agent payload plus compact trace/policy diagnostics.

### Admin Simulation Flow

1. Admin calls `/api/admin/rag-route-policy/simulate`.
2. API validates admin context.
3. Service runs classifier, readiness lookup, and policy decision.
4. API returns safe decision labels.
5. Audit records simulation action without raw query text.

## Rollout Strategy

1. Add policy config and decision data contracts.
2. Add category-aware classifier while keeping existing router behavior compatible.
3. Add readiness snapshot provider.
4. Add route policy service with feature flag and readiness gates.
5. Integrate policy into Study Agent runtime behind conservative defaults.
6. Strengthen Graph RAG Lite evidence expansion for relation/path categories.
7. Strengthen Agentic RAG planner controls for synthesis/question categories.
8. Add admin policy/readiness/simulation APIs.
9. Add compact frontend policy diagnostics.
10. Expand evaluation fixtures and reports for policy behavior.

The rollout should keep simple RAG as fallback at every step.

## Acceptance Criteria

### P2 Acceptance Criteria

- Route policy decisions are produced by a dedicated service with deterministic tests.
- Advanced routing can be disabled globally and per mode.
- Graph RAG Lite and Agentic RAG require readiness candidate status before automatic selection.
- If no readiness snapshot exists, simple RAG is selected and advanced modes are blocked safely.
- Query category is recorded as a safe label in traces and diagnostics.
- Budget and index-health gates can block Agentic or Graph routing.
- User `preferred_mode` cannot force disabled or not-ready advanced modes under default production policy.
- Graph RAG Lite falls back to simple RAG when seed concepts or graph-linked chunks are unavailable.
- Agentic RAG enforces step and budget controls and falls back when evidence is insufficient.
- Admin policy/readiness/simulation APIs are admin-only and return no raw private content.
- Frontend diagnostics show policy status and fallback reason without adding a dashboard.
- Evaluation fixtures cover every required category and policy gate.
- Trace and audit metadata still exclude raw query, answer, chunk content, snippets, prompts, hidden reasoning, tokens, passwords, and secrets.
- Existing Study Agent API response remains backward compatible.

## Test Plan

Required backend tests:

- `tests/test_rag_route_policy.py`
  - simple RAG remains allowed when advanced routing is disabled.
  - Graph RAG Lite is selected only when flag and readiness allow the category.
  - Agentic RAG is selected only when flag, readiness, category, and budget allow it.
  - no readiness snapshot blocks advanced modes.
  - user preferred mode cannot override production policy by default.
  - fallback chain is stable and safe.

- `tests/test_rag_router.py`
  - category classifier detects definition, direct lookup, concept relation, learning path, synthesis, question generation, outline fragment, and unknown.
  - existing mode selection remains compatible for current tests.

- `tests/test_study_agent_runtime.py`
  - runtime applies policy-selected mode.
  - runtime records policy decision in safe audit metadata.
  - index health can block advanced modes.
  - fallback to simple RAG is recorded when Graph/Agentic evidence is unavailable.

- `tests/test_graph_rag.py`
  - graph expansion uses seed concepts and neighbors.
  - no seeds falls back to simple RAG.
  - graph metadata includes counts only, not snippets.

- `tests/test_agentic_rag.py`
  - planner respects max steps and budget.
  - insufficient evidence triggers fallback.
  - planning metadata excludes hidden reasoning and raw prompts.

- `tests/test_study_agent_api.py`
  - `/api/study-agent/query` returns additive policy diagnostics.
  - response remains backward compatible.
  - audit metadata remains sanitized.

- `tests/test_api_permissions_audit.py`
  - admin policy APIs require admin.
  - simulation audit metadata excludes raw query text.

- `tests/test_rag_evaluation.py` and `tests/test_rag_mode_comparison.py`
  - fixtures validate policy fields.
  - reports summarize policy status counts and category readiness coverage.

Frontend verification:

- `cd frontend && npm run build`

Recommended final verification:

```bash
pytest tests/test_rag_route_policy.py tests/test_rag_router.py tests/test_study_agent_runtime.py tests/test_graph_rag.py tests/test_agentic_rag.py tests/test_study_agent_api.py tests/test_api_permissions_audit.py tests/test_rag_evaluation.py tests/test_rag_mode_comparison.py -q
cd frontend && npm run build
```

## Review Requirements

After each implementation task, run the project-required two reviews before moving forward:

- **Spec review:** confirm the task implements this P2 spec without skipping policy gates, readiness checks, privacy constraints, or fallback behavior, and without adding out-of-scope embeddings, pgvector migration, graph database work, self-evolution, or a dashboard.
- **Quality review:** inspect service boundaries, deterministic behavior, policy default safety, owner isolation, admin-only APIs, trace/audit sanitization, test coverage, and backward compatibility.

## Next Plan

The implementation plan following this spec should be:

`docs/superpowers/plans/2026-06-26-rag-route-policy-advanced-retrieval.md`

The plan should use subagent-driven development. Policy contracts, runtime integration, Graph RAG changes, Agentic RAG controls, API updates, frontend diagnostics, and evaluation expansion should be serialized enough to avoid conflicting edits in shared service files.
