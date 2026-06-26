from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re


class RetrievalMode(str, Enum):
    SIMPLE = "simple_rag"
    GRAPH = "graph_rag_lite"
    AGENTIC = "agentic_rag"


class QueryCategory(str, Enum):
    DIRECT_LOOKUP = "direct_lookup"
    DEFINITION = "definition"
    CONCEPT_RELATION = "concept_relation"
    LEARNING_PATH = "learning_path"
    MULTI_DOCUMENT_SYNTHESIS = "multi_document_synthesis"
    QUESTION_GENERATION = "question_generation"
    OUTLINE_FRAGMENT = "outline_fragment"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RetrievalDecision:
    mode: RetrievalMode
    reason: str
    confidence: float
    estimated_cost: str
    category: QueryCategory = QueryCategory.DIRECT_LOOKUP


class RAGStrategyRouter:
    def route(self, query: str, target: str | None = None) -> RetrievalDecision:
        category = self.classify(query, target=target)

        if category in {
            QueryCategory.QUESTION_GENERATION,
            QueryCategory.MULTI_DOCUMENT_SYNTHESIS,
        }:
            return RetrievalDecision(
                mode=RetrievalMode.AGENTIC,
                reason="query requires multi-step synthesis or question generation",
                confidence=0.8,
                estimated_cost="high",
                category=category,
            )

        if category in {
            QueryCategory.CONCEPT_RELATION,
            QueryCategory.LEARNING_PATH,
        }:
            return RetrievalDecision(
                mode=RetrievalMode.GRAPH,
                reason="query asks for concept relation or learning path",
                confidence=0.75,
                estimated_cost="medium",
                category=category,
            )

        return RetrievalDecision(
            mode=RetrievalMode.SIMPLE,
            reason="definition or direct lookup query",
            confidence=0.7,
            estimated_cost="low",
            category=category,
        )

    def classify(self, query: str, target: str | None = None) -> QueryCategory:
        if target == "outline_fragment":
            return QueryCategory.OUTLINE_FRAGMENT

        normalized = query.strip().lower()
        if not normalized:
            return QueryCategory.UNKNOWN

        chapter_mentions = set(re.findall(r"第\s*\d+\s*章", normalized))
        is_question_generation = (
            any(
                keyword in normalized
                for keyword in ["出一道", "出题", "生成题", "生成一道", "练习题", "综合题"]
            )
            or re.search(r"生成[^。？！?]*题", normalized) is not None
        )

        if is_question_generation:
            return QueryCategory.QUESTION_GENERATION

        if "跨章节" in normalized or len(chapter_mentions) >= 2:
            return QueryCategory.MULTI_DOCUMENT_SYNTHESIS

        if any(
            keyword in normalized
            for keyword in [
                "前置",
                "先学",
                "依赖",
                "路径",
                "需要掌握",
                "掌握什么",
                "学习前",
            ]
        ):
            return QueryCategory.LEARNING_PATH

        if any(
            keyword in normalized
            for keyword in ["关系", "关联", "影响", "区别", "联系"]
        ):
            return QueryCategory.CONCEPT_RELATION

        if any(keyword in normalized for keyword in ["什么是", "是什么", "定义", "解释"]):
            return QueryCategory.DEFINITION

        return QueryCategory.DIRECT_LOOKUP
