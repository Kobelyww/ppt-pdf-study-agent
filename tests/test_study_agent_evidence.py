import pytest

from src.knowledge.knowledge_graph import KnowledgeGraph, KnowledgePoint, Relationship
from src.services.rag_router import RetrievalMode
from src.services.rag_service import RAGService
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
