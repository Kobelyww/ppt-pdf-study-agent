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
    metadata: dict[str, int | bool] = field(default_factory=dict)


class AgenticRAGPlanner:
    def __init__(self, max_steps: int = 5) -> None:
        self.max_steps = max(1, max_steps)

    def plan(self, query: str, budget: str = "balanced") -> AgenticRAGPlan:
        query = query.strip()
        if not query:
            raise ValueError("query must not be empty")

        is_question_generation = any(
            keyword in query for keyword in ["出一道", "生成题", "综合题", "练习题"]
        )
        is_cross_chapter = any(keyword in query for keyword in ["第2章", "第4章", "跨章节", "综合"])

        steps = [
            AgenticRAGStep("retrieve", "retrieve directly relevant chunks"),
            AgenticRAGStep(
                "expand",
                "expand concepts through graph or prerequisites",
            ),
            AgenticRAGStep(
                "synthesize",
                "merge evidence into a grounded response",
            ),
            AgenticRAGStep(
                "verify",
                "check citations, missing concepts, and unsupported claims",
            ),
        ]

        if is_question_generation:
            steps.append(
                AgenticRAGStep(
                    "generate_question",
                    "produce question, answer, and scoring rubric",
                )
            )

        planned_step_count = len(steps)
        executed_steps = steps[: self.max_steps]
        executed_step_count = len(executed_steps)
        metadata = {
            "planned_step_count": planned_step_count,
            "executed_step_count": executed_step_count,
            "step_budget_exhausted": executed_step_count < planned_step_count,
        }
        estimated_cost = (
            "high"
            if budget == "high" or executed_step_count >= 4
            else "medium"
        )
        reason = (
            "complex multi-step query"
            if is_cross_chapter or is_question_generation
            else "single query agentic plan"
        )
        return AgenticRAGPlan(
            mode="agentic_rag",
            reason=reason,
            steps=tuple(executed_steps),
            estimated_cost=estimated_cost,
            metadata=metadata,
        )
