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
