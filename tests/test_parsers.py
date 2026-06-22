import pytest
from types import SimpleNamespace
from src.parsers.marker_pdf import MarkerPDFParser, StructuredDocument


@pytest.mark.asyncio
async def test_marker_parser_initialization():
    """测试Marker解析器初始化"""
    parser = MarkerPDFParser()
    assert parser.model is None


@pytest.mark.asyncio
async def test_structured_document_creation():
    """测试结构化文档创建"""
    doc = StructuredDocument(title="测试文档", sections=[], tables=[], figures=[], formulas=[])
    assert doc.title == "测试文档"
    assert len(doc.sections) == 0


@pytest.mark.asyncio
@pytest.mark.xfail(
    raises=FileNotFoundError,
    strict=True,
    reason=(
        "requires real marker-pdf model/PDF fixture; covered by marker output "
        "mapping and structured-document E2E for MVP-1 in this environment"
    ),
)
async def test_marker_parser_parse():
    """测试Marker解析器解析PDF"""
    parser = MarkerPDFParser()
    result = await parser.parse("tests/fixtures/sample.pdf")
    assert isinstance(result, StructuredDocument)


def test_marker_output_mapping_to_structured_document():
    parser = MarkerPDFParser()
    fake_rendered = SimpleNamespace(
        metadata={"title": "Linear Algebra"},
        markdown="# Chapter 1\nVectors and matrices",
        children=[],
    )

    doc = parser._map_marker_output(fake_rendered)

    assert doc.title == "Linear Algebra"
    assert doc.sections
    assert "Vectors" in doc.sections[0].content
