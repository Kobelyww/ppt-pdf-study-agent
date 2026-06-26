from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any

from src.knowledge.knowledge_graph import KnowledgeGraph
from src.services.agentic_rag import AgenticRAGPlanner
from src.services.graph_rag import GraphRAGLiteRetriever
from src.services.rag_evaluation import RAGEvalCase, RAGEvaluator
from src.services.rag_router import RAGStrategyRouter, RetrievalMode
from src.services.rag_service import Chunk, RAGService


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
    authenticated_user_id: str | None = None
    request_id: str | None = None


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
        if evidence.sources and score.source_recall < 1.0:
            issues.append("missing expected sources")
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
        self.graph = graph
        self.agentic_planner = agentic_planner or AgenticRAGPlanner()
        self.top_k = top_k

    async def collect(self, request: StudyRequest, mode: RetrievalMode) -> EvidenceBundle:
        try:
            retrieval_mode = RetrievalMode(mode)
        except ValueError as exc:
            raise ValueError(f"unsupported retrieval mode: {mode}") from exc

        if retrieval_mode == RetrievalMode.GRAPH:
            return await self._graph_bundle(request)
        if retrieval_mode == RetrievalMode.AGENTIC:
            return await self._agentic_bundle(request)
        if retrieval_mode != RetrievalMode.SIMPLE:
            raise ValueError(f"unsupported retrieval mode: {mode}")
        return self._simple_bundle(request)

    def _simple_bundle(
        self,
        request: StudyRequest,
        fallback_reason: str | None = None,
    ) -> EvidenceBundle:
        scoped_service = self._scoped_rag_service(request)
        chunks = scoped_service.retrieve(request.query, top_k=self.top_k)
        if not chunks:
            chunks = self._substring_fallback_chunks(request)

        return EvidenceBundle(
            mode=RetrievalMode.SIMPLE,
            chunks=tuple(chunks),
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

    def _substring_fallback_chunks(self, request: StudyRequest) -> list[Chunk]:
        terms = _query_terms(request.query)
        if not terms or self.top_k <= 0:
            return []

        ranked: list[tuple[int, Chunk]] = []
        for chunk in self._scoped_chunks(request):
            content = chunk.content.lower()
            source = chunk.source.lower()
            match_score = max(
                (
                    2
                    if content.startswith(term)
                    else 1
                    if term in content or term in source
                    else 0
                )
                for term in terms
            )
            if match_score <= 0:
                continue

            ranked.append(
                (
                    match_score,
                    Chunk(
                        content=chunk.content,
                        source=chunk.source,
                        metadata=chunk.metadata.copy(),
                        score=max(chunk.score, 0.5),
                    ),
                )
            )

        ranked.sort(key=lambda item: item[0], reverse=True)
        max_score = max((score for score, _ in ranked), default=0)
        return [chunk for score, chunk in ranked if score == max_score][: self.top_k]

    async def _graph_bundle(self, request: StudyRequest) -> EvidenceBundle:
        if self.graph is None:
            return self._simple_bundle(request, fallback_reason="no graph configured")

        result = await GraphRAGLiteRetriever(self.graph, self._scoped_chunks(request)).retrieve(
            request.query,
            top_k=self.top_k,
        )
        if result.reason == "no graph seed matched":
            return self._simple_bundle(request, fallback_reason=result.reason)

        chunks = result.chunks
        if result.expanded_point_ids:
            chunks = self._recover_chunks_by_concept_id(
                request=request,
                point_ids=result.expanded_point_ids,
                existing_chunks=chunks,
                scoped_chunks=self._scoped_chunks(request),
            )
        if not chunks:
            return self._simple_bundle(request, fallback_reason=result.reason)

        return EvidenceBundle(
            mode=RetrievalMode.GRAPH,
            chunks=tuple(chunks),
            sources=_unique(chunk.source for chunk in chunks if chunk.source),
            concept_ids=tuple(result.expanded_point_ids),
            confidence=result.confidence if result.chunks else _average_score(chunks),
            reason=(
                "matched concepts and expanded graph neighbors"
                if chunks
                else result.reason
            ),
        )

    async def _agentic_bundle(self, request: StudyRequest) -> EvidenceBundle:
        if request.budget == StudyBudget.LOW:
            return self._simple_bundle(
                request,
                fallback_reason="low budget prevents agentic retrieval",
            )

        self.agentic_planner.plan(request.query)
        if self.graph is not None:
            graph_bundle = await self._graph_bundle(request)
            if graph_bundle.mode == RetrievalMode.GRAPH and graph_bundle.chunks:
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

    def _recover_chunks_by_concept_id(
        self,
        *,
        request: StudyRequest,
        point_ids: list[str],
        existing_chunks: list[Chunk],
        scoped_chunks: list[Chunk] | None = None,
    ) -> list[Chunk]:
        chunks = list(existing_chunks)
        seen_sources = {chunk.source for chunk in chunks}
        candidate_chunks = scoped_chunks if scoped_chunks is not None else self._scoped_chunks(request)
        for point_id in point_ids:
            if len(chunks) >= self.top_k:
                break
            for chunk in candidate_chunks:
                if chunk.source in seen_sources:
                    continue
                if chunk.metadata.get("concept_id") != point_id:
                    continue
                chunks.append(
                    Chunk(
                        content=chunk.content,
                        source=chunk.source,
                        metadata=chunk.metadata.copy(),
                        score=max(chunk.score, 0.5),
                    )
                )
                seen_sources.add(chunk.source)
                break
        return chunks[: self.top_k]

    def _scoped_rag_service(self, request: StudyRequest) -> RAGService:
        scoped_service = RAGService()
        scoped_service._chunks = self._scoped_chunks(request)
        return scoped_service

    def _scoped_chunks(self, request: StudyRequest) -> list[Chunk]:
        return [
            Chunk(
                content=chunk.content,
                source=chunk.source,
                metadata=chunk.metadata.copy(),
                score=chunk.score,
            )
            for chunk in self.rag_service._chunks
            if self._chunk_allowed(request, chunk)
        ]

    def _chunk_allowed(self, request: StudyRequest, chunk: Chunk) -> bool:
        document_ids = set(request.document_ids)
        document_id = str(chunk.metadata.get("document_id", "")).strip()
        owner_id = str(chunk.metadata.get("owner_id", "")).strip()

        if document_ids and (not document_id or document_id not in document_ids):
            return False

        if request.authenticated_user_id:
            authenticated_user_id = request.authenticated_user_id.strip()
            if owner_id:
                return owner_id == authenticated_user_id
            if document_ids:
                return False

        return True


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
        audit_metadata = {
            "mode": plan.mode.value,
            "target": request.target.value,
            "needs_review": verification.needs_review,
            "source_count": len(evidence.sources),
            "chunk_count": len(evidence.chunks),
        }
        policy_decision = payload.get("policy_decision")
        if isinstance(policy_decision, dict):
            audit_metadata["policy"] = policy_decision
        return StudyAgentResult(
            request=request,
            plan=plan,
            evidence=evidence,
            draft=draft,
            verification=verification,
            audit_metadata=audit_metadata,
        )

    def _plan(self, request: StudyRequest) -> StudyPlan:
        decision = self.router.route(request.query) if request.preferred_mode is None else None
        mode = request.preferred_mode or decision.mode
        reason = decision.reason if decision is not None else "preferred mode requested"
        estimated_cost = decision.estimated_cost if decision is not None else self._cost_for(mode)
        if request.budget == StudyBudget.LOW and mode == RetrievalMode.AGENTIC:
            mode = RetrievalMode.SIMPLE
            reason = "low budget prevents agentic retrieval"
            estimated_cost = "low"

        return StudyPlan(
            mode=mode,
            reason=reason,
            steps=self._steps_for(mode, request),
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
        authenticated_user_id=_optional_nonempty(payload.get("authenticated_user_id")),
        request_id=_optional_nonempty(payload.get("request_id")),
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


def _optional_nonempty(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _unique(values) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for value in values:
        normalized = str(value).strip()
        if normalized:
            seen.setdefault(normalized, None)
    return tuple(seen)


def _average_score(chunks: list[Chunk] | tuple[Chunk, ...]) -> float:
    if not chunks:
        return 0.0
    return min(1.0, sum(max(0.0, chunk.score) for chunk in chunks) / len(chunks))


def _query_terms(query: str) -> tuple[str, ...]:
    terms = re.findall(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]+", query.lower())
    stopwords = {"什么是", "是什么", "什么", "关系", "和", "的", "了", "吗"}
    expanded: list[str] = []
    for term in terms:
        stripped = term.strip()
        if not stripped or stripped in stopwords:
            continue
        expanded.append(stripped)
        if any("\u4e00" <= char <= "\u9fff" for char in stripped):
            expanded.extend(
                stripped[index : index + 2]
                for index in range(max(0, len(stripped) - 1))
            )
    return _unique(expanded)
