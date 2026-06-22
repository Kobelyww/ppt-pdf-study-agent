import pytest

from src.agents.content_understanding import ContentUnderstandingAgent
from src.knowledge.knowledge_graph import PointType
from src.parsers.marker_pdf import Formula, Section, StructuredDocument


@pytest.mark.asyncio
async def test_extracts_knowledge_points_from_sections():
    doc = StructuredDocument(
        title="Calculus",
        sections=[
            Section(
                level=1,
                title="Derivatives",
                content="Derivative measures rate of change. Chain rule is important.",
                formulas=[Formula(latex="(f(g(x)))'=f'(g(x))g'(x)")],
            )
        ],
    )

    result = await ContentUnderstandingAgent().invoke({"document": doc})

    assert result.success is True
    points = result.data["knowledge_points"]
    assert len(points) >= 2
    assert any("Derivatives" in point.name or "Derivative" in point.name for point in points)
    formula_points = [point for point in points if point.point_type == PointType.FORMULA]
    assert len(formula_points) >= 1
    assert any(
        "f(g(x))" in point.name
        or "f(g(x))" in point.description
        or "f(g(x))" in point.metadata.get("latex", "")
        for point in formula_points
    )


@pytest.mark.asyncio
async def test_rejects_invalid_input_without_retry_exception():
    result = await ContentUnderstandingAgent().invoke(None)

    assert result.success is False
    assert "重试" not in result.message
    assert "document" in result.message or "输入" in result.message
