import json
from pathlib import Path

import pytest
from src.config import load_config
from src.parsers.marker_pdf import Formula, MarkerPDFParser, Section, StructuredDocument
from src.agents.content_understanding import ContentUnderstandingAgent
from src.agents.outline_generation import OutlineGenerationAgent
from src.agents.question_generation import QuestionGenerationAgent
from src.knowledge.knowledge_graph import KnowledgeGraph, KnowledgePoint
from src.services.rag_service import RAGService
from src.services.memory_service import MemoryService
from src.coordinator.main_coordinator import MainCoordinator


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _formula_from_fixture(data):
    return Formula(
        latex=data.get("latex", ""),
        description=data.get("description", ""),
        page_number=data.get("page_number", 0),
    )


def _section_from_fixture(data):
    return Section(
        level=data.get("level", 1),
        title=data.get("title", ""),
        content=data.get("content", ""),
        formulas=[_formula_from_fixture(formula) for formula in data.get("formulas", [])],
        subsections=[
            _section_from_fixture(subsection) for subsection in data.get("subsections", [])
        ],
    )


def _structured_document_from_fixture(filename):
    fixture = json.loads((FIXTURES_DIR / filename).read_text(encoding="utf-8"))
    return StructuredDocument(
        title=fixture["title"],
        metadata=fixture.get("metadata", {}),
        sections=[_section_from_fixture(section) for section in fixture.get("sections", [])],
        formulas=[_formula_from_fixture(formula) for formula in fixture.get("formulas", [])],
    )


@pytest.mark.asyncio
async def test_full_pipeline():
    """测试完整流程"""
    # 1. 加载配置
    config = load_config()
    assert config.llm.primary_model == "mimo-v2.5"

    # 2. 初始化组件
    parser = MarkerPDFParser()
    knowledge_graph = KnowledgeGraph()
    rag_service = RAGService()
    memory_service = MemoryService()
    coordinator = MainCoordinator()

    # 3. 测试组件集成
    assert parser is not None
    assert knowledge_graph is not None
    assert rag_service is not None
    assert memory_service is not None
    assert coordinator is not None

    # 4. 测试知识图谱添加
    kp = KnowledgePoint(
        id="kp1", name="测试概念", description="这是一个测试概念", category="概念", importance=0.8
    )
    knowledge_graph.add_point(kp)
    assert len(knowledge_graph.nodes) == 1

    # 5. 测试记忆服务
    memory_service.add_message("user", "测试消息")
    context = memory_service.get_context()
    assert "测试消息" in context

    # 6. 测试协调器状态
    status = coordinator.get_status()
    assert status["current_stage"] == "idle"


@pytest.mark.asyncio
async def test_study_agents_process_structured_document_fixture():
    """Fixture-driven MVP-1 flow avoids real PDF/model dependencies."""
    document = _structured_document_from_fixture("sample_structured_document.json")

    content_agent = ContentUnderstandingAgent()
    outline_agent = OutlineGenerationAgent()
    question_agent = QuestionGenerationAgent()

    content_result = await content_agent.invoke({"document": document})
    assert content_result.success is True
    knowledge_points = content_result.data["knowledge_points"]
    assert knowledge_points
    knowledge_text = "\n".join(
        "\n".join(
            [
                point.name,
                point.description,
                str(point.metadata),
            ]
        )
        for point in knowledge_points
    )
    assert "Derivatives" in knowledge_text
    assert "Matrices" in knowledge_text
    assert any(
        "f(g(x))" in point.metadata.get("latex", "") or "Chain rule" in point.description
        for point in knowledge_points
    )

    outline_result = await outline_agent.invoke(
        {
            "knowledge_points": knowledge_points,
            "title": document.title,
        }
    )
    assert outline_result.success is True
    markdown = outline_result.data["markdown"]
    assert document.title in markdown
    assert "Derivatives" in markdown
    assert "Matrices" in markdown
    assert "Formula" in markdown or "Chain rule" in markdown
    assert "复习建议" in markdown

    question_result = await question_agent.invoke(
        {
            "knowledge_points": knowledge_points,
            "count": 5,
        }
    )
    assert question_result.success is True
    questions = question_result.data["questions"]
    assert len(questions) >= 5
    assert all(question.stem for question in questions)
    assert all(question.answer for question in questions)
    assert all(question.explanation for question in questions)
    question_text = "\n".join(
        "\n".join([question.stem, question.answer, question.explanation]) for question in questions
    )
    assert "Derivative" in question_text or "Matrix" in question_text
    assert "Chain" in question_text or "matrix" in question_text
