import pytest
from src.services.memory_service import MemoryService, ShortTermMemory, LongTermMemory


def test_short_term_memory_initialization():
    """测试短期记忆初始化"""
    stm = ShortTermMemory(max_tokens=50000)
    assert stm.max_tokens == 50000
    assert len(stm.messages) == 0


def test_long_term_memory_initialization():
    """测试长期记忆初始化"""
    ltm = LongTermMemory(db_path=":memory:")
    assert ltm.db is not None


def test_memory_service_initialization():
    """测试记忆服务初始化"""
    service = MemoryService()
    assert service.stm is not None
    assert service.ltm is not None
