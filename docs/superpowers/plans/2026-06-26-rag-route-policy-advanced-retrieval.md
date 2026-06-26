# RAG Route Policy And Advanced Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the P2 controlled RAG routing policy so Study Agent can safely choose simple RAG, Graph RAG Lite, or Agentic RAG using feature flags, readiness gates, index health, category classification, budget, and fallback rules.

**Architecture:** Keep simple RAG as the baseline and add a policy layer before evidence collection. Split responsibilities into category-aware routing, readiness snapshot lookup, policy decisions, runtime integration, bounded Graph/Agentic retrieval improvements, narrow admin APIs, compact frontend diagnostics, and deterministic policy evaluation.

**Tech Stack:** FastAPI, SQLAlchemy ORM, pytest, deterministic in-process Study Agent services, Vite/React/TypeScript frontend, existing `StorageBackend`, existing RAG evaluation fixtures and reports.

---

## Scope And Product Boundaries

This plan implements:

- `docs/superpowers/specs/2026-06-26-rag-route-policy-advanced-retrieval-design.md`

It includes:

- Category-aware deterministic routing.
- `RAGRoutePolicyService`, policy config, policy decision contract, and readiness snapshot provider.
- Conservative runtime integration where simple RAG remains the fallback.
- Graph RAG Lite metadata and fallback strengthening.
- Agentic RAG step and budget controls.
- Admin-only policy/readiness/simulation APIs.
- Compact frontend policy diagnostics.
- Expanded evaluation fixtures and policy metrics.

It excludes:

- Real embedding providers.
- pgvector or managed vector DB migration.
- A new graph database or graph dashboard.
- Self-evolution, DSPy/GEPA optimization, or prompt mutation.
- Large analytics dashboard.
- Persisting raw private query text, generated answers, chunk content, source snippets, prompts, hidden reasoning, tokens, passwords, or secrets.

## File Structure

- Modify `src/services/rag_router.py`: add `QueryCategory`, category classification, and category on `RetrievalDecision`.
- Create `src/services/rag_route_policy.py`: policy config, readiness snapshot provider, decision object, and route policy service.
- Modify `src/services/study_agent.py`: accept optional policy decision, plan with policy-selected mode, pass bounded metadata through evidence collection.
- Modify `src/services/study_agent_runtime.py`: load readiness snapshot, apply policy before orchestration, pass policy diagnostics into audit metadata.
- Modify `src/services/study_agent_trace.py`: serialize safe policy fields in trace payloads.
- Modify `src/services/graph_rag.py`: add graph seed/expanded/hop metadata and clearer fallback reasons.
- Modify `src/services/agentic_rag.py`: add bounded planning options and safe planning metadata.
- Modify `src/services/rag_evaluation.py`: validate policy fixture fields and summarize policy status/category readiness coverage.
- Modify `src/api/routes/admin.py`: add policy config, readiness, and simulation routes.
- Modify `src/api/routes/study_agent.py`: return additive `policy` diagnostics.
- Modify `frontend/src/api.ts`: add `StudyAgentPolicyDiagnostic` type.
- Modify `frontend/src/components/StudyAgentPanel.tsx`: show compact policy status/fallback diagnostics.
- Modify `frontend/src/styles.css`: add small policy diagnostic styles.
- Modify `tests/fixtures/rag_eval_set.json`: add deterministic policy fields and category coverage.
- Create `tests/test_rag_route_policy.py`: policy service coverage.
- Modify `tests/test_rag_router.py`: category classification coverage.
- Modify `tests/test_study_agent_runtime.py`: policy runtime integration coverage.
- Modify `tests/test_study_agent_traces.py`: trace policy serialization coverage.
- Modify `tests/test_graph_rag.py`: metadata/fallback coverage.
- Modify `tests/test_agentic_rag.py`: bounded planner coverage.
- Modify `tests/test_study_agent_api.py`: policy diagnostics coverage.
- Modify `tests/test_api_permissions_audit.py`: admin API and audit privacy coverage.
- Modify `tests/test_rag_evaluation.py`: fixture validation and policy metric coverage.
- Modify `tests/test_rag_mode_comparison.py`: readiness/policy report coverage.
- Modify `README.md` and `SPEC.md`: document P2 routing policy status.

## Shared Review Rule

After each task, run both reviews before moving to the next task:

- **Spec review:** compare the task diff against `docs/superpowers/specs/2026-06-26-rag-route-policy-advanced-retrieval-design.md`. Confirm the task implements the intended slice and does not add out-of-scope embeddings, pgvector migration, graph database work, self-evolution, prompt mutation, or dashboard work.
- **Quality review:** inspect service boundaries, deterministic behavior, conservative defaults, owner isolation, admin-only access, trace/audit sanitization, fallback behavior, and backward compatibility.

Record both review outcomes in the task completion note.

## Task 1: Category-Aware Router Contract

**Files:**
- Modify: `src/services/rag_router.py`
- Modify: `tests/test_rag_router.py`

- [ ] **Step 1: Write failing router category tests**

Append these tests to `tests/test_rag_router.py`:

```python
from src.services.rag_router import QueryCategory


def test_classifies_definition_query():
    decision = RAGStrategyRouter().route("什么是导数？")

    assert decision.mode == RetrievalMode.SIMPLE
    assert decision.category == QueryCategory.DEFINITION


def test_classifies_learning_path_query():
    decision = RAGStrategyRouter().route("学习积分前需要掌握什么？")

    assert decision.mode == RetrievalMode.GRAPH
    assert decision.category == QueryCategory.LEARNING_PATH


def test_classifies_concept_relation_query():
    decision = RAGStrategyRouter().route("特征值和矩阵分解有什么关系？")

    assert decision.mode == RetrievalMode.GRAPH
    assert decision.category == QueryCategory.CONCEPT_RELATION


def test_classifies_question_generation_query():
    decision = RAGStrategyRouter().route("综合第2章和第4章出一道题")

    assert decision.mode == RetrievalMode.AGENTIC
    assert decision.category == QueryCategory.QUESTION_GENERATION


def test_classifies_outline_fragment_from_target():
    decision = RAGStrategyRouter().route(
        "整理这一章的重点",
        target="outline_fragment",
    )

    assert decision.category == QueryCategory.OUTLINE_FRAGMENT


def test_classifies_unknown_empty_after_normalization_as_direct_lookup_default():
    decision = RAGStrategyRouter().route("特征值")

    assert decision.mode == RetrievalMode.SIMPLE
    assert decision.category in {QueryCategory.DIRECT_LOOKUP, QueryCategory.UNKNOWN}
```

- [ ] **Step 2: Run router tests and confirm failure**

Run:

```bash
pytest tests/test_rag_router.py -q
```

Expected: FAIL because `QueryCategory`, `RetrievalDecision.category`, and `route(..., target=...)` do not exist.

- [ ] **Step 3: Implement category-aware router**

Modify `src/services/rag_router.py`:

```python
class QueryCategory(str, Enum):
    DIRECT_LOOKUP = "direct_lookup"
    DEFINITION = "definition"
    CONCEPT_RELATION = "concept_relation"
    LEARNING_PATH = "learning_path"
    MULTI_DOCUMENT_SYNTHESIS = "multi_document_synthesis"
    QUESTION_GENERATION = "question_generation"
    OUTLINE_FRAGMENT = "outline_fragment"
    UNKNOWN = "unknown"
```

Update `RetrievalDecision`:

```python
@dataclass(frozen=True)
class RetrievalDecision:
    mode: RetrievalMode
    reason: str
    confidence: float
    estimated_cost: str
    category: QueryCategory = QueryCategory.DIRECT_LOOKUP
```

Update `RAGStrategyRouter.route` to accept target and classify category:

```python
def route(self, query: str, target: str | None = None) -> RetrievalDecision:
    normalized = query.strip().lower()
    category = self.classify(query, target=target)
    chapter_mentions = set(re.findall(r"第\s*\d+\s*章", normalized))

    if category in {
        QueryCategory.QUESTION_GENERATION,
        QueryCategory.MULTI_DOCUMENT_SYNTHESIS,
    }:
        return RetrievalDecision(
            mode=RetrievalMode.AGENTIC,
            reason="query requires multi-step synthesis or question generation",
            confidence=0.8,
            estimated_cost="high",
            category=category,
        )

    if category in {QueryCategory.CONCEPT_RELATION, QueryCategory.LEARNING_PATH}:
        return RetrievalDecision(
            mode=RetrievalMode.GRAPH,
            reason="query asks for concept relation or learning path",
            confidence=0.75,
            estimated_cost="medium",
            category=category,
        )

    if len(chapter_mentions) >= 2:
        return RetrievalDecision(
            mode=RetrievalMode.AGENTIC,
            reason="query spans multiple chapters",
            confidence=0.78,
            estimated_cost="high",
            category=QueryCategory.MULTI_DOCUMENT_SYNTHESIS,
        )

    return RetrievalDecision(
        mode=RetrievalMode.SIMPLE,
        reason="definition or direct lookup query",
        confidence=0.7,
        estimated_cost="low",
        category=category,
    )
```

Add classifier helper:

```python
def classify(self, query: str, target: str | None = None) -> QueryCategory:
    normalized = query.strip().lower()
    if target == "outline_fragment":
        return QueryCategory.OUTLINE_FRAGMENT
    if not normalized:
        return QueryCategory.UNKNOWN
    if any(keyword in normalized for keyword in ["出一道", "出题", "生成题", "生成一道", "练习题", "综合题"]):
        return QueryCategory.QUESTION_GENERATION
    if re.search(r"生成[^。？！?]*题", normalized) is not None:
        return QueryCategory.QUESTION_GENERATION
    if "跨章节" in normalized or len(set(re.findall(r"第\s*\d+\s*章", normalized))) >= 2:
        return QueryCategory.MULTI_DOCUMENT_SYNTHESIS
    if any(keyword in normalized for keyword in ["前置", "先学", "路径", "需要掌握", "掌握什么", "学习前"]):
        return QueryCategory.LEARNING_PATH
    if any(keyword in normalized for keyword in ["关系", "关联", "影响", "区别", "联系"]):
        return QueryCategory.CONCEPT_RELATION
    if any(keyword in normalized for keyword in ["什么是", "是什么", "定义", "解释"]):
        return QueryCategory.DEFINITION
    if normalized:
        return QueryCategory.DIRECT_LOOKUP
    return QueryCategory.UNKNOWN
```

- [ ] **Step 4: Run router tests**

Run:

```bash
pytest tests/test_rag_router.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit router contract**

Run:

```bash
git add src/services/rag_router.py tests/test_rag_router.py
git commit -m "feat: classify study agent query categories"
```

- [ ] **Step 6: Run required reviews**

Run the project-required Spec review and Quality review for Task 1 before continuing.

## Task 2: Route Policy Service And Readiness Snapshot

**Files:**
- Create: `src/services/rag_route_policy.py`
- Create: `tests/test_rag_route_policy.py`

- [ ] **Step 1: Write failing policy service tests**

Create `tests/test_rag_route_policy.py`:

```python
from src.services.rag_route_policy import (
    RAGReadinessSnapshot,
    RAGRoutePolicyConfig,
    RAGRoutePolicyService,
)
from src.services.rag_router import QueryCategory, RetrievalDecision, RetrievalMode


def _decision(mode, category):
    return RetrievalDecision(
        mode=mode,
        reason="router reason",
        confidence=0.8,
        estimated_cost="high" if mode == RetrievalMode.AGENTIC else "medium",
        category=category,
    )


def _snapshot(graph_status="candidate", agentic_status="hold"):
    return RAGReadinessSnapshot(
        policy_version="rag-policy-v1",
        fixture_version="rag_eval_set.json",
        modes={
            "simple_rag": {"overall": "baseline", "by_category": {}},
            "graph_rag_lite": {
                "overall": graph_status,
                "by_category": {"learning_path": graph_status},
            },
            "agentic_rag": {
                "overall": agentic_status,
                "by_category": {"question_generation": agentic_status},
            },
        },
    )


def test_simple_rag_allowed_when_advanced_routing_disabled():
    service = RAGRoutePolicyService(
        RAGRoutePolicyConfig(advanced_routing_enabled=False)
    )

    decision = service.decide(
        router_decision=_decision(RetrievalMode.GRAPH, QueryCategory.LEARNING_PATH),
        readiness=_snapshot(),
        index_statuses={"doc-1": {"status": "indexed"}},
        budget="balanced",
    )

    assert decision.selected_mode == RetrievalMode.SIMPLE
    assert decision.status == "blocked_by_flag"
    assert decision.blocked_reason == "advanced routing is disabled"


def test_graph_selected_only_when_flag_and_readiness_allow_category():
    service = RAGRoutePolicyService(
        RAGRoutePolicyConfig(
            advanced_routing_enabled=True,
            graph_rag_enabled=True,
        )
    )

    decision = service.decide(
        router_decision=_decision(RetrievalMode.GRAPH, QueryCategory.LEARNING_PATH),
        readiness=_snapshot(graph_status="candidate"),
        index_statuses={"doc-1": {"status": "indexed"}},
        budget="balanced",
    )

    assert decision.selected_mode == RetrievalMode.GRAPH
    assert decision.status == "allowed"
    assert decision.readiness_status == "candidate"


def test_agentic_blocked_when_readiness_holds_category():
    service = RAGRoutePolicyService(
        RAGRoutePolicyConfig(
            advanced_routing_enabled=True,
            agentic_rag_enabled=True,
        )
    )

    decision = service.decide(
        router_decision=_decision(
            RetrievalMode.AGENTIC,
            QueryCategory.QUESTION_GENERATION,
        ),
        readiness=_snapshot(agentic_status="hold"),
        index_statuses={"doc-1": {"status": "indexed"}},
        budget="high",
    )

    assert decision.selected_mode == RetrievalMode.SIMPLE
    assert decision.status == "blocked_by_readiness"
    assert decision.blocked_reason == "agentic_rag is not candidate for question_generation"


def test_no_readiness_snapshot_blocks_advanced_modes():
    service = RAGRoutePolicyService(
        RAGRoutePolicyConfig(
            advanced_routing_enabled=True,
            graph_rag_enabled=True,
        )
    )

    decision = service.decide(
        router_decision=_decision(RetrievalMode.GRAPH, QueryCategory.CONCEPT_RELATION),
        readiness=None,
        index_statuses={"doc-1": {"status": "indexed"}},
        budget="balanced",
    )

    assert decision.selected_mode == RetrievalMode.SIMPLE
    assert decision.status == "blocked_by_readiness"


def test_user_preferred_mode_cannot_override_default_policy():
    service = RAGRoutePolicyService(
        RAGRoutePolicyConfig(
            advanced_routing_enabled=True,
            graph_rag_enabled=False,
            allow_user_preferred_mode=False,
        )
    )

    decision = service.decide(
        router_decision=_decision(RetrievalMode.GRAPH, QueryCategory.LEARNING_PATH),
        readiness=_snapshot(),
        index_statuses={"doc-1": {"status": "indexed"}},
        budget="balanced",
        preferred_mode=RetrievalMode.GRAPH,
    )

    assert decision.selected_mode == RetrievalMode.SIMPLE
    assert decision.status == "blocked_by_flag"


def test_index_health_blocks_advanced_when_persisted_chunks_required():
    service = RAGRoutePolicyService(
        RAGRoutePolicyConfig(
            advanced_routing_enabled=True,
            graph_rag_enabled=True,
            require_persisted_chunks_for_advanced=True,
        )
    )

    decision = service.decide(
        router_decision=_decision(RetrievalMode.GRAPH, QueryCategory.LEARNING_PATH),
        readiness=_snapshot(),
        index_statuses={"doc-1": {"status": "missing"}},
        budget="balanced",
    )

    assert decision.selected_mode == RetrievalMode.SIMPLE
    assert decision.status == "blocked_by_index_health"
```

- [ ] **Step 2: Run policy tests and confirm failure**

Run:

```bash
pytest tests/test_rag_route_policy.py -q
```

Expected: FAIL because `src/services/rag_route_policy.py` does not exist.

- [ ] **Step 3: Implement route policy service**

Create `src/services/rag_route_policy.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.services.rag_router import QueryCategory, RetrievalDecision, RetrievalMode


@dataclass(frozen=True)
class RAGRoutePolicyConfig:
    policy_version: str = "rag-policy-v1"
    advanced_routing_enabled: bool = False
    graph_rag_enabled: bool = False
    agentic_rag_enabled: bool = False
    enabled_categories: frozenset[str] | None = None
    graph_candidate_required: bool = True
    agentic_candidate_required: bool = True
    allow_user_preferred_mode: bool = False
    max_budget_for_agentic: str = "high"
    require_persisted_chunks_for_advanced: bool = True
    fallback_to_simple_on_block: bool = True


@dataclass(frozen=True)
class RAGReadinessSnapshot:
    policy_version: str
    fixture_version: str
    modes: dict[str, dict[str, Any]]
    created_at: str | None = None

    def status_for(self, mode: RetrievalMode, category: QueryCategory) -> str | None:
        mode_payload = self.modes.get(mode.value)
        if not mode_payload:
            return None
        by_category = mode_payload.get("by_category") or {}
        return by_category.get(category.value) or mode_payload.get("overall")


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

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "policy_version": self.policy_version,
            "router_mode": self.router_mode.value,
            "selected_mode": self.selected_mode.value,
            "category": self.category,
            "status": self.status,
            "reason": self.reason,
            "fallback_chain": [mode.value for mode in self.fallback_chain],
            "readiness_status": self.readiness_status,
            "blocked_reason": self.blocked_reason,
            "estimated_cost": self.estimated_cost,
            "experiment_enabled": self.experiment_enabled,
        }


class RAGRoutePolicyService:
    def __init__(self, config: RAGRoutePolicyConfig | None = None) -> None:
        self.config = config or RAGRoutePolicyConfig()

    def decide(
        self,
        *,
        router_decision: RetrievalDecision,
        readiness: RAGReadinessSnapshot | None,
        index_statuses: dict[str, dict[str, Any]] | None,
        budget: str,
        preferred_mode: RetrievalMode | None = None,
    ) -> RAGRoutePolicyDecision:
        router_mode = preferred_mode if self.config.allow_user_preferred_mode and preferred_mode else router_decision.mode
        category = router_decision.category
        fallback_chain = self._fallback_chain(router_mode)
        readiness_status = readiness.status_for(router_mode, category) if readiness else None

        if router_mode == RetrievalMode.SIMPLE:
            return self._decision(router_decision, router_mode, "allowed", "simple rag baseline", fallback_chain, readiness_status, None, True)

        block = self._block_reason(
            mode=router_mode,
            category=category,
            readiness_status=readiness_status,
            index_statuses=index_statuses or {},
            budget=budget,
            readiness_available=readiness is not None,
        )
        if block is not None:
            status, reason = block
            return self._decision(router_decision, RetrievalMode.SIMPLE, status, reason, fallback_chain, readiness_status, reason, False)

        return self._decision(router_decision, router_mode, "allowed", router_decision.reason, fallback_chain, readiness_status, None, True)

    def _block_reason(
        self,
        *,
        mode: RetrievalMode,
        category: QueryCategory,
        readiness_status: str | None,
        index_statuses: dict[str, dict[str, Any]],
        budget: str,
        readiness_available: bool,
    ) -> tuple[str, str] | None:
        if not self.config.advanced_routing_enabled:
            return ("blocked_by_flag", "advanced routing is disabled")
        if mode == RetrievalMode.GRAPH and not self.config.graph_rag_enabled:
            return ("blocked_by_flag", "graph_rag_lite is disabled")
        if mode == RetrievalMode.AGENTIC and not self.config.agentic_rag_enabled:
            return ("blocked_by_flag", "agentic_rag is disabled")
        if self.config.enabled_categories is not None and category.value not in self.config.enabled_categories:
            return ("blocked_by_category", f"{category.value} is not enabled for advanced routing")
        if not readiness_available:
            return ("blocked_by_readiness", "no readiness snapshot is available")
        if readiness_status != "candidate":
            return ("blocked_by_readiness", f"{mode.value} is not candidate for {category.value}")
        if mode == RetrievalMode.AGENTIC and budget != self.config.max_budget_for_agentic:
            return ("blocked_by_budget", "agentic_rag requires high budget")
        if self.config.require_persisted_chunks_for_advanced:
            unhealthy = [
                status.get("status")
                for status in index_statuses.values()
                if status.get("status") not in {"indexed"}
            ]
            if unhealthy:
                return ("blocked_by_index_health", "advanced routing requires healthy persisted chunks")
        return None

    def _decision(
        self,
        router_decision: RetrievalDecision,
        selected_mode: RetrievalMode,
        status: str,
        reason: str,
        fallback_chain: list[RetrievalMode],
        readiness_status: str | None,
        blocked_reason: str | None,
        experiment_enabled: bool,
    ) -> RAGRoutePolicyDecision:
        return RAGRoutePolicyDecision(
            selected_mode=selected_mode,
            router_mode=router_decision.mode,
            category=router_decision.category.value,
            status=status,
            reason=reason,
            fallback_chain=fallback_chain,
            readiness_status=readiness_status,
            blocked_reason=blocked_reason,
            estimated_cost=router_decision.estimated_cost if selected_mode != RetrievalMode.SIMPLE else "low",
            experiment_enabled=experiment_enabled,
            policy_version=self.config.policy_version,
        )

    def _fallback_chain(self, mode: RetrievalMode) -> list[RetrievalMode]:
        if mode == RetrievalMode.AGENTIC:
            return [RetrievalMode.GRAPH, RetrievalMode.SIMPLE]
        if mode == RetrievalMode.GRAPH:
            return [RetrievalMode.SIMPLE]
        return []
```

- [ ] **Step 4: Run policy tests**

Run:

```bash
pytest tests/test_rag_route_policy.py tests/test_rag_router.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit policy service**

Run:

```bash
git add src/services/rag_route_policy.py tests/test_rag_route_policy.py
git commit -m "feat: add rag route policy service"
```

- [ ] **Step 6: Run required reviews**

Run Spec review and Quality review for Task 2 before continuing.

## Task 3: Runtime Policy Integration And Trace Diagnostics

**Files:**
- Modify: `src/services/study_agent.py`
- Modify: `src/services/study_agent_runtime.py`
- Modify: `src/services/study_agent_trace.py`
- Modify: `src/api/routes/study_agent.py`
- Modify: `tests/test_study_agent_runtime.py`
- Modify: `tests/test_study_agent_traces.py`
- Modify: `tests/test_study_agent_api.py`

- [ ] **Step 1: Write failing runtime/API tests**

Add assertions to `tests/test_study_agent_runtime.py` that inject a policy service with advanced routing disabled and verify a graph-classified request runs simple RAG and records policy metadata:

```python
from src.services.rag_route_policy import RAGRoutePolicyConfig, RAGRoutePolicyService


@pytest.mark.asyncio
async def test_runtime_applies_route_policy_and_records_safe_metadata():
    Session = _session_factory()
    _insert_ready_document_with_artifact(
        Session,
        document_id="doc-study",
        content="Eigenvalues describe matrix scaling.",
    )
    _insert_persisted_chunk(
        Session,
        document_id="doc-study",
        content="Eigenvalues describe matrix scaling.",
    )
    runtime = StudyAgentRuntimeService(
        session_factory=Session,
        route_policy=RAGRoutePolicyService(
            RAGRoutePolicyConfig(advanced_routing_enabled=False)
        ),
        readiness_provider=lambda: None,
    )

    result = await runtime.run(
        {
            "query": "学习特征值前需要掌握什么？",
            "document_ids": ["doc-study"],
            "authenticated_user_id": "user-1",
        }
    )

    assert result.plan.mode == RetrievalMode.SIMPLE
    policy = result.audit_metadata["policy"]
    assert policy["status"] == "blocked_by_flag"
    assert policy["router_mode"] == "graph_rag_lite"
    assert policy["selected_mode"] == "simple_rag"
    assert "学习特征值" not in str(policy)
```

Add API response assertions to `tests/test_study_agent_api.py`:

```python
def test_study_agent_query_returns_policy_diagnostics(tmp_path: Path):
    Session = _session_factory()
    document_service = DocumentService(
        session_factory=Session,
        storage=LocalStorageBackend(tmp_path / "storage"),
    )
    app = create_app(
        document_service=document_service,
        session_factory=Session,
        secret_key="test-secret",
        allow_dev_user_header=False,
    )
    client = TestClient(app)
    headers = _login(client)
    _insert_ready_document_for_api(Session)

    response = client.post(
        "/api/study-agent/query",
        headers=headers,
        json={
            "query": "学习特征值前需要掌握什么？",
            "document_ids": ["doc-api"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "policy" in payload
    assert payload["policy"]["selected_mode"] in {
        "simple_rag",
        "graph_rag_lite",
        "agentic_rag",
    }
    assert "query" not in payload["policy"]
```

- [ ] **Step 2: Run focused tests and confirm failure**

Run:

```bash
pytest tests/test_study_agent_runtime.py tests/test_study_agent_traces.py tests/test_study_agent_api.py -q
```

Expected: FAIL because runtime does not accept route policy dependencies and API response has no `policy` field.

- [ ] **Step 3: Integrate policy into runtime**

Modify `StudyAgentRuntimeService.__init__` in `src/services/study_agent_runtime.py`:

```python
from src.services.rag_route_policy import (
    RAGReadinessSnapshot,
    RAGRoutePolicyConfig,
    RAGRoutePolicyService,
)

...
route_policy: RAGRoutePolicyService | None = None,
readiness_provider: Callable[[], RAGReadinessSnapshot | None] | None = None,
...
self.route_policy = route_policy or RAGRoutePolicyService(RAGRoutePolicyConfig())
self.readiness_provider = readiness_provider or (lambda: None)
```

After `index_statuses` is built and before constructing the orchestrator, compute:

```python
request_policy_input = normalize_study_request(payload)
router_decision = (self.router or RAGStrategyRouter()).route(
    request_policy_input.query,
    target=request_policy_input.target.value,
)
policy_decision = self.route_policy.decide(
    router_decision=router_decision,
    readiness=self.readiness_provider(),
    index_statuses=index_statuses,
    budget=request_policy_input.budget.value,
    preferred_mode=request_policy_input.preferred_mode,
)
payload = {
    **payload,
    "preferred_mode": policy_decision.selected_mode.value,
    "policy_decision": policy_decision.to_safe_dict(),
}
```

After `result = await orchestrator.run(payload)`, add:

```python
result.audit_metadata["policy"] = policy_decision.to_safe_dict()
```

- [ ] **Step 4: Preserve policy diagnostics through Study Agent result**

Leave `normalize_study_request` unchanged for `policy_decision`; it already ignores unknown payload keys by reading only known request fields. Do not add policy inputs to `StudyRequest`.

Modify `StudyAgentOrchestrator.run` in `src/services/study_agent.py`:

```python
policy_decision = payload.get("policy_decision")
...
audit_metadata={
    "mode": plan.mode.value,
    "target": request.target.value,
    "needs_review": verification.needs_review,
    "source_count": len(evidence.sources),
    "chunk_count": len(evidence.chunks),
    "policy": policy_decision if isinstance(policy_decision, dict) else None,
}
```

Remove `None` policy before returning so existing responses stay unchanged when no policy decision exists:

```python
audit_metadata = {...}
if audit_metadata["policy"] is None:
    audit_metadata.pop("policy")
```

- [ ] **Step 5: Return policy diagnostics from API and trace payload**

In `src/api/routes/study_agent.py`, include:

```python
"policy": result.audit_metadata.get("policy"),
```

in the query response payload when present.

In `src/services/study_agent_trace.py`, include safe policy fields from `record.trace_metadata.get("policy")` or audit metadata when building trace payload:

```python
policy = record.trace_metadata.get("policy") if isinstance(record.trace_metadata, dict) else None
if isinstance(policy, dict):
    payload["policy"] = {
        "policy_version": policy.get("policy_version"),
        "router_mode": policy.get("router_mode"),
        "selected_mode": policy.get("selected_mode"),
        "category": policy.get("category"),
        "status": policy.get("status"),
        "readiness_status": policy.get("readiness_status"),
        "blocked_reason": policy.get("blocked_reason"),
        "experiment_enabled": policy.get("experiment_enabled"),
    }
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
pytest tests/test_study_agent_runtime.py tests/test_study_agent_traces.py tests/test_study_agent_api.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit runtime integration**

Run:

```bash
git add src/services/study_agent.py src/services/study_agent_runtime.py src/services/study_agent_trace.py src/api/routes/study_agent.py tests/test_study_agent_runtime.py tests/test_study_agent_traces.py tests/test_study_agent_api.py
git commit -m "feat: apply rag route policy at runtime"
```

- [ ] **Step 8: Run required reviews**

Run Spec review and Quality review for Task 3 before continuing.

## Task 4: Graph RAG Lite Metadata And Fallback Strengthening

**Files:**
- Modify: `src/services/graph_rag.py`
- Modify: `src/services/study_agent.py`
- Modify: `tests/test_graph_rag.py`

- [ ] **Step 1: Write failing graph metadata tests**

Append to `tests/test_graph_rag.py`:

```python
@pytest.mark.asyncio
async def test_graph_rag_reports_safe_expansion_metadata():
    graph = KnowledgeGraph()
    graph.add_point(KnowledgePoint("kp1", "Derivative", "Rate", "concept"))
    graph.add_point(KnowledgePoint("kp2", "Gradient", "Vector rate", "concept"))
    graph.add_relationship(Relationship("kp1", "kp2", "related"))
    chunks = [
        Chunk(
            content="Derivative and Gradient are related",
            source="calculus:chunk:1",
            metadata={"concept_id": "kp2"},
        )
    ]

    result = await GraphRAGLiteRetriever(graph, chunks).retrieve("Derivative")

    assert result.seed_count == 1
    assert result.expanded_count == 2
    assert result.hop_count == 2
    assert result.metadata == {
        "seed_count": 1,
        "expanded_count": 2,
        "hop_count": 2,
        "fallback_reason": None,
    }


@pytest.mark.asyncio
async def test_graph_rag_reports_fallback_reason_without_snippets():
    graph = KnowledgeGraph()
    result = await GraphRAGLiteRetriever(graph, []).retrieve("Derivative")

    assert result.metadata["fallback_reason"] == "no graph seed matched"
    assert "content" not in result.metadata
    assert "snippet" not in result.metadata
```

- [ ] **Step 2: Run graph tests and confirm failure**

Run:

```bash
pytest tests/test_graph_rag.py -q
```

Expected: FAIL because `GraphRAGResult` lacks metadata fields.

- [ ] **Step 3: Add graph metadata to result contract**

Modify `GraphRAGResult`:

```python
@dataclass(frozen=True)
class GraphRAGResult:
    mode: str
    reason: str
    chunks: list[Chunk]
    confidence: float
    expanded_point_ids: list[str]
    seed_count: int = 0
    expanded_count: int = 0
    hop_count: int = 0
    metadata: dict[str, int | str | None] = field(default_factory=dict)
```

Import `field` from `dataclasses`.

In `retrieve`, compute metadata:

```python
fallback_reason = None if matched_chunks else self._result_reason(seeds=seeds, chunks=matched_chunks, top_k=top_k)
metadata = {
    "seed_count": len(seeds),
    "expanded_count": len(expanded),
    "hop_count": max_hops,
    "fallback_reason": fallback_reason,
}
```

Return fields:

```python
seed_count=len(seeds),
expanded_count=len(expanded),
hop_count=max_hops,
metadata=metadata,
```

- [ ] **Step 4: Thread graph metadata into evidence**

In `src/services/study_agent.py`, when returning graph `EvidenceBundle`, add to `StudyDraft.metadata` or `audit_metadata` through evidence reason if the existing dataclass has no metadata field. Prefer adding a safe `metadata: dict[str, Any] = field(default_factory=dict)` to `EvidenceBundle` and set:

```python
metadata=result.metadata,
```

Update existing EvidenceBundle construction sites with `metadata={}` only where needed.

- [ ] **Step 5: Run graph and study-agent tests**

Run:

```bash
pytest tests/test_graph_rag.py tests/test_study_agent_runtime.py tests/test_study_agent_api.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit graph strengthening**

Run:

```bash
git add src/services/graph_rag.py src/services/study_agent.py tests/test_graph_rag.py
git commit -m "feat: add graph rag safe expansion metadata"
```

- [ ] **Step 7: Run required reviews**

Run Spec review and Quality review for Task 4 before continuing.

## Task 5: Bounded Agentic RAG Controls

**Files:**
- Modify: `src/services/agentic_rag.py`
- Modify: `src/services/study_agent.py`
- Modify: `tests/test_agentic_rag.py`
- Modify: `tests/test_study_agent_runtime.py`

- [ ] **Step 1: Write failing bounded planner tests**

Append to `tests/test_agentic_rag.py`:

```python
def test_agentic_planner_respects_max_steps():
    planner = AgenticRAGPlanner(max_steps=3)

    plan = planner.plan("基于第2章和第4章出一道综合题")

    assert len(plan.steps) == 3
    assert plan.metadata["planned_step_count"] >= 4
    assert plan.metadata["executed_step_count"] == 3
    assert plan.metadata["step_budget_exhausted"] is True


def test_agentic_planner_uses_budget_cost_labels():
    low_plan = AgenticRAGPlanner(max_steps=4).plan("解释特征值", budget="balanced")
    high_plan = AgenticRAGPlanner(max_steps=6).plan("综合第2章和第4章出一道题", budget="high")

    assert low_plan.estimated_cost in {"medium", "high"}
    assert high_plan.estimated_cost == "high"


def test_agentic_plan_metadata_excludes_raw_prompt_and_hidden_reasoning():
    plan = AgenticRAGPlanner().plan("综合第2章和第4章出一道题")

    assert "prompt" not in plan.metadata
    assert "chain_of_thought" not in plan.metadata
    assert "hidden_reasoning" not in plan.metadata
```

- [ ] **Step 2: Run agentic tests and confirm failure**

Run:

```bash
pytest tests/test_agentic_rag.py -q
```

Expected: FAIL because planner has no `max_steps`, `budget`, or `metadata`.

- [ ] **Step 3: Add planner controls**

Modify `src/services/agentic_rag.py`:

```python
@dataclass(frozen=True)
class AgenticRAGPlan:
    mode: str
    reason: str
    steps: tuple[AgenticRAGStep, ...]
    estimated_cost: str
    metadata: dict[str, int | bool | str] = field(default_factory=dict)


class AgenticRAGPlanner:
    def __init__(self, max_steps: int = 5) -> None:
        self.max_steps = max(1, max_steps)

    def plan(self, query: str, budget: str = "balanced") -> AgenticRAGPlan:
        ...
        planned_steps = tuple(steps)
        executed_steps = planned_steps[: self.max_steps]
        step_budget_exhausted = len(planned_steps) > len(executed_steps)
        estimated_cost = "high" if len(executed_steps) >= 4 or budget == "high" else "medium"
        return AgenticRAGPlan(
            mode="agentic_rag",
            reason=reason,
            steps=tuple(executed_steps),
            estimated_cost=estimated_cost,
            metadata={
                "planned_step_count": len(planned_steps),
                "executed_step_count": len(executed_steps),
                "step_budget_exhausted": step_budget_exhausted,
            },
        )
```

- [ ] **Step 4: Use budgeted planner in EvidenceCollector**

In `src/services/study_agent.py`, update:

```python
plan = self.agentic_planner.plan(request.query, budget=request.budget.value)
if plan.metadata.get("step_budget_exhausted"):
    return self._simple_bundle(
        request,
        fallback_reason="agentic step budget exhausted",
    )
```

If the graph path succeeds, include safe plan metadata in `EvidenceBundle.metadata`.

- [ ] **Step 5: Run agentic/runtime tests**

Run:

```bash
pytest tests/test_agentic_rag.py tests/test_study_agent_runtime.py tests/test_study_agent_api.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit agentic controls**

Run:

```bash
git add src/services/agentic_rag.py src/services/study_agent.py tests/test_agentic_rag.py tests/test_study_agent_runtime.py
git commit -m "feat: bound agentic rag planning"
```

- [ ] **Step 7: Run required reviews**

Run Spec review and Quality review for Task 5 before continuing.

## Task 6: Admin Policy APIs

**Files:**
- Modify: `src/api/routes/admin.py`
- Modify: `tests/test_api_permissions_audit.py`
- Modify: `tests/test_study_agent_api.py`

- [ ] **Step 1: Write failing admin API tests**

Append to `tests/test_api_permissions_audit.py`:

```python
from src.db.models import UserRecord
from src.security.auth import hash_password


def _create_user(Session, *, user_id: str, email: str, role: str = "user") -> None:
    with Session() as session:
        session.add(
            UserRecord(
                id=user_id,
                email=email,
                password_hash=hash_password("password-123"),
                role=role,
                is_active=True,
            )
        )
        session.commit()


def _login(client: TestClient, *, email: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": "password-123"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_admin_can_read_rag_route_policy(tmp_path: Path):
    client, _service, Session = _client(tmp_path)
    _create_user(
        Session,
        user_id="admin-1",
        email="admin@example.com",
        role="admin",
    )
    headers = _login(client, email="admin@example.com")

    response = client.get(
        "/api/admin/rag-route-policy",
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert "policy_version" in payload
    assert "advanced_routing_enabled" in payload


def test_non_admin_cannot_read_rag_route_policy(tmp_path: Path):
    client, _service, Session = _client(tmp_path)
    _create_user(
        Session,
        user_id="user-1",
        email="user@example.com",
        role="user",
    )
    headers = _login(client, email="user@example.com")

    response = client.get(
        "/api/admin/rag-route-policy",
        headers=headers,
    )

    assert response.status_code == 403


def test_admin_can_simulate_policy_without_raw_query_in_response(tmp_path: Path):
    client, _service, Session = _client(tmp_path)
    _create_user(
        Session,
        user_id="admin-1",
        email="admin@example.com",
        role="admin",
    )
    headers = _login(client, email="admin@example.com")

    response = client.post(
        "/api/admin/rag-route-policy/simulate",
        headers=headers,
        json={"query": "学习积分前需要掌握什么？", "budget": "balanced"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["selected_mode"] in {"simple_rag", "graph_rag_lite", "agentic_rag"}
    assert "query" not in payload
```

- [ ] **Step 2: Run admin tests and confirm failure**

Run:

```bash
pytest tests/test_api_permissions_audit.py -q
```

Expected: FAIL because policy admin routes do not exist.

- [ ] **Step 3: Add admin policy routes**

In `src/api/routes/admin.py`, import policy/router types:

```python
from src.services.rag_route_policy import RAGReadinessSnapshot, RAGRoutePolicyConfig, RAGRoutePolicyService
from src.services.rag_router import RAGStrategyRouter
```

Add helpers:

```python
def _route_policy_config(request: Request) -> RAGRoutePolicyConfig:
    return getattr(request.app.state, "rag_route_policy_config", RAGRoutePolicyConfig())


def _readiness_snapshot(request: Request) -> RAGReadinessSnapshot | None:
    provider = getattr(request.app.state, "rag_readiness_provider", None)
    return provider() if provider is not None else None
```

Add routes:

```python
@router.get("/rag-route-policy")
def get_rag_route_policy(request: Request) -> dict[str, Any]:
    _require_admin(request)
    config = _route_policy_config(request)
    return {
        "policy_version": config.policy_version,
        "advanced_routing_enabled": config.advanced_routing_enabled,
        "graph_rag_enabled": config.graph_rag_enabled,
        "agentic_rag_enabled": config.agentic_rag_enabled,
        "enabled_categories": sorted(config.enabled_categories) if config.enabled_categories else None,
        "require_persisted_chunks_for_advanced": config.require_persisted_chunks_for_advanced,
    }


@router.get("/rag-route-readiness")
def get_rag_route_readiness(request: Request) -> dict[str, Any]:
    _require_admin(request)
    snapshot = _readiness_snapshot(request)
    if snapshot is None:
        return {"available": False, "modes": {}}
    return {
        "available": True,
        "policy_version": snapshot.policy_version,
        "fixture_version": snapshot.fixture_version,
        "created_at": snapshot.created_at,
        "modes": snapshot.modes,
    }


@router.post("/rag-route-policy/simulate")
def simulate_rag_route_policy(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    _require_admin(request)
    query = str(payload.get("query", "")).strip()
    if not query:
        raise HTTPException(status_code=422, detail="query is required")
    router_decision = RAGStrategyRouter().route(query, target=payload.get("target"))
    policy_decision = RAGRoutePolicyService(_route_policy_config(request)).decide(
        router_decision=router_decision,
        readiness=_readiness_snapshot(request),
        index_statuses=payload.get("index_statuses") or {},
        budget=str(payload.get("budget") or "balanced"),
    )
    return policy_decision.to_safe_dict()
```

Do not include raw query in response or audit metadata.

- [ ] **Step 4: Run admin tests**

Run:

```bash
pytest tests/test_api_permissions_audit.py tests/test_study_agent_api.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit admin API routes**

Run:

```bash
git add src/api/routes/admin.py tests/test_api_permissions_audit.py tests/test_study_agent_api.py
git commit -m "feat: expose rag route policy admin APIs"
```

- [ ] **Step 6: Run required reviews**

Run Spec review and Quality review for Task 6 before continuing.

## Task 7: Frontend Policy Diagnostics

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/components/StudyAgentPanel.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Add frontend API type**

In `frontend/src/api.ts`, add:

```ts
export type StudyAgentPolicyDiagnostic = {
  policy_version?: string | null;
  router_mode?: RetrievalMode | null;
  selected_mode?: RetrievalMode | null;
  category?: string | null;
  status?: string | null;
  readiness_status?: string | null;
  blocked_reason?: string | null;
  experiment_enabled?: boolean | null;
};
```

Add `policy?: StudyAgentPolicyDiagnostic | null;` to the Study Agent query response type.

- [ ] **Step 2: Add compact UI diagnostics**

In `frontend/src/components/StudyAgentPanel.tsx`, render below existing trace diagnostics:

```tsx
{result.policy ? (
  <div className="study-agent-policy">
    <span>Policy: {result.policy.status ?? "unknown"}</span>
    <span>Mode: {result.policy.selected_mode ?? "unknown"}</span>
    {result.policy.category ? <span>Category: {result.policy.category}</span> : null}
    {result.policy.blocked_reason ? (
      <span className="study-agent-policy-warning">{result.policy.blocked_reason}</span>
    ) : null}
  </div>
) : null}
```

Keep text compact and avoid adding a dashboard or new route.

- [ ] **Step 3: Add styles**

In `frontend/src/styles.css`, add:

```css
.study-agent-policy {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  color: #374151;
  font-size: 0.85rem;
}

.study-agent-policy-warning {
  color: #92400e;
  font-weight: 600;
}
```

- [ ] **Step 4: Run frontend build**

Run:

```bash
cd frontend && npm run build
```

Expected: PASS.

- [ ] **Step 5: Commit frontend diagnostics**

Run:

```bash
git add frontend/src/api.ts frontend/src/components/StudyAgentPanel.tsx frontend/src/styles.css
git commit -m "feat: show rag route policy diagnostics"
```

- [ ] **Step 6: Run required reviews**

Run Spec review and Quality review for Task 7 before continuing.

## Task 8: Evaluation Fixtures, Reports, Docs, And Final Verification

**Files:**
- Modify: `tests/fixtures/rag_eval_set.json`
- Modify: `src/services/rag_evaluation.py`
- Modify: `tests/test_rag_evaluation.py`
- Modify: `tests/test_rag_mode_comparison.py`
- Modify: `README.md`
- Modify: `SPEC.md`

- [ ] **Step 1: Expand evaluation fixture**

Update every object in `tests/fixtures/rag_eval_set.json` with:

```json
{
  "expected_category": "definition",
  "expected_router_mode": "simple_rag",
  "expected_selected_mode_when_ready": "simple_rag",
  "expected_selected_mode_when_not_ready": "simple_rag",
  "requires_persisted_chunks": true,
  "max_allowed_cost": "low",
  "policy_notes": "baseline direct lookup"
}
```

Ensure the fixture includes at least one case for:

- `direct_lookup`
- `definition`
- `concept_relation`
- `learning_path`
- `multi_document_synthesis`
- `question_generation`
- `outline_fragment`

Ensure `question_generation` and `multi_document_synthesis` each have at least two cases.

- [ ] **Step 2: Write failing fixture/report tests**

Append to `tests/test_rag_evaluation.py`:

```python
def test_policy_fixture_fields_are_required():
    cases = load_rag_eval_cases("tests/fixtures/rag_eval_set.json")

    categories = {case.category for case in cases}
    assert "question_generation" in categories
    assert "multi_document_synthesis" in categories
    for case in cases:
        assert case.expected_category
        assert case.expected_router_mode
        assert case.expected_selected_mode_when_ready
        assert case.expected_selected_mode_when_not_ready
```

Append to `tests/test_rag_mode_comparison.py`:

```python
def test_policy_summary_counts_statuses():
    summary = summarize_policy_statuses(
        [
            {"policy_status": "allowed", "category": "definition"},
            {"policy_status": "blocked_by_readiness", "category": "question_generation"},
        ]
    )

    assert summary["status_counts"]["allowed"] == 1
    assert summary["status_counts"]["blocked_by_readiness"] == 1
    assert summary["category_counts"]["question_generation"] == 1
```

- [ ] **Step 3: Run evaluation tests and confirm failure**

Run:

```bash
pytest tests/test_rag_evaluation.py tests/test_rag_mode_comparison.py -q
```

Expected: FAIL because fixture dataclass and summary helper do not include policy fields.

- [ ] **Step 4: Add policy fixture fields and summary helper**

In `src/services/rag_evaluation.py`, add fields to `RAGEvalCase`:

```python
expected_category: str | None = None
expected_router_mode: str | None = None
expected_selected_mode_when_ready: str | None = None
expected_selected_mode_when_not_ready: str | None = None
requires_persisted_chunks: bool = True
max_allowed_cost: str | None = None
policy_notes: str | None = None
```

Add required policy fixture keys:

```python
POLICY_FIXTURE_KEYS = {
    "expected_category",
    "expected_router_mode",
    "expected_selected_mode_when_ready",
    "expected_selected_mode_when_not_ready",
}
```

Make the fixture loader require these keys for P2 fixtures.

Add:

```python
def summarize_policy_statuses(rows: list[dict]) -> dict:
    status_counts: dict[str, int] = defaultdict(int)
    category_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        status = str(row.get("policy_status") or "unknown")
        category = str(row.get("category") or "unknown")
        status_counts[status] += 1
        category_counts[category] += 1
    return {
        "status_counts": dict(sorted(status_counts.items())),
        "category_counts": dict(sorted(category_counts.items())),
    }
```

- [ ] **Step 5: Update docs**

In `README.md`, add to current MVP-9/P2 status:

```markdown
The next P2 slice adds a conservative RAG route policy: Graph RAG Lite and Agentic RAG remain gated by feature flags, readiness, budget, and index health, with simple RAG as the fallback.
```

In `SPEC.md`, add to the current implementation status:

```markdown
- RAG route policy P2: planned controlled automatic routing using readiness gates, feature flags, budget, index health, and safe fallback. It does not add embeddings, pgvector migration, graph database work, or self-evolution.
```

- [ ] **Step 6: Run final verification**

Run:

```bash
pytest tests/test_rag_route_policy.py tests/test_rag_router.py tests/test_study_agent_runtime.py tests/test_graph_rag.py tests/test_agentic_rag.py tests/test_study_agent_api.py tests/test_api_permissions_audit.py tests/test_rag_evaluation.py tests/test_rag_mode_comparison.py -q
cd frontend && npm run build
```

Expected: PASS.

- [ ] **Step 7: Commit evaluation/docs**

Run:

```bash
git add tests/fixtures/rag_eval_set.json src/services/rag_evaluation.py tests/test_rag_evaluation.py tests/test_rag_mode_comparison.py README.md SPEC.md
git commit -m "docs: sync rag route policy p2 plan"
```

- [ ] **Step 8: Run final task reviews**

Run Spec review and Quality review for Task 8 before marking P2 implementation complete.

## Final Verification Before Completion

After all tasks and reviews pass, run:

```bash
pytest tests/test_rag_route_policy.py tests/test_rag_router.py tests/test_study_agent_runtime.py tests/test_graph_rag.py tests/test_agentic_rag.py tests/test_study_agent_api.py tests/test_api_permissions_audit.py tests/test_rag_evaluation.py tests/test_rag_mode_comparison.py -q
cd frontend && npm run build
git status --short --branch
```

Expected:

- backend tests pass;
- frontend build passes;
- no generated `docs/evaluation/*.json` or `docs/evaluation/*.md` artifacts are tracked or left untracked;
- worktree is clean after final commit.

## Self-Review Checklist For This Plan

- Spec coverage: Tasks 1-8 cover policy service, config, readiness, category classification, runtime integration, Graph RAG, Agentic RAG, admin APIs, frontend diagnostics, evaluation fixtures, reports, docs, privacy, and fallback behavior.
- Placeholder scan: No task uses unresolved placeholders or asks a worker to invent missing behavior without examples.
- Type consistency: `RetrievalMode`, `QueryCategory`, `RAGRoutePolicyConfig`, `RAGReadinessSnapshot`, and `RAGRoutePolicyDecision` names are consistent across tasks.
- Scope check: No task adds embeddings, pgvector migration, graph database work, self-evolution, prompt mutation, or a dashboard.
