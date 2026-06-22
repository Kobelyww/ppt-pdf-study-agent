import pytest
from src.knowledge.knowledge_graph import KnowledgeGraph, KnowledgePoint, Relationship


def test_knowledge_graph_initialization():
    """测试知识图谱初始化"""
    kg = KnowledgeGraph()
    assert len(kg.nodes) == 0
    assert len(kg.edges) == 0


def test_knowledge_point_creation():
    """测试知识点创建"""
    kp = KnowledgePoint(
        id="kp1", name="测试概念", description="这是一个测试概念", category="概念", importance=0.8
    )
    assert kp.id == "kp1"
    assert kp.name == "测试概念"


def test_knowledge_graph_add_point():
    """测试添加知识点"""
    kg = KnowledgeGraph()
    kp = KnowledgePoint(
        id="kp1", name="测试概念", description="这是一个测试概念", category="概念", importance=0.8
    )
    kg.add_point(kp)
    assert len(kg.nodes) == 1
    assert "kp1" in kg.nodes
