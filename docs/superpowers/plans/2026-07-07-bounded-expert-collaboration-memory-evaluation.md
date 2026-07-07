# Bounded Expert Collaboration And Memory Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add policy-gated expert collaboration and owner-scoped skill performance aggregates without introducing open-ended autonomous loops, raw memory replay, or automatic prompt evolution.

**Architecture:** Keep `StudyAgentRuntimeService` as the product mainline. Add focused services for expert contracts/gating/execution and skill performance aggregation; feed only safe expert labels/counts into workflow/trace/API/frontend diagnostics. Expert execution is disabled by default and falls back to the existing serial Study Agent path on any gate failure, timeout, or branch error.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy, pytest, React/Vite/TypeScript.

---

## Source Spec

Implement:

- `docs/superpowers/specs/2026-07-07-bounded-expert-collaboration-memory-evaluation-design.md`

## File Structure

- Create `src/services/study_agent_experts.py`: expert config, branch result contract, safe metadata sanitizer, eligibility gate, and deterministic branch runner.
- Modify `src/services/study_agent_runtime.py`: accept expert config/runner, evaluate expert gate, execute optional branches, attach safe workflow/trace metadata, keep serial fallback.
- Modify `src/services/study_agent_workflow.py`: add `expert_gate` stage and safe expert metadata keys/reason codes.
- Modify `src/services/study_agent_trace.py`: add `safe_expert_metadata()` and include safe expert metadata in trace payloads.
- Create `src/services/study_agent_skill_performance.py`: owner-scoped aggregate metrics from traces and safe memory/review metadata.
- Modify `src/api/routes/study_agent.py`: add `GET /api/study-agent/skills/performance`.
- Modify `frontend/src/api.ts`: add expert diagnostics and skill performance types/API call.
- Modify `frontend/src/components/StudyAgentPanel.tsx`: render compact expert diagnostics and selected skill performance.
- Modify `frontend/src/styles.css`: compact diagnostic styling.
- Modify `README.md` and `SPEC.md`: document bounded expert collaboration and memory-guided evaluation status after implementation.
- Tests:
  - Create `tests/test_study_agent_experts.py`
  - Create `tests/test_study_agent_skill_performance.py`
  - Extend `tests/test_study_agent_runtime.py`
  - Extend `tests/test_study_agent_workflow.py`
  - Extend `tests/test_study_agent_traces.py`
  - Extend `tests/test_study_agent_api.py`

## Implementation Rules

- Do not store raw query text, generated answers/questions, chunk content, source snippets, prompts, hidden reasoning, exception strings, file paths, tokens, passwords, authorization headers, API keys, or secrets in expert/workflow/trace/API/frontend metadata.
- Do not add automatic skill promotion/demotion.
- Do not mutate prompts or skill contracts.
- Do not introduce a graph database or new provider.
- Expert collaboration defaults to disabled.
- Every task must pass Spec review and Quality/privacy review before the next task starts.

---

## Task 1: Expert Contract, Sanitizer, And Eligibility Gate

**Files:**
- Create: `src/services/study_agent_experts.py`
- Test: `tests/test_study_agent_experts.py`

- [ ] **Step 1: Write failing expert contract tests**

Create `tests/test_study_agent_experts.py`:

```python
from __future__ import annotations

from src.services.rag_route_policy import RAGRoutePolicyDecision
from src.services.rag_router import RetrievalMode
from src.services.study_agent import StudyBudget, StudyTarget
from src.services.study_agent_experts import (
    ExpertBranchResult,
    ExpertCollaborationConfig,
    ExpertEligibilityService,
    safe_expert_metadata,
)
from src.services.study_agent_skills import StudySkill


def _policy(
    *,
    selected_mode: RetrievalMode = RetrievalMode.AGENTIC,
    category: str = "multi_document_synthesis",
    status: str = "allowed",
) -> RAGRoutePolicyDecision:
    return RAGRoutePolicyDecision(
        selected_mode=selected_mode,
        router_mode=selected_mode,
        effective_mode=selected_mode,
        category=category,
        status=status,
        reason=f"{selected_mode.value} is allowed by route policy",
        fallback_chain=[RetrievalMode.GRAPH, RetrievalMode.SIMPLE],
        readiness_status="candidate",
        blocked_reason=None,
        estimated_cost="high",
        experiment_enabled=True,
        policy_version="rag-policy-v1",
    )


def _skill(*, modes=(RetrievalMode.AGENTIC, RetrievalMode.GRAPH, RetrievalMode.SIMPLE)):
    return StudySkill(
        skill_name="multi_document_synthesis",
        version="v1",
        supported_targets=(StudyTarget.ANSWER, StudyTarget.QUESTION),
        allowed_retrieval_modes=tuple(modes),
        default_budget=StudyBudget.HIGH,
        review_gate_profile="strict",
        memory_inputs=("user_preference", "study_state"),
        memory_outputs=("review_outcome", "skill_performance"),
    )


def test_expert_branch_result_safe_dict_omits_raw_values():
    result = ExpertBranchResult(
        branch_name="retrieval_expert",
        status="passed",
        source_ids=("document:doc-1:chunk:0", "/tmp/raw-secret.pdf"),
        concept_ids=("derivative", "sk-secret-token"),
        confidence=0.88,
        metrics={
            "source_count": 1,
            "chunk_count": 2,
            "query": "raw private query",
            "prompt": "hidden prompt",
            "token": "sk-secret-token",
            "latency_ms": 12.5,
        },
        safe_reason_code=None,
        internal_payload={"draft": "generated answer should not persist"},
    )

    safe = result.to_safe_dict()

    assert safe == {
        "branch_name": "retrieval_expert",
        "status": "passed",
        "source_count": 1,
        "concept_count": 1,
        "confidence": 0.88,
        "metrics": {
            "source_count": 1,
            "chunk_count": 2,
            "latency_ms": 12.5,
        },
    }
    serialized = str(safe).lower()
    assert "raw private query" not in serialized
    assert "hidden prompt" not in serialized
    assert "sk-secret-token" not in serialized
    assert "/tmp/raw-secret" not in serialized
    assert "generated answer" not in serialized


def test_safe_expert_metadata_allows_only_labels_counts_and_statuses():
    metadata = safe_expert_metadata(
        {
            "enabled": True,
            "branch_count": 2,
            "timeout_count": 1,
            "failure_count": 0,
            "fallback_reason": "branch_timeout",
            "branch_statuses": {
                "retrieval_expert": "passed",
                "graph_expert": "timeout",
                "raw_private_branch": "passed",
            },
            "query": "raw private query",
            "exception": "ValueError sk-secret-token",
        }
    )

    assert metadata == {
        "enabled": True,
        "branch_count": 2,
        "timeout_count": 1,
        "failure_count": 0,
        "fallback_reason": "branch_timeout",
        "branch_statuses": {
            "retrieval_expert": "passed",
            "graph_expert": "timeout",
        },
    }


def test_expert_gate_is_disabled_by_default():
    decision = ExpertEligibilityService(ExpertCollaborationConfig()).decide(
        policy_decision=_policy(),
        skill=_skill(),
        index_statuses={"doc-1": {"status": "indexed"}},
    )

    assert decision.enabled is False
    assert decision.safe_reason_code == "expert_disabled"


def test_expert_gate_allows_eligible_policy_skill_and_index():
    config = ExpertCollaborationConfig(enabled=True, max_branches=3, branch_timeout_seconds=0.1)
    decision = ExpertEligibilityService(config).decide(
        policy_decision=_policy(),
        skill=_skill(),
        index_statuses={"doc-1": {"status": "indexed"}},
    )

    assert decision.enabled is True
    assert decision.safe_reason_code is None
    assert decision.max_branches == 3


def test_expert_gate_blocks_non_eligible_category_policy_and_skill_mode():
    service = ExpertEligibilityService(ExpertCollaborationConfig(enabled=True))

    assert service.decide(
        policy_decision=_policy(category="definition"),
        skill=_skill(),
        index_statuses={"doc-1": {"status": "indexed"}},
    ).safe_reason_code == "category_not_eligible"
    assert service.decide(
        policy_decision=_policy(status="blocked_by_budget"),
        skill=_skill(),
        index_statuses={"doc-1": {"status": "indexed"}},
    ).safe_reason_code == "policy_not_allowed"
    assert service.decide(
        policy_decision=_policy(selected_mode=RetrievalMode.AGENTIC),
        skill=_skill(modes=(RetrievalMode.SIMPLE,)),
        index_statuses={"doc-1": {"status": "indexed"}},
    ).safe_reason_code == "mode_not_allowed_by_skill"


def test_expert_gate_blocks_unhealthy_index():
    service = ExpertEligibilityService(ExpertCollaborationConfig(enabled=True))
    decision = service.decide(
        policy_decision=_policy(),
        skill=_skill(),
        index_statuses={"doc-1": {"status": "fallback_available"}},
    )

    assert decision.enabled is False
    assert decision.safe_reason_code == "index_not_ready"
```

- [ ] **Step 2: Run failing expert tests**

Run:

```bash
pytest tests/test_study_agent_experts.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.services.study_agent_experts'`.

- [ ] **Step 3: Implement expert contract and gate**

Create `src/services/study_agent_experts.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from src.services.rag_route_policy import RAGRoutePolicyDecision
from src.services.rag_router import RetrievalMode
from src.services.study_agent_skills import StudySkill

ExpertBranchName = Literal[
    "retrieval_expert",
    "graph_expert",
    "question_expert",
    "synthesis_expert",
]
ExpertBranchStatus = Literal["passed", "skipped", "failed", "timeout"]

SAFE_BRANCH_NAMES = {
    "retrieval_expert",
    "graph_expert",
    "question_expert",
    "synthesis_expert",
}
SAFE_BRANCH_STATUSES = {"passed", "skipped", "failed", "timeout"}
SAFE_REASON_CODES = {
    "expert_disabled",
    "category_not_eligible",
    "policy_not_allowed",
    "mode_not_allowed_by_skill",
    "index_not_ready",
    "budget_not_allowed",
    "branch_timeout",
    "branch_error",
    "graph_unavailable",
    "serial_fallback",
}
ELIGIBLE_CATEGORIES = {"multi_document_synthesis", "question_generation"}
ADVANCED_MODES = {RetrievalMode.AGENTIC, RetrievalMode.GRAPH}
SAFE_METRIC_KEYS = {
    "source_count",
    "chunk_count",
    "concept_count",
    "graph_hop_count",
    "latency_ms",
    "fallback_used",
}


@dataclass(frozen=True)
class ExpertCollaborationConfig:
    enabled: bool = False
    max_branches: int = 3
    branch_timeout_seconds: float = 1.0
    require_indexed_chunks: bool = True


@dataclass(frozen=True)
class ExpertGateDecision:
    enabled: bool
    safe_reason_code: str | None
    max_branches: int
    branch_timeout_seconds: float

    def to_safe_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "enabled": self.enabled,
            "branch_count": 0,
            "timeout_count": 0,
            "failure_count": 0,
        }
        if self.safe_reason_code in SAFE_REASON_CODES:
            payload["fallback_reason"] = self.safe_reason_code
        return payload


@dataclass(frozen=True)
class ExpertBranchResult:
    branch_name: str
    status: str
    source_ids: tuple[str, ...] = ()
    concept_ids: tuple[str, ...] = ()
    confidence: float = 0.0
    metrics: dict[str, Any] = field(default_factory=dict)
    safe_reason_code: str | None = None
    internal_payload: dict[str, Any] = field(default_factory=dict)

    def to_safe_dict(self) -> dict[str, Any]:
        safe: dict[str, Any] = {}
        if self.branch_name in SAFE_BRANCH_NAMES:
            safe["branch_name"] = self.branch_name
        if self.status in SAFE_BRANCH_STATUSES:
            safe["status"] = self.status
        source_ids = tuple(_safe_source_id(item) for item in self.source_ids)
        source_ids = tuple(item for item in source_ids if item is not None)
        concept_ids = tuple(_safe_label(item) for item in self.concept_ids)
        concept_ids = tuple(item for item in concept_ids if item is not None)
        safe["source_count"] = len(source_ids)
        safe["concept_count"] = len(concept_ids)
        safe["confidence"] = _safe_float(self.confidence)
        metrics = _safe_metrics(self.metrics)
        if metrics:
            safe["metrics"] = metrics
        if self.safe_reason_code in SAFE_REASON_CODES:
            safe["safe_reason_code"] = self.safe_reason_code
        return safe


class ExpertEligibilityService:
    def __init__(self, config: ExpertCollaborationConfig | None = None) -> None:
        self.config = config or ExpertCollaborationConfig()

    def decide(
        self,
        *,
        policy_decision: RAGRoutePolicyDecision,
        skill: StudySkill,
        index_statuses: dict[str, dict[str, Any]],
    ) -> ExpertGateDecision:
        if not self.config.enabled:
            return self._blocked("expert_disabled")
        if policy_decision.category not in ELIGIBLE_CATEGORIES:
            return self._blocked("category_not_eligible")
        if policy_decision.status != "allowed":
            return self._blocked("policy_not_allowed")
        if policy_decision.selected_mode not in ADVANCED_MODES:
            return self._blocked("policy_not_allowed")
        if policy_decision.selected_mode not in skill.allowed_retrieval_modes:
            return self._blocked("mode_not_allowed_by_skill")
        if self.config.require_indexed_chunks and not _all_indexes_ready(index_statuses):
            return self._blocked("index_not_ready")
        return ExpertGateDecision(
            enabled=True,
            safe_reason_code=None,
            max_branches=max(1, min(4, int(self.config.max_branches))),
            branch_timeout_seconds=max(0.01, float(self.config.branch_timeout_seconds)),
        )

    def _blocked(self, reason: str) -> ExpertGateDecision:
        return ExpertGateDecision(
            enabled=False,
            safe_reason_code=reason,
            max_branches=0,
            branch_timeout_seconds=max(0.01, float(self.config.branch_timeout_seconds)),
        )


def safe_expert_metadata(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    safe: dict[str, Any] = {}
    if isinstance(value.get("enabled"), bool):
        safe["enabled"] = value["enabled"]
    for source, target in {
        "branch_count": "branch_count",
        "timeout_count": "timeout_count",
        "failure_count": "failure_count",
    }.items():
        count = _safe_int(value.get(source))
        if count is not None:
            safe[target] = count
    reason = value.get("fallback_reason")
    if isinstance(reason, str) and reason in SAFE_REASON_CODES:
        safe["fallback_reason"] = reason
    statuses = value.get("branch_statuses")
    if isinstance(statuses, dict):
        safe_statuses = {
            key: status
            for key, status in statuses.items()
            if key in SAFE_BRANCH_NAMES and status in SAFE_BRANCH_STATUSES
        }
        if safe_statuses:
            safe["branch_statuses"] = safe_statuses
    return safe or None


def _all_indexes_ready(index_statuses: dict[str, dict[str, Any]]) -> bool:
    return bool(index_statuses) and all(
        payload.get("status") == "indexed" for payload in index_statuses.values()
    )


def _safe_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in metrics.items():
        if key not in SAFE_METRIC_KEYS:
            continue
        if isinstance(value, bool):
            safe[key] = value
        elif isinstance(value, int) and value >= 0:
            safe[key] = value
        elif isinstance(value, float) and value >= 0:
            safe[key] = round(value, 6)
    return safe


def _safe_source_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    if value.startswith("document:") and 1 <= len(value) <= 128:
        return value
    return None


def _safe_label(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    if 1 <= len(value) <= 64 and all(char.isalnum() or char in {"_", "-", ":"} for char in value):
        if "secret" not in value.lower() and "token" not in value.lower():
            return value
    return None


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _safe_float(value: Any) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return round(max(0.0, min(1.0, float(value))), 6)
    return 0.0
```

- [ ] **Step 4: Run expert contract tests**

Run:

```bash
pytest tests/test_study_agent_experts.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit expert contract**

Run:

```bash
git add src/services/study_agent_experts.py tests/test_study_agent_experts.py
git commit -m "feat: add bounded expert gate contracts"
```

- [ ] **Step 6: Required reviews**

Run Task 1 Spec review and Quality/privacy review before starting Task 2.

---

## Task 2: Workflow And Trace Expert Metadata Sanitizers

**Files:**
- Modify: `src/services/study_agent_workflow.py`
- Modify: `src/services/study_agent_trace.py`
- Test: `tests/test_study_agent_workflow.py`
- Test: `tests/test_study_agent_traces.py`

- [ ] **Step 1: Write failing workflow sanitizer tests**

Append to `tests/test_study_agent_workflow.py`:

```python
from src.services.study_agent_workflow import (
    WorkflowStageName,
    WorkflowStageResult,
    WorkflowStageStatus,
    sanitize_workflow_payload,
    build_workflow_payload,
)


def test_workflow_sanitizer_keeps_safe_expert_gate_metadata_only():
    workflow = build_workflow_payload(
        workflow_id="workflow-0123456789abcdef0123456789abcdef",
        stages=[
            WorkflowStageResult(
                stage_name=WorkflowStageName.EXPERT_GATE,
                status=WorkflowStageStatus.SKIPPED,
                input_summary={"query": "raw private query"},
                output_summary={
                    "expert_enabled": False,
                    "expert_branch_count": 0,
                    "expert_timeout_count": 0,
                    "expert_failure_count": 0,
                    "expert_fallback_reason": "expert_disabled",
                    "prompt": "hidden prompt",
                    "token": "sk-secret-token",
                },
                duration_ms=0,
            )
        ],
        needs_review=False,
    )

    safe = sanitize_workflow_payload(workflow)

    assert safe is not None
    stage = safe["stages"][0]
    assert stage["stage"] == "expert_gate"
    assert stage["status"] == "skipped"
    assert stage["input_summary"] == {}
    assert stage["output_summary"] == {
        "expert_enabled": False,
        "expert_branch_count": 0,
        "expert_timeout_count": 0,
        "expert_failure_count": 0,
        "expert_fallback_reason": "expert_disabled",
    }
    serialized = str(safe).lower()
    assert "raw private query" not in serialized
    assert "hidden prompt" not in serialized
    assert "sk-secret-token" not in serialized
```

- [ ] **Step 2: Write failing trace sanitizer tests**

Append to `tests/test_study_agent_traces.py`:

```python
from src.services.study_agent_trace import safe_expert_metadata


def test_trace_expert_sanitizer_keeps_labels_and_counts_only():
    safe = safe_expert_metadata(
        {
            "enabled": True,
            "branch_count": 2,
            "timeout_count": 1,
            "failure_count": 0,
            "fallback_reason": "branch_timeout",
            "branch_statuses": {
                "retrieval_expert": "passed",
                "graph_expert": "timeout",
                "raw_branch": "passed",
            },
            "query": "raw private query",
            "chunk_content": "secret source text",
            "token": "sk-secret-token",
        }
    )

    assert safe == {
        "enabled": True,
        "branch_count": 2,
        "timeout_count": 1,
        "failure_count": 0,
        "fallback_reason": "branch_timeout",
        "branch_statuses": {
            "retrieval_expert": "passed",
            "graph_expert": "timeout",
        },
    }
```

- [ ] **Step 3: Run failing sanitizer tests**

Run:

```bash
pytest tests/test_study_agent_workflow.py::test_workflow_sanitizer_keeps_safe_expert_gate_metadata_only tests/test_study_agent_traces.py::test_trace_expert_sanitizer_keeps_labels_and_counts_only -q
```

Expected: FAIL because `WorkflowStageName.EXPERT_GATE` and `safe_expert_metadata` are missing.

- [ ] **Step 4: Extend workflow safe metadata**

Modify `src/services/study_agent_workflow.py`:

```python
class WorkflowStageName(str, Enum):
    INTAKE = "intake"
    PLAN = "plan"
    SKILL_SELECT = "skill_select"
    RETRIEVE = "retrieve"
    EXPERT_GATE = "expert_gate"
    GENERATE = "generate"
    VERIFY = "verify"
    REVIEW_GATE = "review_gate"
    MEMORY_UPDATE = "memory_update"
    TRACE = "trace"
```

Extend `_SAFE_STRING_VALUES`:

```python
    "expert_fallback_reason": {
        "expert_disabled",
        "category_not_eligible",
        "policy_not_allowed",
        "mode_not_allowed_by_skill",
        "index_not_ready",
        "budget_not_allowed",
        "branch_timeout",
        "branch_error",
        "graph_unavailable",
        "serial_fallback",
    },
```

Extend `_SAFE_INT_KEYS`:

```python
    "expert_branch_count",
    "expert_timeout_count",
    "expert_failure_count",
```

Extend `_SAFE_BOOL_KEYS`:

```python
    "expert_enabled",
```

- [ ] **Step 5: Add trace expert sanitizer**

Modify `src/services/study_agent_trace.py`:

```python
from src.services.study_agent_experts import safe_expert_metadata
```

In `record_success()` after workflow metadata:

```python
        safe_expert = safe_expert_metadata(result.audit_metadata.get("expert"))
        if safe_expert is not None:
            trace_metadata["expert"] = safe_expert
```

In `_trace_payload()` after workflow metadata:

```python
    expert = safe_expert_metadata((record.trace_metadata or {}).get("expert"))
    if expert is not None:
        payload["expert"] = expert
```

- [ ] **Step 6: Run sanitizer tests**

Run:

```bash
pytest tests/test_study_agent_workflow.py::test_workflow_sanitizer_keeps_safe_expert_gate_metadata_only tests/test_study_agent_traces.py::test_trace_expert_sanitizer_keeps_labels_and_counts_only -q
```

Expected: PASS.

- [ ] **Step 7: Run trace/workflow suites**

Run:

```bash
pytest tests/test_study_agent_workflow.py tests/test_study_agent_traces.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit sanitizer changes**

Run:

```bash
git add src/services/study_agent_workflow.py src/services/study_agent_trace.py tests/test_study_agent_workflow.py tests/test_study_agent_traces.py
git commit -m "feat: persist safe expert diagnostics"
```

- [ ] **Step 9: Required reviews**

Run Task 2 Spec review and Quality/privacy review before starting Task 3.

---

## Task 3: Runtime Expert Gate And Deterministic Branch Runner

**Files:**
- Modify: `src/services/study_agent_experts.py`
- Modify: `src/services/study_agent_runtime.py`
- Test: `tests/test_study_agent_experts.py`
- Test: `tests/test_study_agent_runtime.py`

- [ ] **Step 1: Write failing branch runner test**

Append to `tests/test_study_agent_experts.py`:

```python
import pytest

from src.services.rag_service import Chunk
from src.services.study_agent_experts import DeterministicExpertBranchRunner, ExpertGateDecision


@pytest.mark.asyncio
async def test_deterministic_expert_runner_returns_safe_branch_summary():
    runner = DeterministicExpertBranchRunner()
    summary = await runner.run(
        gate=ExpertGateDecision(
            enabled=True,
            safe_reason_code=None,
            max_branches=3,
            branch_timeout_seconds=0.1,
        ),
        category="multi_document_synthesis",
        chunks=(
            Chunk(
                content="raw derivative text should not persist",
                source="document:doc-1:chunk:0",
                metadata={"owner_id": "user-1", "document_id": "doc-1", "concept_id": "derivative"},
                score=0.9,
            ),
        ),
        concept_ids=("derivative",),
    )

    assert summary.to_safe_dict() == {
        "enabled": True,
        "branch_count": 3,
        "timeout_count": 0,
        "failure_count": 0,
        "branch_statuses": {
            "retrieval_expert": "passed",
            "graph_expert": "passed",
            "synthesis_expert": "passed",
        },
    }
    assert "raw derivative text" not in str(summary.to_safe_dict()).lower()
```

- [ ] **Step 2: Write failing runtime eligibility tests**

Append to `tests/test_study_agent_runtime.py`:

```python
from src.services.study_agent_experts import (
    DeterministicExpertBranchRunner,
    ExpertCollaborationConfig,
)


def _insert_persisted_chunk_with_concept(
    Session,
    *,
    document_id: str = "doc-study",
    owner_id: str = "user-1",
    artifact_id: str = "artifact-doc-study",
    content: str = "Persisted derivatives evidence.",
    concept_id: str | None = "derivative",
) -> None:
    with Session() as session:
        metadata = {
            "owner_id": owner_id,
            "document_id": document_id,
            "document_title": "Calculus Notes",
            "artifact_id": artifact_id,
            "artifact_type": "normalized_document",
            "chunk_index": 0,
            "chunk_count": 1,
            "source_kind": "persisted_document_chunk",
        }
        if concept_id:
            metadata["concept_id"] = concept_id
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
                chunk_metadata=metadata,
                content_hash=f"hash-{document_id}",
            )
        )
        session.commit()


def _advanced_runtime(Session, *, enabled=True, readiness_modes=None, timeout_seconds=0.1):
    return StudyAgentRuntimeService(
        session_factory=Session,
        expert_config=ExpertCollaborationConfig(
            enabled=enabled,
            max_branches=3,
            branch_timeout_seconds=timeout_seconds,
        ),
        expert_runner=DeterministicExpertBranchRunner(),
        route_policy=RAGRoutePolicyService(
            RAGRoutePolicyConfig(
                advanced_routing_enabled=True,
                graph_rag_enabled=True,
                agentic_rag_enabled=True,
                require_persisted_chunks_for_advanced=True,
                max_budget_for_agentic="high",
            )
        ),
        readiness_provider=lambda: RAGReadinessSnapshot(
            policy_version="rag-policy-v1",
            fixture_version="test-fixture",
            modes=readiness_modes
            or {
                "agentic_rag": {
                    "overall": "candidate",
                    "by_category": {
                        "multi_document_synthesis": "candidate",
                        "question_generation": "candidate",
                    },
                },
                "graph_rag_lite": {"overall": "candidate"},
            },
        ),
    )


@pytest.mark.asyncio
async def test_runtime_runs_expert_branches_for_eligible_synthesis_request():
    Session = _session_factory()
    _insert_ready_document_with_artifact(Session, content="Chapter 2 and Chapter 4 connect derivatives and integrals.")
    _insert_persisted_chunk_with_concept(Session, content="Chapter 2 and Chapter 4 connect derivatives and integrals.")
    runtime = _advanced_runtime(Session)

    result = await runtime.run(
        {
            "query": "Compare 第2章 and 第4章 for an exam synthesis.",
            "target": "answer",
            "document_ids": ["doc-study"],
            "budget": "high",
            "authenticated_user_id": "user-1",
            "request_id": "req-expert-synthesis",
        }
    )

    assert result.audit_metadata["expert"] == {
        "enabled": True,
        "branch_count": 3,
        "timeout_count": 0,
        "failure_count": 0,
        "branch_statuses": {
            "retrieval_expert": "passed",
            "graph_expert": "passed",
            "synthesis_expert": "passed",
        },
    }
    expert_stage = next(
        stage for stage in result.audit_metadata["workflow"]["stages"] if stage["stage"] == "expert_gate"
    )
    assert expert_stage["output_summary"]["expert_enabled"] is True
    assert expert_stage["output_summary"]["expert_branch_count"] == 3


@pytest.mark.asyncio
async def test_runtime_skips_experts_for_non_eligible_category():
    Session = _session_factory()
    _insert_ready_document_with_artifact(Session)
    _insert_persisted_chunk_with_concept(Session)
    runtime = _advanced_runtime(Session)

    result = await runtime.run(
        {
            "query": "What do derivatives measure?",
            "target": "answer",
            "document_ids": ["doc-study"],
            "budget": "high",
            "authenticated_user_id": "user-1",
            "request_id": "req-expert-direct",
        }
    )

    assert result.audit_metadata["expert"]["enabled"] is False
    assert result.audit_metadata["expert"]["fallback_reason"] == "category_not_eligible"


@pytest.mark.asyncio
async def test_runtime_expert_gate_does_not_receive_cross_owner_chunks():
    Session = _session_factory()
    _insert_ready_document_with_artifact(Session)
    _insert_persisted_chunk_with_concept(Session)
    _insert_ready_document_with_artifact(
        Session,
        document_id="doc-other",
        owner_id="user-2",
        content="Private other owner content.",
    )
    _insert_persisted_chunk_with_concept(
        Session,
        document_id="doc-other",
        owner_id="user-2",
        artifact_id="artifact-doc-other",
        content="Private other owner content.",
        concept_id="other-private-concept",
    )
    runtime = _advanced_runtime(Session)

    result = await runtime.run(
        {
            "query": "Compare 第2章 and 第4章 for an exam synthesis.",
            "target": "answer",
            "document_ids": ["doc-study"],
            "budget": "high",
            "authenticated_user_id": "user-1",
            "request_id": "req-expert-owner-scope",
        }
    )

    serialized = str(result.audit_metadata["expert"]).lower()
    assert "doc-other" not in serialized
    assert "private other owner" not in serialized
```

- [ ] **Step 3: Write failing timeout fallback test**

Append to `tests/test_study_agent_runtime.py`:

```python
class SlowExpertRunner:
    async def run(self, *, gate, category, chunks, concept_ids):
        import asyncio

        await asyncio.sleep(0.2)
        raise AssertionError("slow expert runner should be cancelled by runtime timeout")


@pytest.mark.asyncio
async def test_runtime_expert_timeout_records_safe_fallback_metadata():
    Session = _session_factory()
    _insert_ready_document_with_artifact(Session, content="Chapter 2 and Chapter 4 connect derivatives and integrals.")
    _insert_persisted_chunk_with_concept(Session, content="Chapter 2 and Chapter 4 connect derivatives and integrals.")
    runtime = _advanced_runtime(Session, timeout_seconds=0.01)
    runtime.expert_runner = SlowExpertRunner()

    result = await runtime.run(
        {
            "query": "Compare 第2章 and 第4章 for an exam synthesis.",
            "target": "answer",
            "document_ids": ["doc-study"],
            "budget": "high",
            "authenticated_user_id": "user-1",
            "request_id": "req-expert-timeout",
        }
    )

    assert result.audit_metadata["expert"] == {
        "enabled": True,
        "branch_count": 1,
        "timeout_count": 1,
        "failure_count": 0,
        "fallback_reason": "branch_timeout",
        "branch_statuses": {"retrieval_expert": "timeout"},
    }
    assert result.draft.content
```

- [ ] **Step 4: Run failing runtime tests**

Run:

```bash
pytest tests/test_study_agent_experts.py::test_deterministic_expert_runner_returns_safe_branch_summary tests/test_study_agent_runtime.py::test_runtime_runs_expert_branches_for_eligible_synthesis_request -q
```

Expected: FAIL because runner/runtime integration is missing.

- [ ] **Step 5: Implement branch runner and summary**

Extend `src/services/study_agent_experts.py`:

```python
from src.services.rag_service import Chunk


@dataclass(frozen=True)
class ExpertExecutionSummary:
    enabled: bool
    branch_results: tuple[ExpertBranchResult, ...] = ()
    fallback_reason: str | None = None

    def to_safe_dict(self) -> dict[str, Any]:
        branch_statuses = {
            result.branch_name: result.status
            for result in self.branch_results
            if result.branch_name in SAFE_BRANCH_NAMES and result.status in SAFE_BRANCH_STATUSES
        }
        timeout_count = sum(1 for result in self.branch_results if result.status == "timeout")
        failure_count = sum(1 for result in self.branch_results if result.status == "failed")
        safe: dict[str, Any] = {
            "enabled": self.enabled,
            "branch_count": len(self.branch_results),
            "timeout_count": timeout_count,
            "failure_count": failure_count,
        }
        if self.fallback_reason in SAFE_REASON_CODES:
            safe["fallback_reason"] = self.fallback_reason
        if branch_statuses:
            safe["branch_statuses"] = branch_statuses
        return safe_expert_metadata(safe) or {}


class DeterministicExpertBranchRunner:
    async def run(
        self,
        *,
        gate: ExpertGateDecision,
        category: str,
        chunks: tuple[Chunk, ...],
        concept_ids: tuple[str, ...],
    ) -> ExpertExecutionSummary:
        if not gate.enabled:
            return ExpertExecutionSummary(enabled=False, fallback_reason=gate.safe_reason_code)

        results: list[ExpertBranchResult] = [
            ExpertBranchResult(
                branch_name="retrieval_expert",
                status="passed",
                source_ids=tuple(chunk.source for chunk in chunks[:5]),
                confidence=_average_chunk_score(chunks),
                metrics={"source_count": len({chunk.source for chunk in chunks if chunk.source}), "chunk_count": len(chunks)},
            )
        ]
        if concept_ids:
            results.append(
                ExpertBranchResult(
                    branch_name="graph_expert",
                    status="passed",
                    concept_ids=concept_ids[:5],
                    confidence=0.7,
                    metrics={"concept_count": len(concept_ids[:5]), "graph_hop_count": 1},
                )
            )
        else:
            results.append(
                ExpertBranchResult(
                    branch_name="graph_expert",
                    status="skipped",
                    safe_reason_code="graph_unavailable",
                )
            )
        if category == "question_generation":
            results.append(
                ExpertBranchResult(branch_name="question_expert", status="passed", confidence=0.7)
            )
        else:
            results.append(
                ExpertBranchResult(branch_name="synthesis_expert", status="passed", confidence=0.7)
            )
        return ExpertExecutionSummary(enabled=True, branch_results=tuple(results[: gate.max_branches]))


def _average_chunk_score(chunks: tuple[Chunk, ...]) -> float:
    if not chunks:
        return 0.0
    return round(sum(max(0.0, chunk.score) for chunk in chunks) / len(chunks), 6)
```

- [ ] **Step 6: Wire runtime expert execution**

Modify `src/services/study_agent_runtime.py` imports:

```python
import asyncio

from src.services.rag_service import Chunk, RAGService
from src.services.study_agent_experts import (
    DeterministicExpertBranchRunner,
    ExpertBranchResult,
    ExpertCollaborationConfig,
    ExpertEligibilityService,
    ExpertExecutionSummary,
)
```

Add constructor arguments:

```python
        expert_config: ExpertCollaborationConfig | None = None,
        expert_runner: Any | None = None,
```

Set fields:

```python
        self.expert_config = expert_config or ExpertCollaborationConfig()
        self.expert_runner = expert_runner or DeterministicExpertBranchRunner()
```

After `safe_skill = skill.to_safe_dict()` and before `orchestrator_payload`:

```python
        expert_chunks = tuple(
            Chunk(
                content=str(chunk.get("content", "")),
                source=str(chunk.get("source", "")),
                metadata=dict(chunk.get("metadata") or {}),
                score=0.0,
            )
            for chunk in chunks
            if isinstance(chunk, dict)
        )
        expert_gate = ExpertEligibilityService(self.expert_config).decide(
            policy_decision=policy_decision,
            skill=skill,
            index_statuses=index_statuses,
        )
        expert_concept_ids = tuple(
            str(chunk.get("metadata", {}).get("concept_id") or "")
            for chunk in chunks
            if isinstance(chunk, dict)
            and str(chunk.get("metadata", {}).get("concept_id") or "")
        )
        if expert_gate.enabled:
            try:
                expert_summary = await asyncio.wait_for(
                    self.expert_runner.run(
                        gate=expert_gate,
                        category=policy_decision.category,
                        chunks=expert_chunks,
                        concept_ids=expert_concept_ids,
                    ),
                    timeout=expert_gate.branch_timeout_seconds,
                )
            except asyncio.TimeoutError:
                expert_summary = ExpertExecutionSummary(
                    enabled=True,
                    branch_results=(
                        ExpertBranchResult(
                            branch_name="retrieval_expert",
                            status="timeout",
                            safe_reason_code="branch_timeout",
                        ),
                    ),
                    fallback_reason="branch_timeout",
                )
            except Exception:
                expert_summary = ExpertExecutionSummary(
                    enabled=True,
                    branch_results=(
                        ExpertBranchResult(
                            branch_name="retrieval_expert",
                            status="failed",
                            safe_reason_code="branch_error",
                        ),
                    ),
                    fallback_reason="branch_error",
                )
        else:
            expert_summary = ExpertExecutionSummary(
                enabled=False,
                fallback_reason=expert_gate.safe_reason_code,
            )
        safe_expert = expert_summary.to_safe_dict()
        add_stage(
            WorkflowStageName.EXPERT_GATE,
            status=(
                WorkflowStageStatus.PASSED
                if safe_expert.get("enabled") is True
                else WorkflowStageStatus.SKIPPED
            ),
            output_summary={
                "expert_enabled": safe_expert.get("enabled", False),
                "expert_branch_count": safe_expert.get("branch_count", 0),
                "expert_timeout_count": safe_expert.get("timeout_count", 0),
                "expert_failure_count": safe_expert.get("failure_count", 0),
                "expert_fallback_reason": safe_expert.get("fallback_reason"),
            },
        )
```

Add to `orchestrator_payload`:

```python
            "expert": safe_expert,
```

After result audit metadata:

```python
        result.audit_metadata["expert"] = safe_expert
```

- [ ] **Step 7: Run runtime expert tests**

Run:

```bash
pytest tests/test_study_agent_experts.py tests/test_study_agent_runtime.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit runtime expert execution**

Run:

```bash
git add src/services/study_agent_experts.py src/services/study_agent_runtime.py tests/test_study_agent_experts.py tests/test_study_agent_runtime.py
git commit -m "feat: gate expert collaboration in study runtime"
```

- [ ] **Step 9: Required reviews**

Run Task 3 Spec review and Quality/privacy review before starting Task 4.

---

## Task 4: Expert Metadata In Trace And API Responses

**Files:**
- Modify: `src/services/study_agent_trace.py`
- Modify: `src/api/routes/study_agent.py`
- Test: `tests/test_study_agent_traces.py`
- Test: `tests/test_study_agent_api.py`

- [ ] **Step 1: Write failing trace persistence test**

Append to `tests/test_study_agent_traces.py`:

```python
def test_record_success_persists_safe_expert_metadata():
    SessionFactory = _session_factory()
    service = StudyAgentTraceService(SessionFactory)
    result = _study_result()
    result.audit_metadata["expert"] = {
        "enabled": True,
        "branch_count": 2,
        "timeout_count": 1,
        "failure_count": 0,
        "fallback_reason": "branch_timeout",
        "branch_statuses": {"retrieval_expert": "passed", "graph_expert": "timeout"},
        "query": "raw private query",
        "token": "sk-secret-token",
    }

    payload = service.record_success(
        owner_id="owner-1",
        request_id="req-expert-trace",
        result=result,
        latency_ms=10,
        index_statuses={},
    )

    assert payload["expert"] == {
        "enabled": True,
        "branch_count": 2,
        "timeout_count": 1,
        "failure_count": 0,
        "fallback_reason": "branch_timeout",
        "branch_statuses": {"retrieval_expert": "passed", "graph_expert": "timeout"},
    }
    assert "raw private query" not in str(payload)
    assert "sk-secret-token" not in str(payload)
```

- [ ] **Step 2: Write failing unpersisted API expert sanitizer test**

Append to `tests/test_study_agent_api.py`:

```python
@dataclass
class SensitiveExpertStudyAgentOrchestrator:
    async def run(self, payload: dict) -> StudyAgentResult:
        request = StudyRequest(query=payload["query"], target=StudyTarget.ANSWER)
        return StudyAgentResult(
            request=request,
            plan=StudyPlan(mode=RetrievalMode.SIMPLE, reason="test", steps=("retrieve_chunks",), estimated_cost="low"),
            evidence=EvidenceBundle(
                mode=RetrievalMode.SIMPLE,
                chunks=(Chunk(content="raw chunk text", source="document:doc:chunk:0"),),
                sources=("document:doc:chunk:0",),
                concept_ids=("concept",),
                confidence=0.8,
                reason="test",
            ),
            draft=StudyDraft(target=StudyTarget.ANSWER, content="generated answer", citations=("document:doc:chunk:0",), used_chunk_count=1),
            verification=StudyVerification(passed=True, needs_review=False, confidence=0.8, issues=(), source_recall=1.0, answer_term_recall=1.0),
            audit_metadata={
                "mode": "simple_rag",
                "target": "answer",
                "needs_review": False,
                "source_count": 1,
                "chunk_count": 1,
                "expert": {
                    "enabled": True,
                    "branch_count": 1,
                    "timeout_count": 0,
                    "failure_count": 0,
                    "branch_statuses": {"retrieval_expert": "passed"},
                    "query": "raw private query",
                    "chunk_content": "raw chunk text",
                    "prompt": "hidden prompt",
                    "token": "sk-secret-token",
                },
            },
        )


def test_study_agent_query_response_includes_safe_expert_payload_only(tmp_path: Path):
    Session = _session_factory()
    app = create_app(
        session_factory=Session,
        study_agent_orchestrator=SensitiveExpertStudyAgentOrchestrator(),
        secret_key="test-secret",
        allow_dev_user_header=False,
    )
    client = TestClient(app)
    headers = _login(client)

    response = client.post(
        "/api/study-agent/query",
        json={"query": "raw private query"},
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["expert"] == {
        "enabled": True,
        "branch_count": 1,
        "timeout_count": 0,
        "failure_count": 0,
        "branch_statuses": {"retrieval_expert": "passed"},
    }
    serialized = response.text
    assert "hidden prompt" not in serialized
    assert "sk-secret-token" not in serialized
    assert "chunk_content" not in serialized
```

- [ ] **Step 3: Run failing trace/API tests**

Run:

```bash
pytest tests/test_study_agent_traces.py::test_record_success_persists_safe_expert_metadata tests/test_study_agent_api.py::test_study_agent_query_response_includes_safe_expert_payload_only -q
```

Expected: FAIL because API response does not expose safe expert payload yet.

- [ ] **Step 4: Add expert to API response and unpersisted trace**

Modify `src/api/routes/study_agent.py` imports:

```python
from src.services.study_agent_experts import safe_expert_metadata
```

In `query_study_agent()` after skill:

```python
    expert = safe_expert_metadata(audit_metadata.get("expert"))
    if expert is not None:
        response_payload["expert"] = expert
```

In `_trace_payload_without_persistence()` after workflow:

```python
    expert = safe_expert_metadata(audit_metadata.get("expert"))
    if expert is not None:
        trace_payload["expert"] = expert
```

- [ ] **Step 5: Run trace/API tests**

Run:

```bash
pytest tests/test_study_agent_traces.py tests/test_study_agent_api.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit trace/API expert metadata**

Run:

```bash
git add src/services/study_agent_trace.py src/api/routes/study_agent.py tests/test_study_agent_traces.py tests/test_study_agent_api.py
git commit -m "feat: expose safe expert diagnostics"
```

- [ ] **Step 7: Required reviews**

Run Task 4 Spec review and Quality/privacy review before starting Task 5.

---

## Task 5: Owner-Scoped Skill Performance Aggregation

**Files:**
- Create: `src/services/study_agent_skill_performance.py`
- Modify: `src/api/routes/study_agent.py`
- Test: `tests/test_study_agent_skill_performance.py`
- Test: `tests/test_study_agent_api.py`

- [ ] **Step 1: Write failing performance service tests**

Create `tests/test_study_agent_skill_performance.py`:

```python
from __future__ import annotations

from sqlalchemy import create_engine

from src.db import Base, StudyAgentTraceRecord, create_session_factory
from src.services.study_agent_skill_performance import StudyAgentSkillPerformanceService


def _session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


def _trace(
    *,
    trace_id: str,
    owner_id: str,
    skill_name: str = "concept_explanation",
    skill_version: str = "v1",
    needs_review: bool = False,
    fallback_reason: str | None = None,
    confidence: float = 0.8,
    source_recall: float = 1.0,
    answer_term_recall: float = 1.0,
    expert=None,
    review_reason: str | None = None,
):
    workflow_stage = {
        "stage": "review_gate",
        "status": "needs_review" if needs_review else "passed",
        "duration_ms": 0,
        "input_summary": {},
        "output_summary": {"needs_review": needs_review, "review_reason": review_reason},
        "error_code": None,
        "review_reason": review_reason,
    }
    return StudyAgentTraceRecord(
        id=trace_id,
        owner_id=owner_id,
        request_id=f"req-{trace_id}",
        query_hash=f"sha256:{trace_id}",
        target="answer",
        document_ids=["doc-1"],
        selected_mode="simple_rag",
        route_reason="safe reason",
        estimated_cost="low",
        fallback_chain=[],
        chunk_source="persisted",
        fallback_reason=fallback_reason,
        source_count=1,
        used_chunk_count=1,
        confidence=confidence,
        source_recall=source_recall,
        answer_term_recall=answer_term_recall,
        needs_review=needs_review,
        latency_ms=10,
        trace_metadata={
            "skill": {
                "skill_name": skill_name,
                "skill_version": skill_version,
            },
            "workflow": {
                "workflow_id": "workflow-0123456789abcdef0123456789abcdef",
                "status": "needs_review" if needs_review else "completed",
                "current_stage": "trace",
                "needs_review": needs_review,
                "stage_count": 1,
                "stages": [workflow_stage],
            },
            "expert": expert or {
                "enabled": False,
                "branch_count": 0,
                "timeout_count": 0,
                "failure_count": 0,
            },
        },
    )


def test_skill_performance_summary_is_owner_scoped_and_aggregate_only():
    Session = _session_factory()
    with Session() as session:
        session.add_all(
            [
                _trace(trace_id="trace-1", owner_id="owner-1", needs_review=False, confidence=0.8),
                _trace(
                    trace_id="trace-2",
                    owner_id="owner-1",
                    needs_review=True,
                    fallback_reason="persisted_chunks_missing",
                    confidence=0.4,
                    source_recall=0.5,
                    answer_term_recall=0.25,
                    expert={
                        "enabled": True,
                        "branch_count": 2,
                        "timeout_count": 1,
                        "failure_count": 0,
                        "fallback_reason": "branch_timeout",
                    },
                    review_reason="low_confidence",
                ),
                _trace(trace_id="trace-3", owner_id="owner-2", skill_name="practice_question", needs_review=True),
            ]
        )
        session.commit()

    summary = StudyAgentSkillPerformanceService(Session).summary(owner_id="owner-1")

    assert summary == {
        "skills": [
            {
                "skill_name": "concept_explanation",
                "skill_version": "v1",
                "run_count": 2,
                "needs_review_count": 1,
                "review_rate": 0.5,
                "fallback_count": 1,
                "fallback_rate": 0.5,
                "expert_run_count": 1,
                "expert_timeout_count": 1,
                "average_confidence": 0.6,
                "average_source_recall": 0.75,
                "average_answer_term_recall": 0.625,
                "review_reason_counts": {"low_confidence": 1},
            }
        ]
    }
    serialized = str(summary).lower()
    assert "owner-2" not in serialized
    assert "trace-3" not in serialized


def test_skill_performance_summary_can_filter_skill_version():
    Session = _session_factory()
    with Session() as session:
        session.add_all(
            [
                _trace(trace_id="trace-1", owner_id="owner-1", skill_name="concept_explanation", skill_version="v1"),
                _trace(trace_id="trace-2", owner_id="owner-1", skill_name="practice_question", skill_version="v1"),
            ]
        )
        session.commit()

    summary = StudyAgentSkillPerformanceService(Session).summary(
        owner_id="owner-1",
        skill_name="practice_question",
        skill_version="v1",
    )

    assert [item["skill_name"] for item in summary["skills"]] == ["practice_question"]
```

- [ ] **Step 2: Run failing performance tests**

Run:

```bash
pytest tests/test_study_agent_skill_performance.py -q
```

Expected: FAIL because `src.services.study_agent_skill_performance` is missing.

- [ ] **Step 3: Implement performance service**

Create `src/services/study_agent_skill_performance.py`:

```python
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import select

from src.db import StudyAgentTraceRecord
from src.services.study_agent_trace import safe_skill_metadata
from src.services.study_agent_experts import safe_expert_metadata
from src.services.study_agent_workflow import sanitize_workflow_payload


class StudyAgentSkillPerformanceService:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    def summary(
        self,
        *,
        owner_id: str,
        skill_name: str | None = None,
        skill_version: str | None = None,
    ) -> dict[str, Any]:
        with self.session_factory() as session:
            records = list(
                session.scalars(
                    select(StudyAgentTraceRecord).where(
                        StudyAgentTraceRecord.owner_id == owner_id
                    )
                )
            )
        buckets: dict[tuple[str, str], list[StudyAgentTraceRecord]] = defaultdict(list)
        for record in records:
            skill = safe_skill_metadata((record.trace_metadata or {}).get("skill"))
            if skill is None:
                continue
            name = skill.get("skill_name")
            version = skill.get("skill_version")
            if not isinstance(name, str) or not isinstance(version, str):
                continue
            if skill_name is not None and name != skill_name:
                continue
            if skill_version is not None and version != skill_version:
                continue
            buckets[(name, version)].append(record)

        return {
            "skills": [
                _summarize_bucket(name, version, bucket)
                for (name, version), bucket in sorted(buckets.items())
            ]
        }


def _summarize_bucket(
    skill_name: str,
    skill_version: str,
    records: list[StudyAgentTraceRecord],
) -> dict[str, Any]:
    run_count = len(records)
    needs_review_count = sum(1 for record in records if record.needs_review)
    fallback_count = sum(1 for record in records if record.fallback_reason)
    expert_run_count = 0
    expert_timeout_count = 0
    review_reasons: Counter[str] = Counter()
    for record in records:
        expert = safe_expert_metadata((record.trace_metadata or {}).get("expert")) or {}
        if expert.get("enabled") is True:
            expert_run_count += 1
        expert_timeout_count += int(expert.get("timeout_count") or 0)
        workflow = sanitize_workflow_payload((record.trace_metadata or {}).get("workflow"))
        if workflow is not None:
            for stage in workflow.get("stages", []):
                reason = stage.get("review_reason") or stage.get("output_summary", {}).get("review_reason")
                if isinstance(reason, str):
                    review_reasons[reason] += 1

    return {
        "skill_name": skill_name,
        "skill_version": skill_version,
        "run_count": run_count,
        "needs_review_count": needs_review_count,
        "review_rate": _rate(needs_review_count, run_count),
        "fallback_count": fallback_count,
        "fallback_rate": _rate(fallback_count, run_count),
        "expert_run_count": expert_run_count,
        "expert_timeout_count": expert_timeout_count,
        "average_confidence": _avg(record.confidence for record in records),
        "average_source_recall": _avg(record.source_recall for record in records),
        "average_answer_term_recall": _avg(record.answer_term_recall for record in records),
        "review_reason_counts": dict(sorted(review_reasons.items())),
    }


def _rate(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(count / total, 6)


def _avg(values) -> float:
    items = [float(value) for value in values if value is not None]
    if not items:
        return 0.0
    return round(sum(items) / len(items), 6)
```

- [ ] **Step 4: Write API endpoint tests**

Append to `tests/test_study_agent_api.py`:

```python
def test_skill_performance_endpoint_is_owner_scoped(tmp_path: Path):
    client, _orchestrator, Session, _document_service = _client(tmp_path)
    headers = _login(client)
    with Session() as session:
        session.add_all(
            [
                StudyAgentTraceRecord(
                    id="trace-owner",
                    owner_id="user-1",
                    request_id="req-owner",
                    query_hash="sha256:owner",
                    target="answer",
                    document_ids=["doc-api"],
                    selected_mode="simple_rag",
                    route_reason="safe",
                    estimated_cost="low",
                    fallback_chain=[],
                    chunk_source="persisted",
                    fallback_reason=None,
                    source_count=1,
                    used_chunk_count=1,
                    confidence=0.8,
                    source_recall=1.0,
                    answer_term_recall=1.0,
                    needs_review=False,
                    latency_ms=10,
                    trace_metadata={"skill": {"skill_name": "concept_explanation", "skill_version": "v1"}},
                ),
                StudyAgentTraceRecord(
                    id="trace-other",
                    owner_id="user-2",
                    request_id="req-other",
                    query_hash="sha256:other",
                    target="answer",
                    document_ids=["doc-other"],
                    selected_mode="simple_rag",
                    route_reason="safe",
                    estimated_cost="low",
                    fallback_chain=[],
                    chunk_source="persisted",
                    fallback_reason=None,
                    source_count=1,
                    used_chunk_count=1,
                    confidence=0.1,
                    source_recall=0.1,
                    answer_term_recall=0.1,
                    needs_review=True,
                    latency_ms=10,
                    trace_metadata={"skill": {"skill_name": "practice_question", "skill_version": "v1"}},
                ),
            ]
        )
        session.commit()

    response = client.get("/api/study-agent/skills/performance", headers=headers)

    assert response.status_code == 200
    assert response.json()["skills"][0]["skill_name"] == "concept_explanation"
    serialized = json.dumps(response.json(), ensure_ascii=False)
    assert "user-2" not in serialized
    assert "trace-other" not in serialized
```

Add missing import near the top of `tests/test_study_agent_api.py`:

```python
from src.db import StudyAgentTraceRecord
```

- [ ] **Step 5: Add API endpoint**

Modify `src/api/routes/study_agent.py` imports:

```python
from src.services.study_agent_skill_performance import StudyAgentSkillPerformanceService
```

Add route after `/skills`:

```python
@router.get("/skills/performance")
def get_study_agent_skill_performance(
    request: Request,
    skill_name: str | None = None,
    skill_version: str | None = None,
) -> dict[str, Any]:
    context = get_user_context(request)
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        return {"skills": []}
    return StudyAgentSkillPerformanceService(
        _non_expiring_session_factory(session_factory)
    ).summary(
        owner_id=context.user_id,
        skill_name=skill_name,
        skill_version=skill_version,
    )
```

- [ ] **Step 6: Run performance tests**

Run:

```bash
pytest tests/test_study_agent_skill_performance.py tests/test_study_agent_api.py::test_skill_performance_endpoint_is_owner_scoped -q
```

Expected: PASS.

- [ ] **Step 7: Commit performance service**

Run:

```bash
git add src/services/study_agent_skill_performance.py src/api/routes/study_agent.py tests/test_study_agent_skill_performance.py tests/test_study_agent_api.py
git commit -m "feat: summarize study skill performance"
```

- [ ] **Step 8: Required reviews**

Run Task 5 Spec review and Quality/privacy review before starting Task 6.

---

## Task 6: Frontend Compact Expert And Performance Diagnostics

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/components/StudyAgentPanel.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Add frontend API types**

Modify `frontend/src/api.ts`.

Add:

```ts
export interface StudyAgentExpertDiagnostic {
  enabled?: boolean | null;
  branch_count?: number | null;
  timeout_count?: number | null;
  failure_count?: number | null;
  fallback_reason?: string | null;
  branch_statuses?: Record<string, string>;
}

export interface StudyAgentSkillPerformanceItem {
  skill_name: string;
  skill_version: string;
  run_count: number;
  needs_review_count: number;
  review_rate: number;
  fallback_count: number;
  fallback_rate: number;
  expert_run_count: number;
  expert_timeout_count: number;
  average_confidence: number;
  average_source_recall: number;
  average_answer_term_recall: number;
  review_reason_counts: Record<string, number>;
}

export interface StudyAgentSkillPerformanceSummary {
  skills: StudyAgentSkillPerformanceItem[];
}
```

Add `expert?: StudyAgentExpertDiagnostic | null;` to `StudyAgentTraceSummary` and `StudyAgentResult`.

Add:

```ts
export async function getStudyAgentSkillPerformance(
  apiClient: ApiClient,
  skillName?: string,
  skillVersion?: string,
): Promise<StudyAgentSkillPerformanceSummary> {
  const params = new URLSearchParams();
  if (skillName) params.set("skill_name", skillName);
  if (skillVersion) params.set("skill_version", skillVersion);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const response = await fetch(`${API_BASE}/api/study-agent/skills/performance${suffix}`, {
    headers: apiClient.headers(),
  });
  return parseJson<StudyAgentSkillPerformanceSummary>(
    response,
    "Failed to load Study Agent skill performance",
  );
}
```

- [ ] **Step 2: Add compact components**

Modify `frontend/src/components/StudyAgentPanel.tsx`.

Extend the existing API import:

```tsx
import {
  ApiClient,
  ApiError,
  type ApiDocument,
  type StudyAgentQueryPayload,
  type StudyAgentResult,
  type StudyAgentSkillPerformanceItem,
  type StudyBudget,
  type StudyRetrievalMode,
  type StudyTarget,
  getStudyAgentSkillPerformance,
  queryStudyAgent,
} from "../api";
```

Add components near `SkillStatus`:

```tsx
function ExpertStatus({ expert }: { expert?: StudyAgentResult["expert"] }) {
  if (!expert) return null;
  return (
    <div className="study-agent-expert" aria-label="Study Agent expert diagnostics">
      <span>
        <strong>Experts</strong> {expert.enabled ? "enabled" : "skipped"}
      </span>
      <span>
        <strong>Branches</strong> {expert.branch_count ?? 0}
      </span>
      <span>
        <strong>Timeouts</strong> {expert.timeout_count ?? 0}
      </span>
      {expert.fallback_reason ? (
        <span className="study-agent-policy-warning">{expert.fallback_reason}</span>
      ) : null}
    </div>
  );
}

function SkillPerformanceStatus({
  item,
}: {
  item?: StudyAgentSkillPerformanceItem | null;
}) {
  if (!item) return null;
  return (
    <div className="study-agent-skill-performance" aria-label="Study Agent skill performance">
      <span>
        <strong>Review rate</strong> {Math.round(item.review_rate * 100)}%
      </span>
      <span>
        <strong>Fallback rate</strong> {Math.round(item.fallback_rate * 100)}%
      </span>
      <span>
        <strong>Expert runs</strong> {item.expert_run_count}
      </span>
    </div>
  );
}
```

Add state in `StudyAgentPanel`:

```tsx
  const [skillPerformance, setSkillPerformance] = useState<StudyAgentSkillPerformanceItem | null>(null);
```

After a successful query, fetch performance using selected skill:

```tsx
      const data = await queryStudyAgent(apiClient, payload);
      setResult(data);
      const skill = data.skill ?? data.trace?.skill;
      if (skill?.skill_name) {
        const performance = await getStudyAgentSkillPerformance(
          apiClient,
          skill.skill_name,
          skill.skill_version ?? undefined,
        );
        setSkillPerformance(performance.skills[0] ?? null);
      } else {
        setSkillPerformance(null);
      }
```

Replace the current `setResult(await queryStudyAgent(apiClient, payload));` line with the block above. Keep the existing `ApiError` 401 handling around the whole request path so authentication expiry is still routed through `onAuthExpired()`.

Render after `SkillStatus`:

```tsx
          <ExpertStatus expert={result.expert ?? result.trace?.expert} />
          <SkillPerformanceStatus item={skillPerformance} />
```

- [ ] **Step 3: Add compact CSS**

Modify `frontend/src/styles.css`:

```css
.study-agent-expert,
.study-agent-skill-performance {
  align-items: center;
  background: #f8fafc;
  border: 1px solid #dbe3ef;
  border-radius: 6px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  padding: 8px 10px;
}

.study-agent-expert span,
.study-agent-skill-performance span {
  color: #334155;
  font-size: 0.85rem;
  line-height: 1.3;
}

.study-agent-expert strong,
.study-agent-skill-performance strong {
  color: #0f172a;
  font-weight: 700;
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
git commit -m "feat: show expert and skill performance diagnostics"
```

- [ ] **Step 6: Required reviews**

Run Task 6 Spec review and Quality/privacy review before starting Task 7.

---

## Task 7: Documentation Sync And Final Verification

**Files:**
- Modify: `README.md`
- Modify: `SPEC.md`
- Modify: `docs/superpowers/specs/2026-07-07-bounded-expert-collaboration-memory-evaluation-design.md` only if implementation forces a clarification.

- [ ] **Step 1: Update README status**

Add to `README.md` under MVP-9 status:

```markdown
Bounded expert collaboration can now run only for policy-approved synthesis and question-generation paths. Expert diagnostics and skill performance summaries remain compact and privacy-safe; they expose labels, counts, rates, and reason codes rather than raw query text, generated content, prompts, or source snippets.
```

- [ ] **Step 2: Update SPEC status**

Add to `SPEC.md` current MVP-9 implementation status:

```markdown
- Bounded expert collaboration and memory-guided evaluation: eligible Study Agent paths can run optional expert branches behind route policy/readiness/index/budget gates, and skill performance summaries aggregate owner-scoped safe trace/review metadata without automatic prompt evolution.
```

- [ ] **Step 3: Run targeted backend verification**

Run:

```bash
pytest tests/test_study_agent_experts.py tests/test_study_agent_skill_performance.py tests/test_study_agent_runtime.py tests/test_study_agent_workflow.py tests/test_study_agent_traces.py tests/test_study_agent_api.py tests/test_rag_route_policy.py tests/test_study_agent_skills.py tests/test_study_agent_memory.py tests/test_study_agent_review_tasks.py -q
```

Expected: PASS.

- [ ] **Step 4: Run frontend build**

Run:

```bash
cd frontend && npm run build
```

Expected: PASS.

- [ ] **Step 5: Confirm no generated artifacts and clean diff**

Run:

```bash
find docs -maxdepth 3 -path 'docs/evaluation/*' -type f -print
git diff --check
git status --short --branch
```

Expected: no `docs/evaluation` output, no whitespace errors, only intended docs changes before commit.

- [ ] **Step 6: Commit docs sync**

Run:

```bash
git add README.md SPEC.md docs/superpowers/specs/2026-07-07-bounded-expert-collaboration-memory-evaluation-design.md
git commit -m "docs: sync expert memory evaluation status"
```

- [ ] **Step 7: Required reviews**

Run Task 7 Spec review and Quality/privacy review before marking implementation complete.

## Final Verification Before Completion

After all tasks and reviews pass, run:

```bash
pytest tests/test_study_agent_experts.py tests/test_study_agent_skill_performance.py tests/test_study_agent_runtime.py tests/test_study_agent_workflow.py tests/test_study_agent_traces.py tests/test_study_agent_api.py tests/test_rag_route_policy.py tests/test_rag_router.py tests/test_graph_rag.py tests/test_agentic_rag.py tests/test_api_permissions_audit.py tests/test_rag_evaluation.py tests/test_rag_mode_comparison.py tests/test_study_agent_memory.py tests/test_study_agent_skills.py tests/test_study_agent_review_tasks.py -q
cd frontend && npm run build
git diff --check
git status --short --branch
```

Expected:

- Backend targeted suites PASS.
- Frontend build PASS.
- `git diff --check` has no output.
- Worktree is clean after final commit.

## Execution Handoff

Plan complete. Recommended execution mode is **Subagent-Driven** because each task has a clear file boundary and requires mandatory spec/quality review after every task.
