import pytest

from src.services.agentic_rag import AgenticRAGPlanner


def test_agentic_planner_creates_steps_for_question_generation():
    plan = AgenticRAGPlanner().plan("基于第2章和第4章出一道综合题")

    assert plan.mode == "agentic_rag"
    assert len(plan.steps) >= 3
    assert "retrieve" in plan.steps[0].action
    assert any(step.action == "generate_question" for step in plan.steps)


def test_agentic_planner_keeps_direct_query_as_agentic_plan_without_question_generation():
    plan = AgenticRAGPlanner().plan("  解释特征值的定义  ")

    assert plan.mode == "agentic_rag"
    assert plan.reason == "single query agentic plan"
    assert tuple(step.action for step in plan.steps) == (
        "retrieve",
        "expand",
        "synthesize",
        "verify",
    )
    assert all(step.inputs["query"] == "解释特征值的定义" for step in plan.steps)


def test_agentic_planner_marks_cross_chapter_query_complex_without_question_generation():
    plan = AgenticRAGPlanner().plan("比较第2章和第4章的核心概念")

    assert plan.reason == "complex multi-step query"
    assert not any(step.action == "generate_question" for step in plan.steps)


def test_agentic_planner_rejects_empty_query():
    with pytest.raises(ValueError, match="query must not be empty"):
        AgenticRAGPlanner().plan("   ")
