import pytest

from src.agents.question_generation import QuestionGenerationAgent
from src.knowledge.knowledge_graph import KnowledgePoint


@pytest.mark.asyncio
async def test_generates_questions_with_answers():
    points = [
        KnowledgePoint(
            id="kp1",
            name="Derivative",
            description="Rate of change",
            category="concept",
        ),
        KnowledgePoint(
            id="kp2",
            name="Matrix",
            description="Rectangular array",
            category="concept",
        ),
    ]

    result = await QuestionGenerationAgent().invoke({"knowledge_points": points, "count": 5})

    assert result.success is True
    questions = result.data["questions"]
    assert len(questions) == 5
    assert all(q.stem and q.answer and q.explanation for q in questions)
    assert {q.question_type for q in questions} >= {
        "definition",
        "fill-in",
        "short-answer",
    }
    assert {q.knowledge_point_id for q in questions} <= {"kp1", "kp2"}


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [1.5, True, "3"])
async def test_rejects_invalid_count_values(count):
    points = [
        KnowledgePoint(
            id="kp1",
            name="Derivative",
            description="Rate of change",
            category="concept",
        )
    ]

    result = await QuestionGenerationAgent().invoke({"knowledge_points": points, "count": count})

    assert result.success is False
    assert result.data == {}
    assert "count" in result.message
    assert "整数" in result.message


@pytest.mark.asyncio
async def test_rejects_invalid_knowledge_point_items():
    result = await QuestionGenerationAgent().invoke({"knowledge_points": ["bad"], "count": 1})

    assert result.success is False
    assert "KnowledgePoint" in result.message
    assert "knowledge_points" in result.message


@pytest.mark.asyncio
async def test_zero_count_returns_empty_questions():
    points = [
        KnowledgePoint(
            id="kp1",
            name="Derivative",
            description="Rate of change",
            category="concept",
        )
    ]

    result = await QuestionGenerationAgent().invoke({"knowledge_points": points, "count": 0})

    assert result.success is True
    assert result.data["questions"] == []
