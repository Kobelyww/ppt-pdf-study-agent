import pytest

from src.agents.outline_generation import OutlineGenerationAgent
from src.knowledge.knowledge_graph import KnowledgePoint, PointType


@pytest.mark.asyncio
async def test_generates_markdown_outline():
    points = [
        KnowledgePoint(
            id="kp1",
            name="Derivative",
            description="Rate of change",
            category="concept",
        ),
        KnowledgePoint(
            id="kp2",
            name="Chain Rule",
            description="Composite derivative",
            category="formula",
            point_type=PointType.FORMULA,
        ),
    ]

    result = await OutlineGenerationAgent().invoke(
        {"knowledge_points": points, "title": "Calculus"}
    )

    assert result.success is True
    markdown = result.data["markdown"]
    assert "# Calculus" in markdown
    assert "### concept" in markdown
    assert "Derivative" in markdown
    assert "## Formula" in markdown
    assert "Chain Rule" in markdown
    assert "复习建议" in markdown


@pytest.mark.asyncio
async def test_rejects_invalid_knowledge_point_items():
    result = await OutlineGenerationAgent().invoke({"knowledge_points": ["bad"]})

    assert result.success is False
    assert result.data == {}
    assert "KnowledgePoint" in result.message or "knowledge_points" in result.message
