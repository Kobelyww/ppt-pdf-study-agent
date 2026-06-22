from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AgenticRAGStep:
    action: str
    objective: str
    inputs: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AgenticRAGPlan:
    mode: str
    reason: str
    steps: tuple[AgenticRAGStep, ...]
    estimated_cost: str


class AgenticRAGPlanner:
    def plan(self, query: str) -> AgenticRAGPlan:
        query = query.strip()
        if not query:
            raise ValueError("query must not be empty")

        is_question_generation = any(
            keyword in query for keyword in ["出一道", "生成题", "综合题", "练习题"]
        )
        is_cross_chapter = any(keyword in query for keyword in ["第2章", "第4章", "跨章节", "综合"])

        steps = [
            AgenticRAGStep("retrieve", "retrieve directly relevant chunks", {"query": query}),
            AgenticRAGStep(
                "expand",
                "expand concepts through graph or prerequisites",
                {"query": query},
            ),
            AgenticRAGStep(
                "synthesize",
                "merge evidence into a grounded response",
                {"query": query},
            ),
            AgenticRAGStep(
                "verify",
                "check citations, missing concepts, and unsupported claims",
                {"query": query},
            ),
        ]

        if is_question_generation:
            steps.append(
                AgenticRAGStep(
                    "generate_question",
                    "produce question, answer, and scoring rubric",
                    {"query": query},
                )
            )

        reason = (
            "complex multi-step query"
            if is_cross_chapter or is_question_generation
            else "single query agentic plan"
        )
        return AgenticRAGPlan(
            mode="agentic_rag",
            reason=reason,
            steps=tuple(steps),
            estimated_cost="high",
        )
