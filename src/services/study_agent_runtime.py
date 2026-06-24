from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.knowledge.knowledge_graph import KnowledgeGraph
from src.services.agentic_rag import AgenticRAGPlanner
from src.services.rag_router import RAGStrategyRouter
from src.services.rag_service import RAGService
from src.services.study_agent import (
    EvidenceCollector,
    StudyAgentOrchestrator,
    StudyContentGenerator,
    StudyVerifier,
    normalize_study_request,
)
from src.services.study_agent_documents import (
    StudyAgentDocumentError,
    StudyDocumentChunker,
    StudyDocumentEvidence,
    StudyDocumentEvidenceSource,
)


class StudyAgentRuntimeService:
    def __init__(
        self,
        *,
        session_factory,
        evidence_source: StudyDocumentEvidenceSource | None = None,
        chunker: StudyDocumentChunker | None = None,
        graph: KnowledgeGraph | None = None,
        graph_factory: Callable[[tuple[StudyDocumentEvidence, ...]], KnowledgeGraph | None]
        | None = None,
        agentic_planner: AgenticRAGPlanner | None = None,
        generator: StudyContentGenerator | None = None,
        verifier: StudyVerifier | None = None,
        router: RAGStrategyRouter | None = None,
        top_k: int = 5,
    ) -> None:
        self.session_factory = session_factory
        self.evidence_source = evidence_source or StudyDocumentEvidenceSource(session_factory)
        self.chunker = chunker or StudyDocumentChunker()
        self.graph = graph
        self.graph_factory = graph_factory
        self.agentic_planner = agentic_planner
        self.generator = generator
        self.verifier = verifier
        self.router = router
        self.top_k = top_k

    async def run(self, payload: dict[str, Any]):
        request = normalize_study_request(payload)
        if not request.authenticated_user_id:
            raise StudyAgentDocumentError(
                status_code=422,
                code="authentication_required",
                detail="Study Agent requires an authenticated user.",
            )

        evidence = self.evidence_source.load(
            owner_id=request.authenticated_user_id,
            document_ids=request.document_ids,
        )
        chunks = self.chunker.chunk(evidence)
        if not chunks:
            raise StudyAgentDocumentError(
                status_code=422,
                code="document_evidence_missing",
                detail="Processed document evidence is unavailable.",
            )

        rag_service = RAGService()
        rag_service.index_chunks(chunks)
        collector = EvidenceCollector(
            rag_service=rag_service,
            graph=self._graph_for(evidence),
            agentic_planner=self.agentic_planner,
            top_k=self.top_k,
        )
        orchestrator = StudyAgentOrchestrator(
            evidence_collector=collector,
            generator=self.generator,
            verifier=self.verifier,
            router=self.router,
        )
        return await orchestrator.run(payload)

    def _graph_for(self, evidence: tuple[StudyDocumentEvidence, ...]) -> KnowledgeGraph | None:
        if self.graph_factory is not None:
            return self.graph_factory(evidence)
        return self.graph
