from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re


class RetrievalMode(str, Enum):
    SIMPLE = "simple_rag"
    GRAPH = "graph_rag_lite"
    AGENTIC = "agentic_rag"


@dataclass(frozen=True)
class RetrievalDecision:
    mode: RetrievalMode
    reason: str
    confidence: float
    estimated_cost: str


class RAGStrategyRouter:
    def route(self, query: str) -> RetrievalDecision:
        normalized = query.strip().lower()
        chapter_mentions = set(re.findall(r"第\s*\d+\s*章", normalized))
        is_question_generation = (
            any(
                keyword in normalized
                for keyword in ["出一道", "出题", "生成题", "生成一道", "练习题", "综合题"]
            )
            or re.search(r"生成[^。？！?]*题", normalized) is not None
        )
        needs_agentic = (
            is_question_generation or "跨章节" in normalized or len(chapter_mentions) >= 2
        )

        if needs_agentic:
            return RetrievalDecision(
                mode=RetrievalMode.AGENTIC,
                reason="query requires multi-step synthesis or question generation",
                confidence=0.8,
                estimated_cost="high",
            )

        if any(
            keyword in normalized
            for keyword in [
                "关系",
                "前置",
                "先学",
                "依赖",
                "路径",
                "关联",
                "需要掌握",
                "掌握什么",
                "学习前",
            ]
        ):
            return RetrievalDecision(
                mode=RetrievalMode.GRAPH,
                reason="query asks for concept relation or learning path",
                confidence=0.75,
                estimated_cost="medium",
            )

        return RetrievalDecision(
            mode=RetrievalMode.SIMPLE,
            reason="definition or direct lookup query",
            confidence=0.7,
            estimated_cost="low",
        )
