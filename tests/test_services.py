import pytest
from src.services.rag_service import RAGService, QueryType, RetrievalStrategy


def test_rag_service_initialization():
    """测试RAG服务初始化"""
    rag = RAGService()
    assert rag.vector_store is None
    assert rag.knowledge_graph is None


def test_query_type_detection():
    """测试查询类型检测"""
    rag = RAGService()
    assert rag.detect_query_type("什么是机器学习？") == QueryType.DEFINITION
    assert rag.detect_query_type("举个例子") == QueryType.EXAMPLE


def test_retrieval_strategy_selection():
    """测试检索策略选择"""
    rag = RAGService()
    strategy = rag.select_strategy("简单事实查询", QueryType.DEFINITION)
    assert strategy == RetrievalStrategy.SIMPLE_RAG


def test_rag_service_indexes_and_retrieves_chunks():
    rag = RAGService()
    rag.index_chunks(
        [
            {"content": "Derivative is rate of change", "source": "doc:1"},
            {"content": "Matrix multiplication combines rows and columns", "source": "doc:2"},
        ]
    )

    response = rag.retrieve("rate of change", top_k=1)

    assert response[0].source == "doc:1"
    assert "Derivative" in response[0].content


def test_rag_service_rejects_invalid_chunk_inputs():
    rag = RAGService()

    with pytest.raises(TypeError, match="chunks must be a list"):
        rag.index_chunks({"content": "Derivative"})

    with pytest.raises(TypeError, match="chunk item must be a dict"):
        rag.index_chunks(["Derivative"])

    with pytest.raises(TypeError, match="metadata must be a dict"):
        rag.index_chunks(
            [
                {"content": "Derivative is rate of change", "metadata": "doc:1"},
            ]
        )


def test_rag_service_retrieve_empty_and_limits():
    rag = RAGService()
    rag.index_chunks(
        [
            {"content": "Derivative is rate of change", "source": "doc:1"},
            {"content": "Change happens over time", "source": "doc:2"},
            {"content": "Matrix multiplication combines rows and columns", "source": "doc:3"},
        ]
    )

    assert rag.retrieve("", top_k=1) == []
    assert rag.retrieve("change", top_k=0) == []
    assert rag.retrieve("no matching token", top_k=1) == []

    response = rag.retrieve("change", top_k=1)

    assert len(response) == 1


def test_rag_service_metadata_is_copied():
    rag = RAGService()
    metadata = {"page": 1}
    rag.index_chunks(
        [
            {
                "content": "Derivative is rate of change",
                "source": "doc:1",
                "metadata": metadata,
            },
        ]
    )
    metadata["page"] = 2

    first_response = rag.retrieve("Derivative", top_k=1)
    first_response[0].metadata["page"] = 3

    second_response = rag.retrieve("Derivative", top_k=1)

    assert second_response[0].metadata["page"] == 1


@pytest.mark.asyncio
async def test_rag_service_simple_query_answers_from_retrieved_chunks():
    rag = RAGService()
    rag.index_chunks(
        [
            {"content": "Derivative is the rate of change of a function.", "source": "doc:1"},
            {"content": "Matrix multiplication combines rows and columns.", "source": "doc:2"},
        ]
    )

    response = await rag.query("rate of change")

    assert "Derivative" in response.answer
    assert "rate of change" in response.answer
    assert "doc:1" in response.sources
    assert response.chunks
    assert response.confidence > 0
