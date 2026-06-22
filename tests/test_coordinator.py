import pytest
from unittest.mock import AsyncMock

from src.agents.base_agent import AgentResult
from src.coordinator.main_coordinator import MainCoordinator, CoordinatorState


def test_coordinator_initialization():
    """测试协调器初始化"""
    coordinator = MainCoordinator()
    assert coordinator.state.current_stage == "idle"
    assert len(coordinator.state.completed_stages) == 0


def test_coordinator_state():
    """测试协调器状态"""
    state = CoordinatorState()
    assert state.current_stage == "idle"
    assert state.completed_stages == []
    assert state.results == {}


@pytest.mark.asyncio
async def test_coordinator_runs_registered_pipeline():
    """测试协调器按MVP-1顺序调用已注册的子协调器"""
    coordinator = MainCoordinator()

    document_parsing = AsyncMock()
    document_parsing.invoke.return_value = AgentResult(
        success=True,
        data={"document": {"title": "Sample", "content": "PDF text"}, "title": "Sample"},
    )

    content_understanding = AsyncMock()
    content_understanding.invoke.return_value = AgentResult(
        success=True,
        data={"knowledge_points": ["kp"]},
    )

    outline_generation = AsyncMock()
    outline_generation.invoke.return_value = AgentResult(
        success=True,
        data={"markdown": "# Outline"},
    )

    question_generation = AsyncMock()
    question_generation.invoke.return_value = AgentResult(
        success=True,
        data={"questions": ["q"]},
    )

    coordinator.register_sub_coordinator("document_parsing", document_parsing)
    coordinator.register_sub_coordinator("content_understanding", content_understanding)
    coordinator.register_sub_coordinator("outline_generation", outline_generation)
    coordinator.register_sub_coordinator("question_generation", question_generation)

    result = await coordinator.invoke({"pdf_path": "sample.pdf"})

    assert result["status"] == "success"
    assert result["data"]["outline"] == "# Outline"
    assert result["data"]["questions"] == ["q"]
    document_parsing.invoke.assert_awaited_once_with(
        {"pdf_path": "sample.pdf", "request": {"pdf_path": "sample.pdf"}}
    )
    content_understanding.invoke.assert_awaited_once_with(
        {"document": {"title": "Sample", "content": "PDF text"}}
    )
    outline_generation.invoke.assert_awaited_once_with(
        {"knowledge_points": ["kp"], "title": "Sample"}
    )
    question_generation.invoke.assert_awaited_once_with({"knowledge_points": ["kp"], "count": 1})


@pytest.mark.asyncio
async def test_coordinator_accepts_dict_stage_results():
    """测试协调器兼容普通dict格式的阶段返回值"""
    coordinator = MainCoordinator()

    document_parsing = AsyncMock()
    document_parsing.invoke.return_value = {
        "success": True,
        "data": {
            "document": {"title": "Dict Sample", "content": "PDF text"},
            "title": "Dict Sample",
        },
    }

    content_understanding = AsyncMock()
    content_understanding.invoke.return_value = {
        "success": True,
        "data": {"knowledge_points": ["kp"]},
    }

    outline_generation = AsyncMock()
    outline_generation.invoke.return_value = {
        "success": True,
        "data": {"markdown": "# Dict Outline"},
    }

    question_generation = AsyncMock()
    question_generation.invoke.return_value = {
        "success": True,
        "data": {"questions": ["q"]},
    }

    coordinator.register_sub_coordinator("document_parsing", document_parsing)
    coordinator.register_sub_coordinator("content_understanding", content_understanding)
    coordinator.register_sub_coordinator("outline_generation", outline_generation)
    coordinator.register_sub_coordinator("question_generation", question_generation)

    result = await coordinator.invoke({"pdf_path": "sample.pdf"})

    assert result["status"] == "success"
    assert result["data"]["outline"] == "# Dict Outline"
    assert result["data"]["questions"] == ["q"]


@pytest.mark.asyncio
async def test_coordinator_stops_on_failed_stage():
    """测试阶段失败后停止后续阶段调用"""
    coordinator = MainCoordinator()

    document_parsing = AsyncMock()
    document_parsing.invoke.return_value = AgentResult(
        success=True,
        data={"document": {"title": "Sample"}, "title": "Sample"},
    )

    content_understanding = AsyncMock()
    content_understanding.invoke.return_value = AgentResult(
        success=False,
        data={"reason": "bad content"},
        message="内容理解失败",
    )

    outline_generation = AsyncMock()
    question_generation = AsyncMock()

    coordinator.register_sub_coordinator("document_parsing", document_parsing)
    coordinator.register_sub_coordinator("content_understanding", content_understanding)
    coordinator.register_sub_coordinator("outline_generation", outline_generation)
    coordinator.register_sub_coordinator("question_generation", question_generation)

    result = await coordinator.invoke({"pdf_path": "sample.pdf"})

    assert result["status"] == "failed"
    assert result["data"]["failed_stage"] == "content_understanding"
    assert coordinator.state.status.value == "failed"
    outline_generation.invoke.assert_not_awaited()
    question_generation.invoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_coordinator_fails_for_unregistered_stage():
    """测试缺少阶段注册时返回结构化失败"""
    coordinator = MainCoordinator()

    result = await coordinator.invoke({"pdf_path": "sample.pdf"})

    assert result["status"] == "failed"
    assert result["data"]["failed_stage"] == "document_parsing"
    assert coordinator.state.status.value == "failed"


@pytest.mark.asyncio
async def test_coordinator_rejects_invalid_request():
    """测试非法request返回结构化失败而不是抛异常"""
    coordinator = MainCoordinator()

    result = await coordinator.invoke(None)

    assert result["status"] == "failed"
    assert result["data"]["failed_stage"] == "request_validation"
    assert coordinator.state.status.value == "failed"
