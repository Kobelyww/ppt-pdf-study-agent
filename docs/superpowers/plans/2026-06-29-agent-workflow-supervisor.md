# Agent Workflow Supervisor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an explicit, privacy-safe Study Agent workflow supervisor with stage timelines, workflow diagnostics, trace persistence, and compact frontend display.

**Architecture:** Introduce a focused `StudyAgentWorkflowSupervisor` layer that wraps the existing runtime/orchestrator responsibilities without replacing retrieval, generation, verification, auth, or storage internals. Workflow stage summaries are allowlisted and attached to `StudyAgentResult.audit_metadata`, then exposed through API/trace/frontend as compact diagnostics. Development follows the existing task-by-task subagent workflow with spec and quality reviews after each task.

**Tech Stack:** FastAPI, SQLAlchemy ORM JSON metadata, deterministic Python services/dataclasses, pytest/pytest-asyncio, Vite/React/TypeScript frontend, existing Study Agent trace/audit infrastructure.

---

## Scope And Product Boundaries

This plan implements:

- `docs/superpowers/specs/2026-06-29-agent-workflow-supervisor-design.md`

It includes:

- Workflow status and stage dataclasses.
- Safe stage summary sanitization.
- Review Gate v1 reason codes.
- Runtime workflow payload on Study Agent query results.
- Safe trace persistence of workflow timeline.
- Workflow detail API backed by existing trace records.
- Compact frontend workflow timeline.
- Deterministic tests for completed, fallback, failed, needs-review, owner isolation, and privacy behavior.

It excludes:

- Open-ended autonomous agent loops.
- Async cancellation/resume.
- New graph database or workflow engine.
- Prompt mutation, DSPy/GEPA, or self-evolution.
- Large workflow dashboard.
- Admin cross-user workflow search.
- Automatic persisted review task creation in v1.

## File Structure

- Create `src/services/study_agent_workflow.py`: workflow enums, stage/result dataclasses, safe summary sanitizer, review gate, supervisor result helpers.
- Modify `src/services/study_agent.py`: keep `StudyAgentResult` generation/retrieval contracts unchanged and attach workflow diagnostics only through `audit_metadata["workflow"]`.
- Modify `src/services/study_agent_runtime.py`: create stage timeline around existing runtime steps and attach safe workflow payload to `audit_metadata["workflow"]`.
- Modify `src/services/study_agent_trace.py`: persist and return safe workflow payload from trace metadata.
- Modify `src/api/routes/study_agent.py`: return top-level `workflow`, add `GET /api/study-agent/workflows/{workflow_id}`.
- Modify `frontend/src/api.ts`: add workflow diagnostic types to `StudyAgentResult`.
- Modify `frontend/src/components/StudyAgentPanel.tsx`: render compact workflow status and stages.
- Modify `frontend/src/styles.css`: add compact workflow timeline styles.
- Create `tests/test_study_agent_workflow.py`: unit tests for contracts, sanitizer, aggregate status, review gate.
- Modify `tests/test_study_agent_runtime.py`: runtime workflow timeline tests.
- Modify `tests/test_study_agent_traces.py`: trace persistence/privacy tests.
- Modify `tests/test_study_agent_api.py`: API workflow payload and owner isolation tests.

## Shared Review Rule

After each task, run both reviews before moving to the next task:

- **Spec review:** compare the task diff against `docs/superpowers/specs/2026-06-29-agent-workflow-supervisor-design.md`. Confirm the task implements the intended slice and does not add autonomous loops, async cancellation/resume, workflow engine schema, review task creation, admin workflow search, prompt mutation, self-evolution, or dashboard work.
- **Quality review:** inspect deterministic behavior, privacy allowlists, owner isolation, fallback semantics, backward compatibility, compact API/frontend payloads, and test coverage.

Record both review outcomes in the task completion note.

## Task 1: Workflow Contracts, Safe Summaries, And Review Gate

**Files:**
- Create: `src/services/study_agent_workflow.py`
- Create/modify: `tests/test_study_agent_workflow.py`

- [ ] **Step 1: Write failing workflow contract tests**

Create `tests/test_study_agent_workflow.py` with:

```python
import json
from datetime import datetime, timezone

from src.services.rag_router import RetrievalMode
from src.services.rag_service import Chunk
from src.services.study_agent import (
    EvidenceBundle,
    StudyDraft,
    StudyTarget,
    StudyVerification,
)
from src.services.study_agent_workflow import (
    ReviewGate,
    WorkflowStageName,
    WorkflowStageResult,
    WorkflowStageStatus,
    WorkflowStatus,
    build_workflow_payload,
    sanitize_stage_summary,
    summarize_workflow_status,
)


def test_stage_result_serializes_safe_payload_without_private_values():
    started_at = datetime(2026, 6, 29, tzinfo=timezone.utc)
    completed_at = datetime(2026, 6, 29, 0, 0, 1, tzinfo=timezone.utc)

    stage = WorkflowStageResult(
        stage_name=WorkflowStageName.RETRIEVE,
        status=WorkflowStageStatus.PASSED,
        input_summary={
            "query": "什么是导数？",
            "document_count": 1,
            "mode": "simple_rag",
            "token": "secret-token",
        },
        output_summary={
            "chunk_count": 1,
            "source_count": 1,
            "chunk_content": "导数描述函数变化率。",
            "fallback_reason": None,
        },
        started_at=started_at,
        completed_at=completed_at,
        duration_ms=1000.0,
    )

    payload = stage.to_safe_dict()

    assert payload == {
        "stage": "retrieve",
        "status": "passed",
        "duration_ms": 1000.0,
        "input_summary": {"document_count": 1, "mode": "simple_rag"},
        "output_summary": {
            "chunk_count": 1,
            "source_count": 1,
            "fallback_reason": None,
        },
        "error_code": None,
        "review_reason": None,
    }
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "什么是导数" not in serialized
    assert "secret-token" not in serialized
    assert "导数描述" not in serialized


def test_sanitize_stage_summary_buckets_unknown_or_unsafe_values():
    summary = sanitize_stage_summary(
        {
            "stage": "retrieve",
            "mode": "raw query: 什么是导数？",
            "category": "definition",
            "fallback_reason": "persisted_chunks_missing",
            "review_reason": "missing_citations",
            "authorization": "Bearer secret-token",
            "chunk_count": "3",
            "needs_review": True,
        }
    )

    assert summary == {
        "stage": "retrieve",
        "mode": "unknown",
        "category": "definition",
        "fallback_reason": "persisted_chunks_missing",
        "review_reason": "missing_citations",
        "chunk_count": 3,
        "needs_review": True,
    }


def test_summarize_workflow_status_prefers_failed_then_needs_review_then_fallback():
    failed = WorkflowStageResult(
        stage_name=WorkflowStageName.RETRIEVE,
        status=WorkflowStageStatus.FAILED,
        input_summary={},
        output_summary={},
        error_code="document_evidence_missing",
    )
    needs_review = WorkflowStageResult(
        stage_name=WorkflowStageName.REVIEW_GATE,
        status=WorkflowStageStatus.NEEDS_REVIEW,
        input_summary={},
        output_summary={},
        review_reason="low_confidence",
    )
    fallback = WorkflowStageResult(
        stage_name=WorkflowStageName.RETRIEVE,
        status=WorkflowStageStatus.PASSED,
        input_summary={},
        output_summary={"fallback_reason": "persisted_chunks_missing"},
    )

    assert summarize_workflow_status([failed]) == WorkflowStatus.FAILED
    assert summarize_workflow_status([fallback, needs_review]) == WorkflowStatus.NEEDS_REVIEW
    assert summarize_workflow_status([fallback]) == WorkflowStatus.COMPLETED_WITH_FALLBACK


def test_review_gate_marks_missing_citations_and_synthesis_fallback_for_review():
    gate = ReviewGate(confidence_threshold=0.5)
    evidence = EvidenceBundle(
        mode=RetrievalMode.SIMPLE,
        chunks=(Chunk(content="private", source="doc:1"),),
        sources=("doc:1",),
        concept_ids=(),
        confidence=0.8,
        reason="simple",
        fallback_reason="agentic evidence unavailable",
    )
    draft = StudyDraft(
        target=StudyTarget.QUESTION,
        content="private generated answer",
        citations=(),
        used_chunk_count=1,
    )
    verification = StudyVerification(
        passed=False,
        needs_review=True,
        confidence=0.4,
        issues=("missing citations",),
        source_recall=0.0,
        answer_term_recall=1.0,
    )

    decision = gate.evaluate(
        target=StudyTarget.QUESTION,
        evidence=evidence,
        draft=draft,
        verification=verification,
        policy_status="allowed",
    )

    assert decision.status == WorkflowStageStatus.NEEDS_REVIEW
    assert decision.review_reasons == (
        "verification_failed",
        "low_confidence",
        "missing_citations",
        "target_used_fallback_evidence",
    )


def test_build_workflow_payload_uses_safe_stage_payloads():
    stage = WorkflowStageResult(
        stage_name=WorkflowStageName.INTAKE,
        status=WorkflowStageStatus.PASSED,
        input_summary={"query": "什么是导数？"},
        output_summary={"document_count": 1, "target": "answer"},
    )

    payload = build_workflow_payload(
        workflow_id="workflow-1",
        stages=[stage],
        needs_review=False,
    )

    assert payload["workflow_id"] == "workflow-1"
    assert payload["status"] == "completed"
    assert payload["current_stage"] == "intake"
    assert payload["needs_review"] is False
    assert payload["stage_count"] == 1
    assert payload["stages"][0]["output_summary"] == {
        "document_count": 1,
        "target": "answer",
    }
    assert "什么是导数" not in json.dumps(payload, ensure_ascii=False)
```

- [ ] **Step 2: Run workflow contract tests and confirm failure**

Run:

```bash
pytest tests/test_study_agent_workflow.py -q
```

Expected: FAIL because `src.services.study_agent_workflow` does not exist.

- [ ] **Step 3: Implement workflow contracts and sanitizer**

Create `src/services/study_agent_workflow.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from src.services.rag_router import RetrievalMode
from src.services.study_agent import (
    EvidenceBundle,
    StudyDraft,
    StudyTarget,
    StudyVerification,
)


class WorkflowStageName(str, Enum):
    INTAKE = "intake"
    PLAN = "plan"
    RETRIEVE = "retrieve"
    GENERATE = "generate"
    VERIFY = "verify"
    REVIEW_GATE = "review_gate"
    TRACE = "trace"


class WorkflowStageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    NEEDS_REVIEW = "needs_review"


class WorkflowStatus(str, Enum):
    COMPLETED = "completed"
    COMPLETED_WITH_FALLBACK = "completed_with_fallback"
    NEEDS_REVIEW = "needs_review"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


_SAFE_STRING_VALUES = {
    "stage": {stage.value for stage in WorkflowStageName},
    "status": {status.value for status in WorkflowStageStatus} | {status.value for status in WorkflowStatus},
    "target": {target.value for target in StudyTarget},
    "mode": {mode.value for mode in RetrievalMode},
    "router_mode": {mode.value for mode in RetrievalMode},
    "selected_mode": {mode.value for mode in RetrievalMode},
    "category": {
        "direct_lookup",
        "definition",
        "concept_relation",
        "learning_path",
        "multi_document_synthesis",
        "question_generation",
        "outline_fragment",
        "unknown",
    },
    "policy_status": {
        "allowed",
        "blocked_by_flag",
        "blocked_by_category",
        "blocked_by_readiness",
        "blocked_by_budget",
        "blocked_by_index_health",
        "not_applied",
    },
    "readiness_status": {"baseline", "candidate", "hold", "blocked", "insufficient_data"},
    "fallback_reason": {
        "persisted_chunks_missing",
        "persisted_chunks_stale",
        "persisted_chunks_incomplete",
        "no graph configured",
        "no graph seed matched",
        "low budget prevents agentic retrieval",
        "agentic step budget exhausted",
        "agentic evidence unavailable",
    },
    "review_reason": {
        "verification_failed",
        "low_confidence",
        "missing_citations",
        "empty_evidence",
        "policy_blocked_without_fallback",
        "target_used_fallback_evidence",
        "agentic_step_budget_exhausted",
    },
    "error_code": {
        "authentication_required",
        "document_evidence_missing",
        "unsupported_study_target",
        "unsupported_retrieval_mode",
        "forbidden_document",
        "bad_study_request",
    },
    "estimated_cost": {"low", "medium", "balanced", "high"},
    "chunk_source": {"persisted", "fallback"},
}

_SAFE_INT_KEYS = {
    "document_count",
    "chunk_count",
    "source_count",
    "concept_count",
    "issue_count",
    "stage_count",
    "used_chunk_count",
    "citation_count",
}
_SAFE_FLOAT_KEYS = {
    "confidence",
    "source_recall",
    "answer_term_recall",
    "duration_ms",
    "latency_ms",
}
_SAFE_BOOL_KEYS = {
    "needs_review",
    "fallback_used",
    "persisted_chunks_used",
    "experiment_enabled",
}


@dataclass(frozen=True)
class WorkflowStageResult:
    stage_name: WorkflowStageName
    status: WorkflowStageStatus
    input_summary: dict[str, Any]
    output_summary: dict[str, Any]
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    duration_ms: float | None = None
    error_code: str | None = None
    review_reason: str | None = None
    trace_metadata: dict[str, Any] = field(default_factory=dict)

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage_name.value,
            "status": self.status.value,
            "duration_ms": self.duration_ms,
            "input_summary": sanitize_stage_summary(self.input_summary),
            "output_summary": sanitize_stage_summary(self.output_summary),
            "error_code": _safe_string("error_code", self.error_code),
            "review_reason": _safe_string("review_reason", self.review_reason),
        }


@dataclass(frozen=True)
class ReviewGateDecision:
    status: WorkflowStageStatus
    review_reasons: tuple[str, ...] = ()


class ReviewGate:
    def __init__(self, confidence_threshold: float = 0.5) -> None:
        self.confidence_threshold = confidence_threshold

    def evaluate(
        self,
        *,
        target: StudyTarget,
        evidence: EvidenceBundle,
        draft: StudyDraft,
        verification: StudyVerification,
        policy_status: str | None,
    ) -> ReviewGateDecision:
        reasons: list[str] = []
        if verification.needs_review:
            reasons.append("verification_failed")
        if verification.confidence < self.confidence_threshold:
            reasons.append("low_confidence")
        if not draft.citations:
            reasons.append("missing_citations")
        if not evidence.chunks:
            reasons.append("empty_evidence")
        if str(policy_status or "").startswith("blocked") and evidence.mode != RetrievalMode.SIMPLE:
            reasons.append("policy_blocked_without_fallback")
        if (
            evidence.fallback_reason
            and target in {StudyTarget.QUESTION, StudyTarget.OUTLINE_FRAGMENT}
        ):
            reasons.append("target_used_fallback_evidence")
        if evidence.metadata.get("step_budget_exhausted") is True:
            reasons.append("agentic_step_budget_exhausted")

        if reasons:
            return ReviewGateDecision(
                status=WorkflowStageStatus.NEEDS_REVIEW,
                review_reasons=tuple(dict.fromkeys(reasons)),
            )
        return ReviewGateDecision(status=WorkflowStageStatus.PASSED)


def new_workflow_id() -> str:
    return f"workflow-{uuid4().hex}"


def sanitize_stage_summary(summary: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in summary.items():
        if key in _SAFE_STRING_VALUES:
            safe[key] = _safe_string(key, value)
        elif key in _SAFE_INT_KEYS:
            safe[key] = _safe_int(value)
        elif key in _SAFE_FLOAT_KEYS:
            safe[key] = _safe_float(value)
        elif key in _SAFE_BOOL_KEYS and isinstance(value, bool):
            safe[key] = value
        elif key in {"workflow_id", "request_id"} and isinstance(value, str):
            safe[key] = value
        elif key == "document_ids" and isinstance(value, (list, tuple)):
            safe[key] = [str(item) for item in value if str(item).strip()]
        elif value is None and key in _SAFE_STRING_VALUES:
            safe[key] = None
    return safe


def summarize_workflow_status(stages: list[WorkflowStageResult]) -> WorkflowStatus:
    if any(stage.status == WorkflowStageStatus.FAILED for stage in stages):
        return WorkflowStatus.FAILED
    if any(stage.status == WorkflowStageStatus.NEEDS_REVIEW for stage in stages):
        return WorkflowStatus.NEEDS_REVIEW
    if any(
        (stage.output_summary or {}).get("fallback_reason")
        for stage in stages
    ):
        return WorkflowStatus.COMPLETED_WITH_FALLBACK
    if stages:
        return WorkflowStatus.COMPLETED
    return WorkflowStatus.PARTIAL


def build_workflow_payload(
    *,
    workflow_id: str,
    stages: list[WorkflowStageResult],
    needs_review: bool,
) -> dict[str, Any]:
    status = summarize_workflow_status(stages)
    current_stage = stages[-1].stage_name.value if stages else None
    return {
        "workflow_id": workflow_id,
        "status": status.value,
        "current_stage": current_stage,
        "needs_review": needs_review or status == WorkflowStatus.NEEDS_REVIEW,
        "stage_count": len(stages),
        "stages": [stage.to_safe_dict() for stage in stages],
    }


def _safe_string(key: str, value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return "unknown"
    return value if value in _SAFE_STRING_VALUES[key] else "unknown"


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
```

- [ ] **Step 4: Run workflow contract tests**

Run:

```bash
pytest tests/test_study_agent_workflow.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit workflow contracts**

Run:

```bash
git add src/services/study_agent_workflow.py tests/test_study_agent_workflow.py
git commit -m "feat: add study agent workflow contracts"
```

- [ ] **Step 6: Run required reviews**

Run Spec review and Quality review for Task 1 before continuing.

## Task 2: Runtime Supervisor Timeline

**Files:**
- Modify: `src/services/study_agent_runtime.py`
- Modify: `tests/test_study_agent_runtime.py`

- [ ] **Step 1: Write failing runtime workflow tests**

Append to `tests/test_study_agent_runtime.py`:

```python
@pytest.mark.asyncio
async def test_runtime_attaches_completed_workflow_timeline():
    Session = _session_factory()
    _insert_ready_document_with_artifact(Session)
    runtime = StudyAgentRuntimeService(
        session_factory=Session,
        chunker=StudyDocumentChunker(max_chars=200, overlap_chars=20),
    )

    result = await runtime.run(
        {
            "query": "What do derivatives measure?",
            "target": "answer",
            "document_ids": ["doc-study"],
            "expected_terms": ["rate"],
            "authenticated_user_id": "user-1",
            "request_id": "req-workflow-complete",
        }
    )

    workflow = result.audit_metadata["workflow"]
    assert workflow["workflow_id"].startswith("workflow-")
    assert workflow["status"] in {"completed", "completed_with_fallback"}
    assert workflow["current_stage"] == "trace"
    assert workflow["needs_review"] is False
    assert [stage["stage"] for stage in workflow["stages"]] == [
        "intake",
        "plan",
        "retrieve",
        "generate",
        "verify",
        "review_gate",
        "trace",
    ]
    assert workflow["stages"][0]["output_summary"]["document_count"] == 1
    assert workflow["stages"][1]["output_summary"]["selected_mode"] == "simple_rag"
    assert workflow["stages"][2]["output_summary"]["chunk_count"] == 1
    assert workflow["stages"][3]["output_summary"]["citation_count"] == 1
    assert workflow["stages"][4]["output_summary"]["confidence"] >= 0


@pytest.mark.asyncio
async def test_runtime_workflow_records_fallback_and_review_gate():
    Session = _session_factory()
    _insert_ready_document_with_artifact(Session)
    runtime = StudyAgentRuntimeService(
        session_factory=Session,
        chunker=StudyDocumentChunker(max_chars=200, overlap_chars=20),
    )

    result = await runtime.run(
        {
            "query": "基于导数出一道题",
            "target": "question",
            "document_ids": ["doc-study"],
            "authenticated_user_id": "user-1",
            "request_id": "req-workflow-review",
        }
    )

    workflow = result.audit_metadata["workflow"]
    retrieve_stage = next(stage for stage in workflow["stages"] if stage["stage"] == "retrieve")
    review_stage = next(stage for stage in workflow["stages"] if stage["stage"] == "review_gate")

    assert retrieve_stage["output_summary"]["fallback_reason"] == "persisted_chunks_missing"
    assert workflow["status"] in {"completed_with_fallback", "needs_review"}
    assert review_stage["status"] in {"passed", "needs_review"}
    assert "query" not in str(workflow).lower()
    assert "导数" not in str(workflow)


@pytest.mark.asyncio
async def test_runtime_workflow_failure_for_missing_evidence_is_safe():
    Session = _session_factory()
    runtime = StudyAgentRuntimeService(session_factory=Session)

    with pytest.raises(StudyAgentDocumentError) as exc_info:
        await runtime.run(
            {
                "query": "What do derivatives measure?",
                "target": "answer",
                "document_ids": ["missing-doc"],
                "authenticated_user_id": "user-1",
                "request_id": "req-workflow-failed",
            }
        )

    assert exc_info.value.status_code == 404
```

- [ ] **Step 2: Run runtime workflow tests and confirm failure**

Run:

```bash
pytest tests/test_study_agent_runtime.py::test_runtime_attaches_completed_workflow_timeline tests/test_study_agent_runtime.py::test_runtime_workflow_records_fallback_and_review_gate tests/test_study_agent_runtime.py::test_runtime_workflow_failure_for_missing_evidence_is_safe -q
```

Expected: FAIL because `audit_metadata["workflow"]` does not exist.

- [ ] **Step 3: Add workflow timeline construction to runtime**

Modify `src/services/study_agent_runtime.py` imports:

```python
from time import perf_counter
from typing import Any

from src.services.study_agent_workflow import (
    ReviewGate,
    WorkflowStageName,
    WorkflowStageResult,
    WorkflowStageStatus,
    build_workflow_payload,
    new_workflow_id,
)
```

Inside `StudyAgentRuntimeService.run`, create `workflow_id = new_workflow_id()` and `stages: list[WorkflowStageResult] = []` after `started_at`.

Add local helper inside `run` or private module helper:

```python
def add_stage(
    name: WorkflowStageName,
    *,
    status: WorkflowStageStatus = WorkflowStageStatus.PASSED,
    input_summary: dict[str, Any] | None = None,
    output_summary: dict[str, Any] | None = None,
    error_code: str | None = None,
    review_reason: str | None = None,
) -> None:
    stages.append(
        WorkflowStageResult(
            stage_name=name,
            status=status,
            input_summary=input_summary or {},
            output_summary=output_summary or {},
            duration_ms=0.0,
            error_code=error_code,
            review_reason=review_reason,
        )
    )
```

Insert stage records in `run`:

After request normalization and authentication:

```python
add_stage(
    WorkflowStageName.INTAKE,
    output_summary={
        "document_count": len(request.document_ids),
        "target": request.target.value,
        "estimated_cost": request.budget.value,
    },
)
```

After `policy_decision`:

```python
add_stage(
    WorkflowStageName.PLAN,
    output_summary={
        "selected_mode": policy_decision.selected_mode.value,
        "router_mode": policy_decision.router_mode.value,
        "category": policy_decision.category,
        "policy_status": policy_decision.status,
        "readiness_status": policy_decision.readiness_status,
        "estimated_cost": policy_decision.estimated_cost,
    },
)
```

After `result = await orchestrator.run(orchestrator_payload)`:

```python
add_stage(
    WorkflowStageName.RETRIEVE,
    output_summary={
        "chunk_count": len(result.evidence.chunks),
        "source_count": len(result.evidence.sources),
        "concept_count": len(result.evidence.concept_ids),
        "chunk_source": chunk_source,
        "fallback_reason": result.evidence.fallback_reason or fallback_reason,
        "mode": result.evidence.mode.value,
    },
)
add_stage(
    WorkflowStageName.GENERATE,
    output_summary={
        "target": result.draft.target.value,
        "citation_count": len(result.draft.citations),
        "used_chunk_count": result.draft.used_chunk_count,
        "mode": result.evidence.mode.value,
    },
)
add_stage(
    WorkflowStageName.VERIFY,
    status=(
        WorkflowStageStatus.PASSED
        if not result.verification.needs_review
        else WorkflowStageStatus.NEEDS_REVIEW
    ),
    output_summary={
        "needs_review": result.verification.needs_review,
        "confidence": result.verification.confidence,
        "source_recall": result.verification.source_recall,
        "answer_term_recall": result.verification.answer_term_recall,
        "issue_count": len(result.verification.issues),
    },
    review_reason=(
        "verification_failed" if result.verification.needs_review else None
    ),
)
review_decision = ReviewGate().evaluate(
    target=result.request.target,
    evidence=result.evidence,
    draft=result.draft,
    verification=result.verification,
    policy_status=safe_policy.get("status"),
)
add_stage(
    WorkflowStageName.REVIEW_GATE,
    status=review_decision.status,
    output_summary={
        "needs_review": review_decision.status == WorkflowStageStatus.NEEDS_REVIEW,
        "review_reason": (
            review_decision.review_reasons[0]
            if review_decision.review_reasons
            else None
        ),
    },
    review_reason=(
        review_decision.review_reasons[0]
        if review_decision.review_reasons
        else None
    ),
)
add_stage(
    WorkflowStageName.TRACE,
    output_summary={
        "latency_ms": round((perf_counter() - started_at) * 1000, 3),
        "stage_count": len(stages) + 1,
    },
)
workflow = build_workflow_payload(
    workflow_id=workflow_id,
    stages=stages,
    needs_review=result.verification.needs_review
    or review_decision.status == WorkflowStageStatus.NEEDS_REVIEW,
)
```

Then set:

```python
result.audit_metadata["workflow"] = workflow
```

Keep existing audit metadata fields unchanged.

- [ ] **Step 4: Run runtime workflow tests**

Run:

```bash
pytest tests/test_study_agent_runtime.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit runtime workflow timeline**

Run:

```bash
git add src/services/study_agent_runtime.py tests/test_study_agent_runtime.py
git commit -m "feat: attach study agent workflow timeline"
```

- [ ] **Step 6: Run required reviews**

Run Spec review and Quality review for Task 2 before continuing.

## Task 3: Trace Persistence And Workflow Detail API

**Files:**
- Modify: `src/services/study_agent_trace.py`
- Modify: `src/api/routes/study_agent.py`
- Modify: `tests/test_study_agent_traces.py`
- Modify: `tests/test_study_agent_api.py`

- [ ] **Step 1: Write failing trace workflow tests**

Append to `tests/test_study_agent_traces.py`:

```python
def test_trace_persists_safe_workflow_payload():
    SessionFactory = _session_factory()
    service = StudyAgentTraceService(SessionFactory)
    result = _study_result()
    result.audit_metadata["workflow"] = {
        "workflow_id": "workflow-1",
        "status": "completed",
        "current_stage": "trace",
        "needs_review": False,
        "stage_count": 1,
        "stages": [
            {
                "stage": "retrieve",
                "status": "passed",
                "duration_ms": 1.0,
                "input_summary": {"query": "什么是导数？", "document_count": 1},
                "output_summary": {
                    "chunk_count": 1,
                    "chunk_content": "导数原文",
                    "source_count": 1,
                },
                "error_code": None,
                "review_reason": None,
            }
        ],
    }

    payload = service.record_success(
        owner_id="owner-1",
        request_id="req-1",
        result=result,
        latency_ms=42.5,
        index_statuses={},
    )

    assert payload["workflow"]["workflow_id"] == "workflow-1"
    assert payload["workflow"]["stages"][0]["input_summary"] == {"document_count": 1}
    serialized = json.dumps(payload["workflow"], ensure_ascii=False)
    assert "什么是导数" not in serialized
    assert "导数原文" not in serialized


def test_get_trace_returns_workflow_only_to_owner():
    SessionFactory = _session_factory()
    service = StudyAgentTraceService(SessionFactory)
    result = _study_result()
    result.audit_metadata["workflow"] = {
        "workflow_id": "workflow-owner",
        "status": "completed",
        "current_stage": "trace",
        "needs_review": False,
        "stage_count": 0,
        "stages": [],
    }

    created = service.record_success(
        owner_id="owner-1",
        request_id="req-1",
        result=result,
        latency_ms=42.5,
        index_statuses={},
    )

    owner_payload = service.get_trace("owner-1", created["trace_id"])
    other_owner_payload = service.get_trace("owner-2", created["trace_id"])

    assert owner_payload["workflow"]["workflow_id"] == "workflow-owner"
    assert other_owner_payload is None
```

- [ ] **Step 2: Write failing API workflow tests**

Append to `tests/test_study_agent_api.py`:

```python
@dataclass
class WorkflowStudyAgentOrchestrator:
    async def run(self, payload: dict) -> StudyAgentResult:
        result = await FakeStudyAgentOrchestrator(payloads=[]).run(payload)
        result.audit_metadata["workflow"] = {
            "workflow_id": "workflow-api",
            "status": "completed",
            "current_stage": "trace",
            "needs_review": False,
            "stage_count": 1,
            "stages": [
                {
                    "stage": "retrieve",
                    "status": "passed",
                    "duration_ms": 1.0,
                    "input_summary": {"query": payload["query"], "document_count": 1},
                    "output_summary": {
                        "chunk_count": 1,
                        "chunk_content": "导数描述函数的变化率。",
                    },
                    "error_code": None,
                    "review_reason": None,
                }
            ],
        }
        return result


def test_study_agent_query_returns_safe_workflow_payload(tmp_path: Path):
    Session = _session_factory()
    orchestrator = WorkflowStudyAgentOrchestrator()
    document_service = DocumentService(
        session_factory=Session,
        storage=LocalStorageBackend(tmp_path / "storage"),
    )
    app = create_app(
        document_service=document_service,
        session_factory=Session,
        secret_key="test-secret",
        allow_dev_user_header=False,
        study_agent_orchestrator=orchestrator,
    )
    client = TestClient(app)
    headers = _login(client)
    _insert_ready_document_for_api(Session)

    response = client.post(
        "/api/study-agent/query",
        headers=headers,
        json={"query": "什么是导数？", "document_ids": ["doc-api"]},
    )

    assert response.status_code == 200
    workflow = response.json()["workflow"]
    assert workflow["workflow_id"] == "workflow-api"
    assert workflow["stages"][0]["input_summary"] == {"document_count": 1}
    serialized = str(workflow)
    assert "什么是导数" not in serialized
    assert "导数描述" not in serialized


def test_study_agent_workflow_detail_is_owner_scoped(tmp_path: Path):
    client, _orchestrator, Session, _document_service = _client(tmp_path)
    headers = _login(client)
    _insert_ready_document_for_api(Session)

    response = client.post(
        "/api/study-agent/query",
        headers=headers,
        json={"query": "What do derivatives measure?", "document_ids": ["doc-api"]},
    )
    assert response.status_code == 200
    workflow_id = response.json()["workflow"]["workflow_id"]

    owner_response = client.get(
        f"/api/study-agent/workflows/{workflow_id}",
        headers=headers,
    )
    assert owner_response.status_code == 200
    assert owner_response.json()["workflow_id"] == workflow_id

    with Session() as session:
        session.add(
            UserRecord(
                id="user-2",
                email="other@example.com",
                password_hash=hash_password("password-123"),
                role="user",
                is_active=True,
            )
        )
        session.commit()
    other_login = client.post(
        "/api/auth/login",
        json={"email": "other@example.com", "password": "password-123"},
    )
    other_headers = {"Authorization": f"Bearer {other_login.json()['access_token']}"}

    other_response = client.get(
        f"/api/study-agent/workflows/{workflow_id}",
        headers=other_headers,
    )
    assert other_response.status_code == 404
```

- [ ] **Step 3: Run trace/API workflow tests and confirm failure**

Run:

```bash
pytest tests/test_study_agent_traces.py::test_trace_persists_safe_workflow_payload tests/test_study_agent_traces.py::test_get_trace_returns_workflow_only_to_owner tests/test_study_agent_api.py::test_study_agent_query_returns_safe_workflow_payload tests/test_study_agent_api.py::test_study_agent_workflow_detail_is_owner_scoped -q
```

Expected: FAIL because workflow is not sanitized/persisted/exposed and workflow detail API does not exist.

- [ ] **Step 4: Add safe workflow metadata helpers to trace service**

Modify `src/services/study_agent_trace.py` imports:

```python
from src.services.study_agent_workflow import sanitize_workflow_payload
```

If `sanitize_workflow_payload` was not added in Task 1, add it to `study_agent_workflow.py`:

```python
def sanitize_workflow_payload(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    workflow_id = payload.get("workflow_id")
    if not isinstance(workflow_id, str) or not workflow_id.startswith("workflow-"):
        return None
    stages = payload.get("stages")
    safe_stages = []
    if isinstance(stages, list):
        for raw_stage in stages:
            if not isinstance(raw_stage, dict):
                continue
            stage = raw_stage.get("stage")
            status = raw_stage.get("status")
            if not isinstance(stage, str) or stage not in _SAFE_STRING_VALUES["stage"]:
                continue
            if not isinstance(status, str) or status not in _SAFE_STRING_VALUES["status"]:
                continue
            safe_stages.append(
                {
                    "stage": stage,
                    "status": status,
                    "duration_ms": _safe_float(raw_stage.get("duration_ms")),
                    "input_summary": sanitize_stage_summary(raw_stage.get("input_summary") or {}),
                    "output_summary": sanitize_stage_summary(raw_stage.get("output_summary") or {}),
                    "error_code": _safe_string("error_code", raw_stage.get("error_code")),
                    "review_reason": _safe_string("review_reason", raw_stage.get("review_reason")),
                }
            )
    status = _safe_string("status", payload.get("status")) or "unknown"
    current_stage = _safe_string("stage", payload.get("current_stage"))
    return {
        "workflow_id": workflow_id,
        "status": status,
        "current_stage": current_stage,
        "needs_review": payload.get("needs_review") is True,
        "stage_count": _safe_int(payload.get("stage_count")),
        "stages": safe_stages,
    }
```

In `StudyAgentTraceService.record_success`, add:

```python
safe_workflow = sanitize_workflow_payload(result.audit_metadata.get("workflow"))
if safe_workflow is not None:
    trace_metadata["workflow"] = safe_workflow
```

In `_trace_payload`, add:

```python
workflow = sanitize_workflow_payload((record.trace_metadata or {}).get("workflow"))
if workflow is not None:
    payload["workflow"] = workflow
```

- [ ] **Step 5: Return workflow from Study Agent API**

Modify `src/api/routes/study_agent.py` imports:

```python
from src.services.study_agent_workflow import sanitize_workflow_payload
```

In `query_study_agent`, after adding policy:

```python
workflow = sanitize_workflow_payload(audit_metadata.get("workflow"))
if workflow is not None:
    response_payload["workflow"] = workflow
```

Add route:

```python
@router.get("/workflows/{workflow_id}")
def get_study_agent_workflow(request: Request, workflow_id: str) -> dict[str, Any]:
    context = get_user_context(request)
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        raise HTTPException(
            status_code=503,
            detail="Study agent trace store is not configured",
        )
    trace = StudyAgentTraceService(session_factory).get_workflow(
        owner_id=context.user_id,
        workflow_id=workflow_id,
    )
    if trace is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return trace
```

Add `get_workflow` to `StudyAgentTraceService`:

```python
def get_workflow(self, owner_id: str, workflow_id: str) -> dict[str, Any] | None:
    with self.session_factory() as session:
        records = session.scalars(
            select(StudyAgentTraceRecord).where(
                StudyAgentTraceRecord.owner_id == owner_id,
            )
        ).all()
        for record in records:
            workflow = sanitize_workflow_payload(
                (record.trace_metadata or {}).get("workflow")
            )
            if workflow and workflow.get("workflow_id") == workflow_id:
                return workflow
    return None
```

- [ ] **Step 6: Run trace/API workflow tests**

Run:

```bash
pytest tests/test_study_agent_traces.py tests/test_study_agent_api.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit trace/API workflow persistence**

Run:

```bash
git add src/services/study_agent_workflow.py src/services/study_agent_trace.py src/api/routes/study_agent.py tests/test_study_agent_traces.py tests/test_study_agent_api.py
git commit -m "feat: persist study agent workflow traces"
```

- [ ] **Step 8: Run required reviews**

Run Spec review and Quality review for Task 3 before continuing.

## Task 4: Frontend Workflow Timeline

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/components/StudyAgentPanel.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Add frontend workflow types**

Modify `frontend/src/api.ts`:

```ts
export interface StudyAgentWorkflowStage {
  stage: string;
  status: string;
  duration_ms?: number | null;
  input_summary?: Record<string, unknown>;
  output_summary?: Record<string, unknown>;
  error_code?: string | null;
  review_reason?: string | null;
}

export interface StudyAgentWorkflowDiagnostic {
  workflow_id: string;
  status: string;
  current_stage?: string | null;
  needs_review: boolean;
  stage_count: number;
  stages: StudyAgentWorkflowStage[];
}
```

Add to `StudyAgentTraceSummary`:

```ts
workflow?: StudyAgentWorkflowDiagnostic | null;
```

Add to `StudyAgentResult`:

```ts
workflow?: StudyAgentWorkflowDiagnostic | null;
```

- [ ] **Step 2: Render compact workflow timeline**

In `frontend/src/components/StudyAgentPanel.tsx`, add helper:

```tsx
function WorkflowTimeline({ workflow }: { workflow: StudyAgentResult["workflow"] }) {
  if (!workflow) return null;
  return (
    <div className="study-agent-workflow">
      <div className="study-agent-workflow-header">
        <span>Workflow: {workflow.status}</span>
        <span>Stage: {workflow.current_stage ?? "unknown"}</span>
        {workflow.needs_review ? <span className="study-agent-policy-warning">Review</span> : null}
      </div>
      <ol>
        {workflow.stages.map((stage) => (
          <li key={`${stage.stage}-${stage.status}`}>
            <span>{stage.stage}</span>
            <span>{stage.status}</span>
            {typeof stage.duration_ms === "number" ? (
              <span>{Math.round(stage.duration_ms)}ms</span>
            ) : null}
            {stage.review_reason ? <span>{stage.review_reason}</span> : null}
            {stage.error_code ? <span>{stage.error_code}</span> : null}
          </li>
        ))}
      </ol>
    </div>
  );
}
```

Render below existing policy diagnostic/result metadata:

```tsx
<WorkflowTimeline workflow={result.workflow} />
```

- [ ] **Step 3: Add workflow styles**

In `frontend/src/styles.css`, add:

```css
.study-agent-workflow {
  display: grid;
  gap: 8px;
  border-top: 1px solid #e5e7eb;
  padding-top: 10px;
  color: #374151;
  font-size: 0.85rem;
}

.study-agent-workflow-header {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  font-weight: 600;
}

.study-agent-workflow ol {
  display: grid;
  gap: 4px;
  margin: 0;
  padding-left: 18px;
}

.study-agent-workflow li {
  display: grid;
  grid-template-columns: minmax(90px, 1fr) minmax(70px, auto) auto auto;
  gap: 8px;
  align-items: center;
}
```

- [ ] **Step 4: Run frontend build and inspect for type errors**

Run:

```bash
cd frontend && npm run build
```

Expected: PASS.

- [ ] **Step 5: Commit frontend workflow timeline**

Run:

```bash
git add frontend/src/api.ts frontend/src/components/StudyAgentPanel.tsx frontend/src/styles.css
git commit -m "feat: show study agent workflow timeline"
```

- [ ] **Step 6: Run required reviews**

Run Spec review and Quality review for Task 4 before continuing.

## Task 5: Final Verification And Documentation Sync

**Files:**
- Modify: `README.md`
- Modify: `SPEC.md`
- Modify: `docs/superpowers/specs/2026-06-29-agent-workflow-supervisor-design.md` only if implementation forces a small clarification.

- [ ] **Step 1: Update README status**

Add to the MVP-9 section in `README.md`:

```markdown
Study Agent workflow supervision now exposes a safe stage timeline for intake, planning, retrieval, generation, verification, review gate, and trace. Workflow diagnostics are compact and privacy-safe: they include status, counts, mode/category labels, fallback and review reason codes, but not raw queries, generated answers, chunks, prompts, hidden reasoning, or secrets.
```

- [ ] **Step 2: Update SPEC status**

Add to current MVP-9 implementation status in `SPEC.md`:

```markdown
- Agent workflow supervisor: implemented as a deterministic stage supervisor over the Study Agent runtime. It exposes safe workflow status and stage timelines while keeping multi-agent roles as service boundaries before any open-ended autonomous agent behavior.
```

- [ ] **Step 3: Run final backend verification**

Run:

```bash
pytest tests/test_study_agent_workflow.py tests/test_study_agent_runtime.py tests/test_study_agent_traces.py tests/test_study_agent_api.py tests/test_api_permissions_audit.py -q
```

Expected: PASS.

- [ ] **Step 4: Run full P2 regression suite**

Run:

```bash
pytest tests/test_rag_route_policy.py tests/test_rag_router.py tests/test_study_agent_runtime.py tests/test_graph_rag.py tests/test_agentic_rag.py tests/test_study_agent_api.py tests/test_api_permissions_audit.py tests/test_rag_evaluation.py tests/test_rag_mode_comparison.py tests/test_study_agent_workflow.py tests/test_study_agent_traces.py -q
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
git add README.md SPEC.md docs/superpowers/specs/2026-06-29-agent-workflow-supervisor-design.md
git commit -m "docs: sync agent workflow supervisor status"
```

- [ ] **Step 8: Run final task reviews**

Run Spec review and Quality review for Task 5 before marking implementation complete.

## Final Verification Before Completion

After all tasks and reviews pass, run:

```bash
pytest tests/test_rag_route_policy.py tests/test_rag_router.py tests/test_study_agent_runtime.py tests/test_graph_rag.py tests/test_agentic_rag.py tests/test_study_agent_api.py tests/test_api_permissions_audit.py tests/test_rag_evaluation.py tests/test_rag_mode_comparison.py tests/test_study_agent_workflow.py tests/test_study_agent_traces.py -q
cd frontend && npm run build
git status --short --branch
```

Expected:

- backend tests pass;
- frontend build passes;
- no generated `docs/evaluation/*.json` or `docs/evaluation/*.md` artifacts are tracked or left untracked;
- worktree is clean after final commit.

## Self-Review Checklist For This Plan

- Spec coverage: Tasks 1-5 cover workflow contracts, safe summaries, review gate, runtime timeline, trace persistence, workflow detail API, frontend display, docs, privacy, owner isolation, fallback and review statuses, and development governance review gates.
- Placeholder scan: No task uses unresolved placeholders or asks a worker to invent missing behavior without examples.
- Type consistency: `WorkflowStageName`, `WorkflowStageStatus`, `WorkflowStatus`, `WorkflowStageResult`, `ReviewGate`, `build_workflow_payload`, and `sanitize_workflow_payload` names are consistent across tasks.
- Scope check: No task adds autonomous loops, async cancellation/resume, workflow engine schema, automatic review task creation, admin workflow search, self-evolution, prompt mutation, or a dashboard.
