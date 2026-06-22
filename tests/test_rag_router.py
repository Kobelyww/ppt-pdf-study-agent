from src.services.rag_router import RAGStrategyRouter, RetrievalMode


def test_routes_definition_to_simple_rag():
    decision = RAGStrategyRouter().route("什么是特征值？")

    assert decision.mode == RetrievalMode.SIMPLE
    assert decision.estimated_cost == "low"


def test_routes_prerequisite_to_graph_rag():
    decision = RAGStrategyRouter().route("学习特征值前需要掌握什么？")

    assert decision.mode == RetrievalMode.GRAPH
    assert decision.estimated_cost == "medium"


def test_routes_synthesis_to_agentic_rag():
    decision = RAGStrategyRouter().route("基于第2章和第4章出一道综合题")

    assert decision.mode == RetrievalMode.AGENTIC
    assert decision.estimated_cost == "high"


def test_routes_explicit_question_generation_to_agentic_rag():
    decision = RAGStrategyRouter().route("请生成一道关于第2章的题")

    assert decision.mode == RetrievalMode.AGENTIC
    assert decision.estimated_cost == "high"


def test_routes_cross_chapter_query_to_agentic_rag():
    decision = RAGStrategyRouter().route("跨章节总结特征值和矩阵分解")

    assert decision.mode == RetrievalMode.AGENTIC
    assert decision.estimated_cost == "high"


def test_routes_ambiguous_query_to_simple_rag_by_default():
    decision = RAGStrategyRouter().route("特征值")

    assert decision.mode == RetrievalMode.SIMPLE
    assert decision.confidence >= 0.7


def test_routes_single_chapter_direct_lookup_to_simple_rag():
    decision = RAGStrategyRouter().route("第2章讲什么？")

    assert decision.mode == RetrievalMode.SIMPLE
    assert decision.estimated_cost == "low"
