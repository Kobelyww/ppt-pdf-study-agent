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
    assert all("query" not in step.inputs for step in plan.steps)


def test_agentic_planner_marks_cross_chapter_query_complex_without_question_generation():
    plan = AgenticRAGPlanner().plan("比较第2章和第4章的核心概念")

    assert plan.reason == "complex multi-step query"
    assert not any(step.action == "generate_question" for step in plan.steps)


def test_agentic_planner_rejects_empty_query():
    with pytest.raises(ValueError, match="query must not be empty"):
        AgenticRAGPlanner().plan("   ")


def test_agentic_planner_respects_max_steps_and_reports_budget_exhaustion():
    planner = AgenticRAGPlanner(max_steps=3)

    plan = planner.plan("基于第2章和第4章出一道综合题")

    assert tuple(step.action for step in plan.steps) == ("retrieve", "expand", "synthesize")
    assert plan.metadata == {
        "planned_step_count": 5,
        "executed_step_count": 3,
        "step_budget_exhausted": True,
    }


def test_agentic_planner_max_steps_has_minimum_one():
    plan = AgenticRAGPlanner(max_steps=0).plan("基于第2章和第4章出一道综合题")

    assert len(plan.steps) == 1
    assert plan.metadata["planned_step_count"] == 5
    assert plan.metadata["executed_step_count"] == 1
    assert plan.metadata["step_budget_exhausted"] is True


def test_agentic_planner_cost_labels_follow_budget_and_executed_steps():
    balanced_short = AgenticRAGPlanner(max_steps=3).plan("解释特征值的定义", budget="balanced")
    balanced_long = AgenticRAGPlanner(max_steps=4).plan("解释特征值的定义", budget="balanced")
    high_budget = AgenticRAGPlanner(max_steps=1).plan("解释特征值的定义", budget="high")

    assert balanced_short.estimated_cost == "medium"
    assert balanced_long.estimated_cost == "high"
    assert high_budget.estimated_cost == "high"


def test_agentic_planner_metadata_excludes_raw_prompt_and_hidden_reasoning():
    raw_query = "请根据 secret prompt 生成隐藏推理"
    plan = AgenticRAGPlanner(max_steps=5).plan(raw_query, budget="balanced")

    serialized_metadata = str(plan.metadata).lower()
    serialized_steps = str([step.inputs for step in plan.steps]).lower()
    assert raw_query not in serialized_metadata
    assert raw_query not in serialized_steps
    assert "prompt" not in plan.metadata
    assert "query" not in plan.metadata
    assert "chain_of_thought" not in plan.metadata
    assert "hidden_reasoning" not in plan.metadata
