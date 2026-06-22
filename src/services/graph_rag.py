from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from src.knowledge.knowledge_graph import KnowledgeGraph, KnowledgePoint
from src.services.rag_service import Chunk


@dataclass(frozen=True)
class GraphRAGResult:
    mode: str
    reason: str
    chunks: list[Chunk]
    confidence: float
    expanded_point_ids: list[str]


class GraphRAGLiteRetriever:
    def __init__(self, graph: KnowledgeGraph, chunks: list[Chunk]) -> None:
        self.graph = graph
        self.chunks = chunks

    async def retrieve(self, query: str, max_hops: int = 2, top_k: int = 5) -> GraphRAGResult:
        max_hops = max(0, max_hops)
        seeds = self._match_seed_points(query)
        expanded = self._expand_neighbors(seeds, max_hops=max_hops)
        matched_chunks = self._recover_chunks(expanded, top_k=top_k)
        confidence = 0.0 if not matched_chunks else min(1.0, 0.4 + 0.2 * len(matched_chunks))

        return GraphRAGResult(
            mode="graph_rag_lite",
            reason=self._result_reason(seeds=seeds, chunks=matched_chunks, top_k=top_k),
            chunks=matched_chunks,
            confidence=confidence,
            expanded_point_ids=[point.id for point in expanded],
        )

    def _match_seed_points(self, query: str) -> list[KnowledgePoint]:
        query_lower = query.lower()
        return [
            point
            for point in self.graph.points.values()
            if self._matches_point(query_lower=query_lower, point=point)
        ]

    def _expand_neighbors(self, seeds: list[KnowledgePoint], max_hops: int) -> list[KnowledgePoint]:
        seen: set[str] = set()
        expanded: list[KnowledgePoint] = []
        for point in seeds:
            if point.id not in seen:
                seen.add(point.id)
                expanded.append(point)
        frontier = list(seeds)

        for _ in range(max_hops):
            next_frontier: list[KnowledgePoint] = []
            for point in frontier:
                for neighbor in self.graph.get_related_points(point.id):
                    if neighbor.id not in seen:
                        seen.add(neighbor.id)
                        expanded.append(neighbor)
                        next_frontier.append(neighbor)
            frontier = next_frontier

        return expanded

    def _recover_chunks(self, points: list[KnowledgePoint], top_k: int) -> list[Chunk]:
        if top_k <= 0:
            return []

        names = [point.name.lower() for point in points]
        ranked: list[tuple[int, Chunk]] = []
        for chunk in self.chunks:
            score = sum(
                1 for name in names if name in chunk.content.lower() or name in chunk.source.lower()
            )
            if score > 0:
                ranked.append((score, chunk))

        ranked.sort(key=lambda item: item[0], reverse=True)
        max_score = max((score for score, _ in ranked), default=1)
        return [
            Chunk(
                content=chunk.content,
                source=chunk.source,
                metadata=chunk.metadata.copy(),
                score=score / max_score,
            )
            for score, chunk in ranked[:top_k]
        ]

    def _matches_point(self, *, query_lower: str, point: KnowledgePoint) -> bool:
        for term in self._point_match_terms(point):
            term_lower = term.lower().strip()
            if not term_lower:
                continue

            if self._contains_term(query_lower, term_lower):
                return True

        return False

    @staticmethod
    def _result_reason(*, seeds: list[KnowledgePoint], chunks: list[Chunk], top_k: int) -> str:
        if not seeds:
            return "no graph seed matched"
        if top_k <= 0:
            return "top_k must be positive"
        if not chunks:
            return "matched graph seed but no chunks recovered"
        return "matched concepts and expanded graph neighbors"

    def _point_match_terms(self, point: KnowledgePoint) -> list[str]:
        aliases = self._metadata_terms(point.metadata.get("aliases"))
        synonyms = self._metadata_terms(point.metadata.get("synonyms"))
        return [point.name, *aliases, *synonyms]

    @staticmethod
    def _metadata_terms(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, (list, tuple, set)):
            return [str(item) for item in value if str(item).strip()]
        return []

    @staticmethod
    def _contains_term(text: str, term: str) -> bool:
        if re.fullmatch(r"[a-z0-9][a-z0-9 _-]*", term):
            pattern = rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])"
            return re.search(pattern, text) is not None
        return term in text
