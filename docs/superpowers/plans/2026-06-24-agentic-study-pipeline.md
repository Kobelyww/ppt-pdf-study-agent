# Agentic Study Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the MVP-9 Agentic Study Pipeline: route study requests across simple, graph, and agentic RAG, gather evidence, generate grounded study content, verify it, and expose a narrow authenticated API.

**Architecture:** Add a focused service boundary under `src/services/study_agent.py` with dataclass contracts, evidence collection, deterministic generation, verification, and orchestration. Reuse the existing `RAGStrategyRouter`, `RAGService`, `GraphRAGLiteRetriever`, `AgenticRAGPlanner`, `RAGEvaluator`, `KnowledgeGraph`, and FastAPI auth middleware. Keep implementation deterministic and test-first so later LLM/provider work can replace only the generator boundary.

**Tech Stack:** Python dataclasses, FastAPI, pytest, pytest-asyncio, existing SQLAlchemy auth test helpers, existing in-memory RAG/graph services.

---

## File Structure

- Create: `src/services/study_agent.py`
  - Owns MVP-9 study-agent contracts and service implementation.
  - Defines `StudyTarget`, `StudyBudget`, `StudyRequest`, `StudyPlan`, `EvidenceBundle`, `StudyDraft`, `StudyVerification`, `StudyAgentResult`, `StudyContentGenerator`, `StudyVerifier`, and `StudyAgentOrchestrator`.
- Create: `src/api/routes/study_agent.py`
  - Owns the authenticated `POST /api/study-agent/query` route.
  - Validates request payload with Pydantic and calls `app.state.study_agent_orchestrator`.
- Modify: `src/api/app.py`
  - Adds optional `study_agent_orchestrator` injection to `create_app`.
  - Registers the study-agent router.
- Create: `tests/test_study_agent_contracts.py`
  - Covers request validation, target/budget validation, and safe normalized request behavior.
- Create: `tests/test_study_agent_evidence.py`
  - Covers simple, graph, agentic, and fallback evidence collection.
- Create: `tests/test_study_agent_generator_verifier.py`
  - Covers deterministic answer/question/outline generation and verification failure modes.
- Create: `tests/test_study_agent_orchestrator.py`
  - Covers end-to-end service orchestration for answer and question targets.
- Create: `tests/test_study_agent_api.py`
  - Covers authenticated API behavior and middleware integration.
- Modify only if needed: `src/services/__init__.py`
  - Leave unchanged unless imports are already exported there during implementation.

## Task 1: Study Agent Contracts

**Files:**
- Create: `src/services/study_agent.py`
- Test: `tests/test_study_agent_contracts.py`

- [ ] **Step 1: Write failing contract tests**

Create `tests/test_study_agent_contracts.py`:

```python
import pytest

from src.services.rag_router import RetrievalMode
from src.services.study_agent import (
    StudyBudget,
    StudyRequest,
    StudyTarget,
    normalize_study_request,
)


def test_normalizes_minimal_study_request_defaults():
    request = normalize_study_request({"query": "  什么是导数？  "})

    assert request == StudyRequest(
        query="什么是导数？",
        target=StudyTarget.ANSWER,
        document_ids=(),
        preferred_mode=None,
        budget=StudyBudget.BALANCED,
        expected_terms=(),
    )


def test_normalizes_optional_fields_and_deduplicates_document_ids():
    request = normalize_study_request(
        {
            "query": "基于第2章出一道题",
            "target": "question",
            "document_ids": ["doc-1", "doc-1", "doc-2", ""],
            "preferred_mode": "agentic_rag",
            "budget": "high",
            "expected_terms": ["特征值", "特征值", "矩阵"],
        }
    )

    assert request.target == StudyTarget.QUESTION
    assert request.document_ids == ("doc-1", "doc-2")
    assert request.preferred_mode == RetrievalMode.AGENTIC
    assert request.budget == StudyBudget.HIGH
    assert request.expected_terms == ("特征值", "矩阵")


def test_rejects_empty_query():
    with pytest.raises(ValueError, match="query must not be empty"):
        normalize_study_request({"query": "   "})


def test_rejects_unknown_target_budget_and_mode():
    with pytest.raises(ValueError, match="unsupported study target"):
        normalize_study_request({"query": "x", "target": "essay"})

    with pytest.raises(ValueError, match="unsupported study budget"):
        normalize_study_request({"query": "x", "budget": "expensive"})

    with pytest.raises(ValueError, match="unsupported retrieval mode"):
        normalize_study_request({"query": "x", "preferred_mode": "hybrid"})
```

- [ ] **Step 2: Run contract tests and verify red**

Run:

```bash
pytest tests/test_study_agent_contracts.py -q
```

Expected: fail during import with `ModuleNotFoundError: No module named 'src.services.study_agent'`.

- [ ] **Step 3: Implement contracts and request normalization**

Create `src/services/study_agent.py` with this initial content:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.services.rag_router import RetrievalMode
from src.services.rag_service import Chunk


class StudyTarget(str, Enum):
    ANSWER = "answer"
    QUESTION = "question"
    OUTLINE_FRAGMENT = "outline_fragment"


class StudyBudget(str, Enum):
    LOW = "low"
    BALANCED = "balanced"
    HIGH = "high"


@dataclass(frozen=True)
class StudyRequest:
    query: str
    target: StudyTarget = StudyTarget.ANSWER
    document_ids: tuple[str, ...] = ()
    preferred_mode: RetrievalMode | None = None
    budget: StudyBudget = StudyBudget.BALANCED
    expected_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class StudyPlan:
    mode: RetrievalMode
    reason: str
    steps: tuple[str, ...]
    estimated_cost: str
    fallbacks: tuple[RetrievalMode, ...] = ()


@dataclass(frozen=True)
class EvidenceBundle:
    mode: RetrievalMode
    chunks: tuple[Chunk, ...]
    sources: tuple[str, ...]
    concept_ids: tuple[str, ...]
    confidence: float
    reason: str
    fallback_reason: str | None = None


@dataclass(frozen=True)
class StudyDraft:
    target: StudyTarget
    content: str
    citations: tuple[str, ...]
    used_chunk_count: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StudyVerification:
    passed: bool
    needs_review: bool
    confidence: float
    issues: tuple[str, ...]
    source_recall: float
    answer_term_recall: float


@dataclass(frozen=True)
class StudyAgentResult:
    request: StudyRequest
    plan: StudyPlan
    evidence: EvidenceBundle
    draft: StudyDraft
    verification: StudyVerification
    audit_metadata: dict[str, Any]


def normalize_study_request(payload: dict[str, Any]) -> StudyRequest:
    query = str(payload.get("query", "")).strip()
    if not query:
        raise ValueError("query must not be empty")

    target = _enum_value(
        StudyTarget,
        payload.get("target", StudyTarget.ANSWER.value),
        "unsupported study target",
    )
    budget = _enum_value(
        StudyBudget,
        payload.get("budget", StudyBudget.BALANCED.value),
        "unsupported study budget",
    )
    preferred_mode = payload.get("preferred_mode")
    mode = None
    if preferred_mode not in {None, ""}:
        mode = _enum_value(RetrievalMode, preferred_mode, "unsupported retrieval mode")

    return StudyRequest(
        query=query,
        target=target,
        document_ids=_dedupe_nonempty(payload.get("document_ids") or []),
        preferred_mode=mode,
        budget=budget,
        expected_terms=_dedupe_nonempty(payload.get("expected_terms") or []),
    )


def _enum_value(enum_type, raw_value: Any, error_message: str):
    try:
        return enum_type(str(raw_value))
    except ValueError as exc:
        raise ValueError(error_message) from exc


def _dedupe_nonempty(values: list[Any] | tuple[Any, ...]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for value in values:
        normalized = str(value).strip()
        if normalized:
            seen.setdefault(normalized, None)
    return tuple(seen)
```

- [ ] **Step 4: Run contract tests and verify green**

Run:

```bash
pytest tests/test_study_agent_contracts.py -q
```

Expected: `4 passed`.

- [ ] **Step 5: Commit contracts**

Run:

```bash
git add src/services/study_agent.py tests/test_study_agent_contracts.py
git commit -m "feat: add study agent request contracts"
```

## Task 2: Evidence Collection And Routing

**Files:**
- Modify: `src/services/study_agent.py`
- Test: `tests/test_study_agent_evidence.py`

- [ ] **Step 1: Write failing evidence tests**

Create `tests/test_study_agent_evidence.py`:

```python
import pytest

from src.knowledge.knowledge_graph import KnowledgeGraph, KnowledgePoint, Relationship
from src.services.rag_router import RetrievalMode
from src.services.rag_service import Chunk, RAGService
from src.services.study_agent import (
    EvidenceCollector,
    StudyBudget,
    StudyRequest,
    StudyTarget,
)


def _rag_service() -> RAGService:
    service = RAGService()
    service.index_chunks(
        [
            {
                "content": "导数描述函数的变化率。",
                "source": "calculus:derivative",
                "metadata": {"concept_id": "kp-derivative"},
            },
            {
                "content": "梯度是多变量函数偏导数组成的向量。",
                "source": "calculus:gradient",
                "metadata": {"concept_id": "kp-gradient"},
            },
        ]
    )
    return service


def _graph() -> KnowledgeGraph:
    graph = KnowledgeGraph()
    graph.add_point(
        KnowledgePoint(
            id="kp-derivative",
            name="Derivative",
            description="Rate of change",
            category="calculus",
            metadata={"aliases": ["导数"]},
        )
    )
    graph.add_point(
        KnowledgePoint(
            id="kp-gradient",
            name="Gradient",
            description="Vector of partial derivatives",
            category="calculus",
            metadata={"aliases": ["梯度"]},
        )
    )
    graph.add_relationship(Relationship("kp-derivative", "kp-gradient", "extends_to"))
    return graph


@pytest.mark.asyncio
async def test_collects_simple_rag_evidence_with_sources_and_confidence():
    collector = EvidenceCollector(rag_service=_rag_service(), graph=_graph())
    request = StudyRequest(query="什么是导数？", target=StudyTarget.ANSWER)

    bundle = await collector.collect(request, mode=RetrievalMode.SIMPLE)

    assert bundle.mode == RetrievalMode.SIMPLE
    assert bundle.sources == ("calculus:derivative",)
    assert bundle.concept_ids == ("kp-derivative",)
    assert bundle.confidence > 0
    assert bundle.reason == "simple token-overlap retrieval"


@pytest.mark.asyncio
async def test_collects_graph_rag_evidence_with_expanded_concepts():
    collector = EvidenceCollector(rag_service=_rag_service(), graph=_graph())
    request = StudyRequest(query="导数和梯度有什么关系？")

    bundle = await collector.collect(request, mode=RetrievalMode.GRAPH)

    assert bundle.mode == RetrievalMode.GRAPH
    assert "calculus:gradient" in bundle.sources
    assert bundle.concept_ids == ("kp-derivative", "kp-gradient")
    assert bundle.reason == "matched concepts and expanded graph neighbors"


@pytest.mark.asyncio
async def test_graph_without_seed_falls_back_to_simple_rag():
    collector = EvidenceCollector(rag_service=_rag_service(), graph=_graph())
    request = StudyRequest(query="矩阵分解是什么？")

    bundle = await collector.collect(request, mode=RetrievalMode.GRAPH)

    assert bundle.mode == RetrievalMode.SIMPLE
    assert bundle.fallback_reason == "no graph seed matched"
    assert bundle.confidence == 0.0


@pytest.mark.asyncio
async def test_low_budget_agentic_request_uses_simple_evidence():
    collector = EvidenceCollector(rag_service=_rag_service(), graph=_graph())
    request = StudyRequest(
        query="基于第2章和第4章出一道综合题",
        target=StudyTarget.QUESTION,
        budget=StudyBudget.LOW,
    )

    bundle = await collector.collect(request, mode=RetrievalMode.AGENTIC)

    assert bundle.mode == RetrievalMode.SIMPLE
    assert bundle.fallback_reason == "low budget prevents agentic retrieval"
```

- [ ] **Step 2: Run evidence tests and verify red**

Run:

```bash
pytest tests/test_study_agent_evidence.py -q
```

Expected: fail with `ImportError: cannot import name 'EvidenceCollector'`.

- [ ] **Step 3: Add `EvidenceCollector` implementation**

Append this code to `src/services/study_agent.py`:

```python
from src.knowledge.knowledge_graph import KnowledgeGraph
from src.services.agentic_rag import AgenticRAGPlanner
from src.services.graph_rag import GraphRAGLiteRetriever
from src.services.rag_service import RAGService


class EvidenceCollector:
    def __init__(
        self,
        *,
        rag_service: RAGService,
        graph: KnowledgeGraph | None = None,
        agentic_planner: AgenticRAGPlanner | None = None,
        top_k: int = 5,
    ) -> None:
        self.rag_service = rag_service
        self.graph = graph or KnowledgeGraph()
        self.agentic_planner = agentic_planner or AgenticRAGPlanner()
        self.top_k = top_k

    async def collect(self, request: StudyRequest, mode: RetrievalMode) -> EvidenceBundle:
        if mode == RetrievalMode.SIMPLE:
            return self._simple_bundle(request, fallback_reason=None)
        if mode == RetrievalMode.GRAPH:
            return await self._graph_bundle(request)
        if mode == RetrievalMode.AGENTIC:
            return await self._agentic_bundle(request)
        raise ValueError(f"unsupported retrieval mode: {mode}")

    def _simple_bundle(
        self,
        request: StudyRequest,
        *,
        fallback_reason: str | None,
    ) -> EvidenceBundle:
        chunks = tuple(self.rag_service.retrieve(request.query, top_k=self.top_k))
        if not chunks:
            chunks = self._substring_fallback_chunks(request.query)
        return EvidenceBundle(
            mode=RetrievalMode.SIMPLE,
            chunks=chunks,
            sources=_unique(chunk.source for chunk in chunks if chunk.source),
            concept_ids=_unique(
                str(chunk.metadata.get("concept_id", "")).strip()
                for chunk in chunks
                if str(chunk.metadata.get("concept_id", "")).strip()
            ),
            confidence=_average_score(chunks),
            reason="simple token-overlap retrieval",
            fallback_reason=fallback_reason,
        )

    def _substring_fallback_chunks(self, query: str) -> tuple[Chunk, ...]:
        matched: list[Chunk] = []
        for chunk in self.rag_service._chunks:
            if any(token and token in chunk.content for token in _query_terms(query)):
                matched.append(
                    Chunk(
                        content=chunk.content,
                        source=chunk.source,
                        metadata=chunk.metadata.copy(),
                        score=max(chunk.score, 0.5),
                    )
                )
        return tuple(matched[: self.top_k])

    async def _graph_bundle(self, request: StudyRequest) -> EvidenceBundle:
        result = await GraphRAGLiteRetriever(
            self.graph,
            self.rag_service.retrieve(request.query, top_k=self.top_k) or self.rag_service._chunks,
        ).retrieve(request.query, top_k=self.top_k)
        if not result.chunks:
            return self._simple_bundle(request, fallback_reason=result.reason)
        return EvidenceBundle(
            mode=RetrievalMode.GRAPH,
            chunks=tuple(result.chunks),
            sources=_unique(chunk.source for chunk in result.chunks if chunk.source),
            concept_ids=tuple(result.expanded_point_ids),
            confidence=result.confidence,
            reason=result.reason,
        )

    async def _agentic_bundle(self, request: StudyRequest) -> EvidenceBundle:
        if request.budget == StudyBudget.LOW:
            return self._simple_bundle(
                request,
                fallback_reason="low budget prevents agentic retrieval",
            )
        self.agentic_planner.plan(request.query)
        graph_bundle = await self._graph_bundle(request)
        if graph_bundle.confidence > 0:
            return EvidenceBundle(
                mode=RetrievalMode.AGENTIC,
                chunks=graph_bundle.chunks,
                sources=graph_bundle.sources,
                concept_ids=graph_bundle.concept_ids,
                confidence=graph_bundle.confidence,
                reason="agentic plan with graph-expanded evidence",
                fallback_reason=graph_bundle.fallback_reason,
            )
        return self._simple_bundle(request, fallback_reason="agentic evidence unavailable")


def _unique(values) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for value in values:
        if value:
            seen.setdefault(str(value), None)
    return tuple(seen)


def _average_score(chunks: tuple[Chunk, ...]) -> float:
    if not chunks:
        return 0.0
    return min(1.0, sum(chunk.score for chunk in chunks) / len(chunks))


def _query_terms(query: str) -> tuple[str, ...]:
    normalized = query.strip()
    for marker in ["什么是", "是什么", "请解释", "解释", "？", "?", "。"]:
        normalized = normalized.replace(marker, " ")
    return tuple(term.strip() for term in normalized.split() if term.strip())
```

- [ ] **Step 4: Run evidence tests and existing RAG tests**

Run:

```bash
pytest tests/test_study_agent_evidence.py tests/test_rag_router.py tests/test_graph_rag.py tests/test_agentic_rag.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit evidence collector**

Run:

```bash
git add src/services/study_agent.py tests/test_study_agent_evidence.py
git commit -m "feat: collect study agent evidence"
```

## Task 3: Deterministic Generator And Verifier

**Files:**
- Modify: `src/services/study_agent.py`
- Test: `tests/test_study_agent_generator_verifier.py`

- [ ] **Step 1: Write failing generator/verifier tests**

Create `tests/test_study_agent_generator_verifier.py`:

```python
from src.services.rag_router import RetrievalMode
from src.services.rag_service import Chunk
from src.services.study_agent import (
    EvidenceBundle,
    StudyContentGenerator,
    StudyRequest,
    StudyTarget,
    StudyVerifier,
)


def _bundle() -> EvidenceBundle:
    return EvidenceBundle(
        mode=RetrievalMode.SIMPLE,
        chunks=(
            Chunk(
                content="导数描述函数的变化率。",
                source="calculus:derivative",
                score=0.9,
            ),
        ),
        sources=("calculus:derivative",),
        concept_ids=("kp-derivative",),
        confidence=0.9,
        reason="simple token-overlap retrieval",
    )


def test_generator_creates_answer_with_citation():
    draft = StudyContentGenerator().generate(
        StudyRequest(query="什么是导数？", target=StudyTarget.ANSWER),
        _bundle(),
    )

    assert draft.target == StudyTarget.ANSWER
    assert "导数描述函数的变化率" in draft.content
    assert "calculus:derivative" in draft.content
    assert draft.citations == ("calculus:derivative",)


def test_generator_creates_question_answer_explanation_and_rubric():
    draft = StudyContentGenerator().generate(
        StudyRequest(query="基于第2章出一道题", target=StudyTarget.QUESTION),
        _bundle(),
    )

    assert "### Practice Question" in draft.content
    assert "### Answer" in draft.content
    assert "### Explanation" in draft.content
    assert "### Scoring Rubric" in draft.content
    assert draft.metadata["target"] == "question"


def test_generator_creates_outline_fragment():
    draft = StudyContentGenerator().generate(
        StudyRequest(query="整理导数复习提纲", target=StudyTarget.OUTLINE_FRAGMENT),
        _bundle(),
    )

    assert draft.content.startswith("## Study Notes")
    assert "- 导数描述函数的变化率。" in draft.content


def test_verifier_passes_grounded_draft():
    request = StudyRequest(query="什么是导数？", expected_terms=("变化率",))
    draft = StudyContentGenerator().generate(request, _bundle())

    verification = StudyVerifier().verify(request, _bundle(), draft)

    assert verification.passed is True
    assert verification.needs_review is False
    assert verification.source_recall == 1.0
    assert verification.answer_term_recall == 1.0
    assert verification.issues == ()


def test_verifier_flags_missing_citations_and_low_confidence():
    request = StudyRequest(query="什么是矩阵分解？", expected_terms=("矩阵",))
    empty_bundle = EvidenceBundle(
        mode=RetrievalMode.SIMPLE,
        chunks=(),
        sources=(),
        concept_ids=(),
        confidence=0.0,
        reason="simple token-overlap retrieval",
    )
    draft = StudyContentGenerator().generate(request, empty_bundle)

    verification = StudyVerifier(min_confidence=0.5).verify(request, empty_bundle, draft)

    assert verification.passed is False
    assert verification.needs_review is True
    assert "missing citations" in verification.issues
    assert "low evidence confidence" in verification.issues
```

- [ ] **Step 2: Run generator/verifier tests and verify red**

Run:

```bash
pytest tests/test_study_agent_generator_verifier.py -q
```

Expected: fail with `ImportError` for `StudyContentGenerator` or `StudyVerifier`.

- [ ] **Step 3: Add generator and verifier implementation**

Append this code to `src/services/study_agent.py`:

```python
from src.services.rag_evaluation import RAGEvalCase, RAGEvaluator


class StudyContentGenerator:
    def generate(self, request: StudyRequest, evidence: EvidenceBundle) -> StudyDraft:
        if request.target == StudyTarget.QUESTION:
            content = self._question_content(request, evidence)
        elif request.target == StudyTarget.OUTLINE_FRAGMENT:
            content = self._outline_content(evidence)
        else:
            content = self._answer_content(request, evidence)
        return StudyDraft(
            target=request.target,
            content=content,
            citations=evidence.sources,
            used_chunk_count=len(evidence.chunks),
            metadata={
                "target": request.target.value,
                "mode": evidence.mode.value,
                "evidence_confidence": evidence.confidence,
            },
        )

    def _answer_content(self, request: StudyRequest, evidence: EvidenceBundle) -> str:
        if not evidence.chunks:
            return f"未找到足够证据回答：{request.query}"
        lines = [chunk.content for chunk in evidence.chunks]
        if evidence.sources:
            lines.append("")
            lines.append("Sources: " + ", ".join(evidence.sources))
        return "\n\n".join(lines)

    def _question_content(self, request: StudyRequest, evidence: EvidenceBundle) -> str:
        basis = evidence.chunks[0].content if evidence.chunks else request.query
        source = evidence.sources[0] if evidence.sources else "no-source"
        return "\n".join(
            [
                "### Practice Question",
                f"Explain the key idea in this material: {basis}",
                "",
                "### Answer",
                basis,
                "",
                "### Explanation",
                f"The answer should be grounded in source `{source}`.",
                "",
                "### Scoring Rubric",
                "- 1 point for naming the core concept.",
                "- 1 point for explaining the relationship or definition.",
                "- 1 point for citing the source evidence.",
            ]
        )

    def _outline_content(self, evidence: EvidenceBundle) -> str:
        lines = ["## Study Notes"]
        if not evidence.chunks:
            lines.append("- No grounded notes available.")
            return "\n".join(lines)
        for chunk in evidence.chunks:
            suffix = f" ({chunk.source})" if chunk.source else ""
            lines.append(f"- {chunk.content}{suffix}")
        return "\n".join(lines)


class StudyVerifier:
    def __init__(self, min_confidence: float = 0.2) -> None:
        self.min_confidence = min_confidence
        self.evaluator = RAGEvaluator()

    def verify(
        self,
        request: StudyRequest,
        evidence: EvidenceBundle,
        draft: StudyDraft,
    ) -> StudyVerification:
        issues: list[str] = []
        if not draft.citations:
            issues.append("missing citations")
        if evidence.confidence < self.min_confidence:
            issues.append("low evidence confidence")
        if draft.used_chunk_count == 0:
            issues.append("no evidence chunks used")

        score = self.evaluator.score(
            RAGEvalCase(
                id="study-agent-inline",
                query=request.query,
                category=request.target.value,
                expected_sources=list(evidence.sources),
                expected_terms=list(request.expected_terms),
            ),
            answer=draft.content,
            sources=list(draft.citations),
            latency_ms=0,
            token_cost=0,
        )
        if request.expected_terms and score.answer_term_recall < 1.0:
            issues.append("missing expected terms")

        passed = not issues
        return StudyVerification(
            passed=passed,
            needs_review=not passed,
            confidence=min(evidence.confidence, score.source_recall, score.answer_term_recall),
            issues=tuple(issues),
            source_recall=score.source_recall,
            answer_term_recall=score.answer_term_recall,
        )
```

- [ ] **Step 4: Run generator/verifier tests**

Run:

```bash
pytest tests/test_study_agent_generator_verifier.py tests/test_study_agent_contracts.py tests/test_study_agent_evidence.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit generator and verifier**

Run:

```bash
git add src/services/study_agent.py tests/test_study_agent_generator_verifier.py
git commit -m "feat: generate and verify study agent drafts"
```

## Task 4: Study Agent Orchestrator

**Files:**
- Modify: `src/services/study_agent.py`
- Test: `tests/test_study_agent_orchestrator.py`

- [ ] **Step 1: Write failing orchestrator tests**

Create `tests/test_study_agent_orchestrator.py`:

```python
import pytest

from src.knowledge.knowledge_graph import KnowledgeGraph, KnowledgePoint
from src.services.rag_router import RetrievalMode
from src.services.rag_service import RAGService
from src.services.study_agent import (
    EvidenceCollector,
    StudyAgentOrchestrator,
    StudyContentGenerator,
    StudyTarget,
    StudyVerifier,
)


def _orchestrator() -> StudyAgentOrchestrator:
    rag = RAGService()
    rag.index_chunks(
        [
            {
                "content": "导数描述函数的变化率。",
                "source": "calculus:derivative",
                "metadata": {"concept_id": "kp-derivative"},
            }
        ]
    )
    graph = KnowledgeGraph()
    graph.add_point(
        KnowledgePoint(
            id="kp-derivative",
            name="Derivative",
            description="Rate of change",
            category="calculus",
            metadata={"aliases": ["导数"]},
        )
    )
    return StudyAgentOrchestrator(
        evidence_collector=EvidenceCollector(rag_service=rag, graph=graph),
        generator=StudyContentGenerator(),
        verifier=StudyVerifier(),
    )


@pytest.mark.asyncio
async def test_orchestrator_runs_answer_pipeline_with_trace():
    result = await _orchestrator().run(
        {
            "query": "什么是导数？",
            "target": "answer",
            "expected_terms": ["变化率"],
        }
    )

    assert result.request.target == StudyTarget.ANSWER
    assert result.plan.mode == RetrievalMode.SIMPLE
    assert result.evidence.sources == ("calculus:derivative",)
    assert "导数描述函数的变化率" in result.draft.content
    assert result.verification.passed is True
    assert result.audit_metadata == {
        "mode": "simple_rag",
        "target": "answer",
        "needs_review": False,
        "source_count": 1,
        "chunk_count": 1,
    }


@pytest.mark.asyncio
async def test_orchestrator_honors_preferred_mode_for_question_request():
    result = await _orchestrator().run(
        {
            "query": "请生成一道关于导数的题",
            "target": "question",
            "preferred_mode": "agentic_rag",
            "budget": "high",
        }
    )

    assert result.plan.mode == RetrievalMode.AGENTIC
    assert "generate_question" in result.plan.steps
    assert "### Practice Question" in result.draft.content


@pytest.mark.asyncio
async def test_orchestrator_returns_review_needed_for_no_evidence():
    result = await _orchestrator().run({"query": "矩阵分解是什么？"})

    assert result.verification.passed is False
    assert result.verification.needs_review is True
    assert result.evidence.confidence == 0.0
```

- [ ] **Step 2: Run orchestrator tests and verify red**

Run:

```bash
pytest tests/test_study_agent_orchestrator.py -q
```

Expected: fail with `ImportError` for `StudyAgentOrchestrator`.

- [ ] **Step 3: Add orchestrator implementation**

Append this code to `src/services/study_agent.py`:

```python
from src.services.rag_router import RAGStrategyRouter


class StudyAgentOrchestrator:
    def __init__(
        self,
        *,
        evidence_collector: EvidenceCollector,
        generator: StudyContentGenerator | None = None,
        verifier: StudyVerifier | None = None,
        router: RAGStrategyRouter | None = None,
    ) -> None:
        self.evidence_collector = evidence_collector
        self.generator = generator or StudyContentGenerator()
        self.verifier = verifier or StudyVerifier()
        self.router = router or RAGStrategyRouter()

    async def run(self, payload: dict[str, Any]) -> StudyAgentResult:
        request = normalize_study_request(payload)
        plan = self._plan(request)
        evidence = await self.evidence_collector.collect(request, mode=plan.mode)
        draft = self.generator.generate(request, evidence)
        verification = self.verifier.verify(request, evidence, draft)
        return StudyAgentResult(
            request=request,
            plan=plan,
            evidence=evidence,
            draft=draft,
            verification=verification,
            audit_metadata={
                "mode": plan.mode.value,
                "target": request.target.value,
                "needs_review": verification.needs_review,
                "source_count": len(evidence.sources),
                "chunk_count": len(evidence.chunks),
            },
        )

    def _plan(self, request: StudyRequest) -> StudyPlan:
        decision = (
            self.router.route(request.query)
            if request.preferred_mode is None
            else None
        )
        mode = request.preferred_mode or decision.mode
        reason = decision.reason if decision is not None else "preferred mode requested"
        estimated_cost = decision.estimated_cost if decision is not None else self._cost_for(mode)
        if request.budget == StudyBudget.LOW and mode == RetrievalMode.AGENTIC:
            mode = RetrievalMode.SIMPLE
            reason = "low budget prevents agentic retrieval"
            estimated_cost = "low"

        steps = self._steps_for(mode, request)
        return StudyPlan(
            mode=mode,
            reason=reason,
            steps=steps,
            estimated_cost=estimated_cost,
            fallbacks=self._fallbacks_for(mode),
        )

    def _steps_for(self, mode: RetrievalMode, request: StudyRequest) -> tuple[str, ...]:
        if mode == RetrievalMode.AGENTIC:
            steps = ["retrieve", "expand", "synthesize", "verify"]
            if request.target == StudyTarget.QUESTION:
                steps.append("generate_question")
            return tuple(steps)
        if mode == RetrievalMode.GRAPH:
            return ("match_seed_concepts", "expand_graph_neighbors", "recover_chunks")
        return ("retrieve_chunks",)

    def _fallbacks_for(self, mode: RetrievalMode) -> tuple[RetrievalMode, ...]:
        if mode == RetrievalMode.AGENTIC:
            return (RetrievalMode.GRAPH, RetrievalMode.SIMPLE)
        if mode == RetrievalMode.GRAPH:
            return (RetrievalMode.SIMPLE,)
        return ()

    def _cost_for(self, mode: RetrievalMode) -> str:
        if mode == RetrievalMode.AGENTIC:
            return "high"
        if mode == RetrievalMode.GRAPH:
            return "medium"
        return "low"
```

- [ ] **Step 4: Run orchestrator tests**

Run:

```bash
pytest tests/test_study_agent_orchestrator.py tests/test_study_agent_generator_verifier.py tests/test_study_agent_evidence.py tests/test_rag_router.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit orchestrator**

Run:

```bash
git add src/services/study_agent.py tests/test_study_agent_orchestrator.py
git commit -m "feat: orchestrate study agent pipeline"
```

## Task 5: Authenticated Study Agent API

**Files:**
- Create: `src/api/routes/study_agent.py`
- Modify: `src/api/app.py`
- Test: `tests/test_study_agent_api.py`

- [ ] **Step 1: Write failing API tests**

Create `tests/test_study_agent_api.py`:

```python
from dataclasses import dataclass
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.app import create_app
from src.db.models import Base, UserRecord
from src.security.auth import hash_password
from src.services.rag_router import RetrievalMode
from src.services.rag_service import Chunk
from src.services.study_agent import (
    EvidenceBundle,
    StudyAgentResult,
    StudyDraft,
    StudyPlan,
    StudyRequest,
    StudyTarget,
    StudyVerification,
)


@dataclass
class FakeStudyAgentOrchestrator:
    payloads: list[dict]

    async def run(self, payload: dict) -> StudyAgentResult:
        self.payloads.append(payload)
        request = StudyRequest(query=payload["query"], target=StudyTarget.ANSWER)
        evidence = EvidenceBundle(
            mode=RetrievalMode.SIMPLE,
            chunks=(Chunk(content="导数描述函数的变化率。", source="calculus:derivative"),),
            sources=("calculus:derivative",),
            concept_ids=("kp-derivative",),
            confidence=0.8,
            reason="simple token-overlap retrieval",
        )
        return StudyAgentResult(
            request=request,
            plan=StudyPlan(
                mode=RetrievalMode.SIMPLE,
                reason="definition or direct lookup query",
                steps=("retrieve_chunks",),
                estimated_cost="low",
            ),
            evidence=evidence,
            draft=StudyDraft(
                target=StudyTarget.ANSWER,
                content="导数描述函数的变化率。",
                citations=("calculus:derivative",),
                used_chunk_count=1,
            ),
            verification=StudyVerification(
                passed=True,
                needs_review=False,
                confidence=0.8,
                issues=(),
                source_recall=1.0,
                answer_term_recall=1.0,
            ),
            audit_metadata={
                "mode": "simple_rag",
                "target": "answer",
                "needs_review": False,
                "source_count": 1,
                "chunk_count": 1,
            },
        )


def _client(tmp_path: Path):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        session.add(
            UserRecord(
                id="user-1",
                email="user@example.com",
                password_hash=hash_password("password-123"),
                role="user",
                is_active=True,
            )
        )
        session.commit()
    orchestrator = FakeStudyAgentOrchestrator(payloads=[])
    app = create_app(
        session_factory=Session,
        secret_key="test-secret",
        allow_dev_user_header=False,
        study_agent_orchestrator=orchestrator,
    )
    return TestClient(app), orchestrator


def _login(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"email": "user@example.com", "password": "password-123"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_study_agent_query_requires_authentication(tmp_path: Path):
    client, _orchestrator = _client(tmp_path)

    response = client.post("/api/study-agent/query", json={"query": "什么是导数？"})

    assert response.status_code == 401


def test_study_agent_query_returns_trace_payload(tmp_path: Path):
    client, orchestrator = _client(tmp_path)
    headers = _login(client)

    response = client.post(
        "/api/study-agent/query",
        json={"query": "什么是导数？", "expected_terms": ["变化率"]},
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["request"]["query"] == "什么是导数？"
    assert payload["plan"]["mode"] == "simple_rag"
    assert payload["evidence"]["sources"] == ["calculus:derivative"]
    assert payload["draft"]["citations"] == ["calculus:derivative"]
    assert payload["verification"]["passed"] is True
    assert orchestrator.payloads == [{"query": "什么是导数？", "expected_terms": ["变化率"]}]


def test_study_agent_query_validates_payload(tmp_path: Path):
    client, _orchestrator = _client(tmp_path)
    headers = _login(client)

    response = client.post(
        "/api/study-agent/query",
        json={"query": "   "},
        headers=headers,
    )

    assert response.status_code == 422
```

- [ ] **Step 2: Run API tests and verify red**

Run:

```bash
pytest tests/test_study_agent_api.py -q
```

Expected: fail because `create_app()` does not accept `study_agent_orchestrator` or route does not exist.

- [ ] **Step 3: Create study-agent route**

Create `src/api/routes/study_agent.py`:

```python
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from src.api.request_context import get_user_context


class StudyAgentQueryRequest(BaseModel):
    query: str = Field(min_length=1)
    target: str | None = None
    document_ids: list[str] | None = None
    preferred_mode: str | None = None
    budget: str | None = None
    expected_terms: list[str] | None = None

    @field_validator("query")
    @classmethod
    def query_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be empty")
        return value


router = APIRouter(prefix="/api/study-agent", tags=["study-agent"])


@router.post("/query")
async def query_study_agent(
    payload: StudyAgentQueryRequest,
    request: Request,
) -> dict[str, Any]:
    get_user_context(request)
    orchestrator = getattr(request.app.state, "study_agent_orchestrator", None)
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Study agent is not configured")
    try:
        result = await orchestrator.run(payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _to_jsonable(result)


def _to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {key: _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    return value
```

- [ ] **Step 4: Wire route and app state**

Modify `src/api/app.py`:

1. Add import near other route imports:

```python
from src.api.routes.study_agent import router as study_agent_router
```

2. Add keyword argument to `create_app` signature:

```python
    study_agent_orchestrator: Any | None = None,
```

3. Set app state after `app.state.feedback_service = ...`:

```python
    app.state.study_agent_orchestrator = study_agent_orchestrator
```

4. Include router after existing product routers:

```python
    app.include_router(study_agent_router)
```

- [ ] **Step 5: Run API tests**

Run:

```bash
pytest tests/test_study_agent_api.py tests/test_mvp8_api_auth_audit.py -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit API route**

Run:

```bash
git add src/api/app.py src/api/routes/study_agent.py tests/test_study_agent_api.py
git commit -m "feat: expose study agent query api"
```

## Task 6: Full Verification And Docs Sync

**Files:**
- Modify: `SPEC.md`
- Modify: `README.md`
- Test: existing suite

- [ ] **Step 1: Update `SPEC.md` MVP status**

Modify the top implementation status section of `SPEC.md` to add an MVP-9 note:

```markdown
## 0. 当前实现状态：MVP-9 Agentic Study Pipeline 规划中

MVP-9 的目标是在 MVP-8 正式产品底座之上补齐可追踪的 agent 学习工作流：自动路由 simple RAG、Graph RAG Lite 和 Agentic RAG，收集 evidence bundle，生成带引用的答案/题目/提纲片段，并通过 verifier 标记低置信度或需要人工审核的结果。

当前实现计划见 `docs/superpowers/specs/2026-06-24-agentic-study-pipeline-design.md` 和 `docs/superpowers/plans/2026-06-24-agentic-study-pipeline.md`。MVP-9 第一阶段保持确定性、可测试、可审计；真实 LLM provider 优化、Hermes 自进化和大规模向量数据库优化仍为后续阶段。
```

Keep the existing MVP-8 section below it for historical status.

- [ ] **Step 2: Update `README.md` roadmap**

Add an MVP-9 roadmap subsection near the MVP/status area:

```markdown
### MVP-9 Agentic Study Pipeline

Next implementation phase: a deterministic, traceable study-agent workflow that routes study queries across simple RAG, Graph RAG Lite, and Agentic RAG; gathers evidence; generates cited study content; and verifies whether the result should be returned directly or marked for review.
```

- [ ] **Step 3: Run targeted study-agent tests**

Run:

```bash
pytest tests/test_study_agent_contracts.py tests/test_study_agent_evidence.py tests/test_study_agent_generator_verifier.py tests/test_study_agent_orchestrator.py tests/test_study_agent_api.py -q
```

Expected: all selected tests pass.

- [ ] **Step 4: Run full backend tests**

Run:

```bash
python -m pytest -q
```

Expected: full backend suite passes with the existing expected xfail count.

- [ ] **Step 5: Run frontend build**

Run:

```bash
cd frontend && npm run build
```

Expected: TypeScript and Vite production build succeeds.

- [ ] **Step 6: Run compose config validation**

Run:

```bash
docker compose config
```

Expected: Compose config renders successfully.

- [ ] **Step 7: Commit docs and verification sync**

Run:

```bash
git add SPEC.md README.md
git commit -m "docs: sync mvp9 study agent roadmap"
```

## Final Review Requirements

After all tasks are implemented:

- [ ] **Spec review:** Compare implementation against `docs/superpowers/specs/2026-06-24-agentic-study-pipeline-design.md` and this plan. Confirm each acceptance criterion maps to passing tests or implemented behavior.
- [ ] **Quality review:** Inspect `src/services/study_agent.py`, `src/api/routes/study_agent.py`, and all new tests for naming, boundary clarity, deterministic behavior, audit-safe metadata, and regression risk.
- [ ] **Final verification:** Re-run:

```bash
python -m pytest -q
npm --prefix frontend run build
docker compose config
```

- [ ] **Final integration decision:** Use the finishing branch workflow after verification passes.
