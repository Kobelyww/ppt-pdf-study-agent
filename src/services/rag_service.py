from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum
import re


class QueryType(Enum):
    """查询类型"""

    DEFINITION = "definition"
    EXAMPLE = "example"
    CONNECTION = "connection"
    PREREQUISITE = "prerequisite"
    SIMPLE_FACT = "simple_fact"
    COMPLEX_REASONING = "complex_reasoning"


class RetrievalStrategy(Enum):
    """检索策略"""

    SIMPLE_RAG = "simple_rag"
    AGENTIC_RAG = "agentic_rag"
    HYBRID = "hybrid"


@dataclass
class Chunk:
    """文档块"""

    content: str
    source: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    score: float = 0.0


@dataclass
class RAGResponse:
    """RAG响应"""

    answer: str
    sources: List[str] = field(default_factory=list)
    chunks: List[Chunk] = field(default_factory=list)
    confidence: float = 0.0


class RAGService:
    """RAG服务（混合方案）"""

    def __init__(self):
        self.vector_store = None
        self.knowledge_graph = None
        self._chunks: List[Chunk] = []

    def index_chunks(self, chunks: list[dict]) -> None:
        """Index chunks in memory for MVP token-overlap retrieval."""
        if not isinstance(chunks, list):
            raise TypeError("chunks must be a list")

        for raw_chunk in chunks:
            if not isinstance(raw_chunk, dict):
                raise TypeError("chunk item must be a dict")

            content = str(raw_chunk.get("content", "")).strip()
            if not content:
                continue

            source = str(raw_chunk.get("source", ""))
            metadata = raw_chunk.get("metadata") or {}
            if not isinstance(metadata, dict):
                raise TypeError("metadata must be a dict")

            self._chunks.append(Chunk(content=content, source=source, metadata=metadata.copy()))

    def retrieve(self, query: str, top_k: int = 5) -> list[Chunk]:
        """Retrieve indexed chunks using simple token overlap scoring."""
        query_tokens = self._tokenize(query)
        if not query_tokens or top_k <= 0:
            return []

        scored_chunks = []
        for chunk in self._chunks:
            chunk_tokens = self._tokenize(chunk.content)
            overlap = query_tokens & chunk_tokens
            if not overlap:
                continue

            scored_chunks.append(
                Chunk(
                    content=chunk.content,
                    source=chunk.source,
                    metadata=chunk.metadata.copy(),
                    score=len(overlap) / len(query_tokens),
                )
            )

        scored_chunks.sort(key=lambda chunk: chunk.score, reverse=True)
        return scored_chunks[:top_k]

    def _tokenize(self, text: str) -> set[str]:
        return set(re.findall(r"\w+", text.lower()))

    def detect_query_type(self, query: str) -> QueryType:
        """检测查询类型"""
        if "什么是" in query or "定义" in query:
            return QueryType.DEFINITION
        elif "例子" in query or "举例" in query:
            return QueryType.EXAMPLE
        elif "关系" in query or "联系" in query:
            return QueryType.CONNECTION
        elif "前置" in query or "基础" in query:
            return QueryType.PREREQUISITE
        else:
            return QueryType.SIMPLE_FACT

    def select_strategy(self, query: str, query_type: QueryType) -> RetrievalStrategy:
        """选择检索策略"""
        if query_type in [QueryType.SIMPLE_FACT, QueryType.DEFINITION, QueryType.EXAMPLE]:
            return RetrievalStrategy.SIMPLE_RAG
        elif query_type in [QueryType.COMPLEX_REASONING]:
            return RetrievalStrategy.AGENTIC_RAG
        else:
            return RetrievalStrategy.HYBRID

    async def query(self, query: str) -> RAGResponse:
        """执行查询"""
        query_type = self.detect_query_type(query)
        strategy = self.select_strategy(query, query_type)

        if strategy == RetrievalStrategy.SIMPLE_RAG:
            return await self._simple_rag_query(query)
        elif strategy == RetrievalStrategy.AGENTIC_RAG:
            return await self._agentic_rag_query(query)
        else:
            return await self._hybrid_query(query)

    async def _simple_rag_query(self, query: str) -> RAGResponse:
        """简单RAG查询"""
        chunks = self.retrieve(query)
        if not chunks:
            return RAGResponse(
                answer="没有找到与问题相关的来源。",
                sources=[],
                chunks=[],
                confidence=0.0,
            )

        sources = []
        for chunk in chunks:
            if chunk.source and chunk.source not in sources:
                sources.append(chunk.source)

        answer_parts = [chunk.content for chunk in chunks]
        confidence = min(1.0, sum(chunk.score for chunk in chunks) / len(chunks))

        return RAGResponse(
            answer="\n\n".join(answer_parts),
            sources=sources,
            chunks=chunks,
            confidence=confidence,
        )

    async def _agentic_rag_query(self, query: str) -> RAGResponse:
        """Agentic RAG查询"""
        return RAGResponse(answer="Agentic RAG查询结果", sources=[], chunks=[], confidence=0.9)

    async def _hybrid_query(self, query: str) -> RAGResponse:
        """混合查询"""
        return RAGResponse(answer="混合查询结果", sources=[], chunks=[], confidence=0.85)
