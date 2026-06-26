import pytest

from src.knowledge.knowledge_graph import KnowledgeGraph, KnowledgePoint, Relationship
from src.services.study_agent import EvidenceCollector, StudyRequest
from src.services.graph_rag import GraphRAGLiteRetriever
from src.services.rag_router import RetrievalMode
from src.services.rag_service import Chunk, RAGService


@pytest.mark.asyncio
async def test_graph_rag_expands_related_knowledge_points():
    graph = KnowledgeGraph()
    graph.add_point(
        KnowledgePoint(
            id="kp1",
            name="Derivative",
            description="Rate of change",
            category="concept",
        )
    )
    graph.add_point(
        KnowledgePoint(
            id="kp2",
            name="Gradient",
            description="Vector of partial derivatives",
            category="concept",
        )
    )
    graph.add_relationship(
        Relationship(
            source_id="kp1",
            target_id="kp2",
            relation_type="generalizes_to",
        )
    )

    chunks = [
        Chunk(content="Derivative is rate of change", source="calculus:derivative"),
        Chunk(
            content="Gradient extends derivatives to multivariable functions",
            source="calculus:gradient",
        ),
    ]

    result = await GraphRAGLiteRetriever(graph, chunks).retrieve("Derivative 的相关概念")

    assert any("Gradient" in item.content for item in result.chunks)
    assert result.mode == "graph_rag_lite"


@pytest.mark.asyncio
async def test_graph_rag_returns_empty_result_without_seed_match():
    graph = KnowledgeGraph()
    graph.add_point(
        KnowledgePoint(
            id="kp1",
            name="Derivative",
            description="Rate of change",
            category="concept",
        )
    )

    result = await GraphRAGLiteRetriever(graph, []).retrieve("unrelated query")

    assert result.chunks == []
    assert result.confidence == 0.0
    assert result.expanded_point_ids == []
    assert result.reason == "no graph seed matched"


@pytest.mark.asyncio
async def test_graph_rag_respects_max_hops_and_top_k():
    graph = KnowledgeGraph()
    graph.add_point(
        KnowledgePoint(
            id="kp1",
            name="Derivative",
            description="Rate of change",
            category="concept",
        )
    )
    graph.add_point(
        KnowledgePoint(
            id="kp2",
            name="Gradient",
            description="Vector derivative",
            category="concept",
        )
    )
    graph.add_relationship(
        Relationship(
            source_id="kp1",
            target_id="kp2",
            relation_type="generalizes_to",
        )
    )
    chunks = [
        Chunk(content="Derivative definition", source="calculus:derivative"),
        Chunk(content="Derivative example", source="calculus:example"),
        Chunk(content="Gradient definition", source="calculus:gradient"),
    ]

    no_hop_result = await GraphRAGLiteRetriever(graph, chunks).retrieve("Derivative", max_hops=0)
    top_one_result = await GraphRAGLiteRetriever(graph, chunks).retrieve("Derivative", top_k=1)

    assert "kp2" not in no_hop_result.expanded_point_ids
    assert all("Gradient" not in chunk.content for chunk in no_hop_result.chunks)
    assert len(top_one_result.chunks) == 1


@pytest.mark.asyncio
async def test_graph_rag_does_not_seed_on_common_name_tokens():
    graph = KnowledgeGraph()
    graph.add_point(
        KnowledgePoint(
            id="kp-law",
            name="Law of Large Numbers",
            description="Convergence theorem",
            category="statistics",
        )
    )

    result = await GraphRAGLiteRetriever(graph, []).retrieve("What is the role of variance?")

    assert result.expanded_point_ids == []
    assert result.reason == "no graph seed matched"


@pytest.mark.asyncio
async def test_graph_rag_matches_point_aliases_for_chinese_queries():
    graph = KnowledgeGraph()
    graph.add_point(
        KnowledgePoint(
            id="kp1",
            name="Derivative",
            description="Rate of change",
            category="concept",
            metadata={"aliases": ["导数"]},
        )
    )
    chunks = [Chunk(content="Derivative is rate of change", source="calculus:derivative")]

    result = await GraphRAGLiteRetriever(graph, chunks).retrieve("导数是什么？")

    assert result.expanded_point_ids == ["kp1"]
    assert result.chunks[0].source == "calculus:derivative"


@pytest.mark.asyncio
async def test_graph_rag_returns_deterministic_bfs_expansion_order():
    graph = KnowledgeGraph()
    for point_id, name in [
        ("kp1", "Derivative"),
        ("kp2", "Gradient"),
        ("kp3", "Jacobian"),
    ]:
        graph.add_point(
            KnowledgePoint(
                id=point_id,
                name=name,
                description=name,
                category="concept",
            )
        )
    graph.add_relationship(Relationship("kp1", "kp2", "related"))
    graph.add_relationship(Relationship("kp1", "kp3", "related"))
    graph.add_relationship(Relationship("kp2", "kp1", "related"))

    result = await GraphRAGLiteRetriever(graph, []).retrieve("Derivative")

    assert result.expanded_point_ids == ["kp1", "kp2", "kp3"]


@pytest.mark.asyncio
async def test_graph_rag_returns_scored_chunk_copies():
    graph = KnowledgeGraph()
    graph.add_point(
        KnowledgePoint(
            id="kp1",
            name="Derivative",
            description="Rate of change",
            category="concept",
        )
    )
    original = Chunk(
        content="Derivative is rate of change",
        source="calculus:derivative",
        metadata={"page": 1},
    )

    result = await GraphRAGLiteRetriever(graph, [original]).retrieve("Derivative")

    assert result.chunks[0] is not original
    assert result.chunks[0].score > 0
    result.chunks[0].metadata["page"] = 99
    assert original.metadata["page"] == 1


@pytest.mark.asyncio
async def test_graph_rag_normalizes_negative_limits():
    graph = KnowledgeGraph()
    graph.add_point(
        KnowledgePoint(
            id="kp1",
            name="Derivative",
            description="Rate of change",
            category="concept",
        )
    )
    chunks = [
        Chunk(content="Derivative content", source="calculus:derivative"),
        Chunk(content="Derivative example", source="calculus:example"),
    ]

    result = await GraphRAGLiteRetriever(graph, chunks).retrieve(
        "Derivative", max_hops=-1, top_k=-1
    )

    assert result.chunks == []
    assert result.expanded_point_ids == ["kp1"]
    assert result.reason == "top_k must be positive"


@pytest.mark.asyncio
async def test_graph_rag_reports_seed_match_without_recovered_chunks():
    graph = KnowledgeGraph()
    graph.add_point(
        KnowledgePoint(
            id="kp1",
            name="Derivative",
            description="Rate of change",
            category="concept",
        )
    )
    chunks = [Chunk(content="Unrelated content", source="notes:other")]

    result = await GraphRAGLiteRetriever(graph, chunks).retrieve("Derivative")

    assert result.expanded_point_ids == ["kp1"]
    assert result.chunks == []
    assert result.reason == "matched graph seed but no chunks recovered"


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


@pytest.mark.asyncio
async def test_evidence_collector_threads_graph_metadata_into_bundle():
    graph = KnowledgeGraph()
    graph.add_point(KnowledgePoint("kp1", "Derivative", "Rate", "concept"))
    chunks = [Chunk(content="Derivative is rate of change", source="calculus:chunk:1")]
    rag_service = RAGService()
    rag_service._chunks = chunks
    collector = EvidenceCollector(rag_service=rag_service, graph=graph)

    bundle = await collector.collect(
        StudyRequest(query="Derivative"),
        mode=RetrievalMode.GRAPH,
    )

    assert bundle.mode == RetrievalMode.GRAPH
    assert bundle.metadata == {
        "seed_count": 1,
        "expanded_count": 1,
        "hop_count": 2,
        "fallback_reason": None,
    }
    assert "content" not in bundle.metadata
    assert "query" not in bundle.metadata
    assert "snippet" not in bundle.metadata


@pytest.mark.asyncio
async def test_evidence_collector_clears_graph_fallback_when_concept_recovery_succeeds():
    graph = KnowledgeGraph()
    graph.add_point(KnowledgePoint("kp1", "Derivative", "Rate", "concept"))
    rag_service = RAGService()
    rag_service._chunks = [
        Chunk(
            content="Rate of change notes without the seed name",
            source="calculus:chunk:1",
            metadata={"concept_id": "kp1"},
        )
    ]
    collector = EvidenceCollector(rag_service=rag_service, graph=graph)

    bundle = await collector.collect(
        StudyRequest(query="Derivative"),
        mode=RetrievalMode.GRAPH,
    )

    assert bundle.mode == RetrievalMode.GRAPH
    assert bundle.sources == ("calculus:chunk:1",)
    assert bundle.reason == "matched concepts and expanded graph neighbors"
    assert bundle.metadata == {
        "seed_count": 1,
        "expanded_count": 1,
        "hop_count": 2,
        "fallback_reason": None,
    }


@pytest.mark.asyncio
async def test_agentic_bundle_preserves_graph_metadata_when_graph_evidence_succeeds():
    graph = KnowledgeGraph()
    graph.add_point(KnowledgePoint("kp1", "Derivative", "Rate", "concept"))
    chunks = [Chunk(content="Derivative is rate of change", source="calculus:chunk:1")]
    rag_service = RAGService()
    rag_service._chunks = chunks
    collector = EvidenceCollector(rag_service=rag_service, graph=graph)

    bundle = await collector.collect(
        StudyRequest(query="Derivative"),
        mode=RetrievalMode.AGENTIC,
    )

    assert bundle.mode == RetrievalMode.AGENTIC
    assert bundle.metadata == {
        "seed_count": 1,
        "expanded_count": 1,
        "hop_count": 2,
        "fallback_reason": None,
        "planned_step_count": 4,
        "executed_step_count": 4,
        "step_budget_exhausted": False,
    }
