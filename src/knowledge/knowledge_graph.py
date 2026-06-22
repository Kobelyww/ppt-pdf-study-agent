from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum
import networkx as nx


class PointType(Enum):
    """知识点类型"""

    CONCEPT = "concept"
    FORMULA = "formula"
    THEOREM = "theorem"
    EXAMPLE = "example"
    METHOD = "method"


@dataclass
class KnowledgePoint:
    """知识点"""

    id: str
    name: str
    description: str
    category: str
    importance: float = 0.5
    point_type: PointType = PointType.CONCEPT
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Relationship:
    """关系"""

    source_id: str
    target_id: str
    relation_type: str
    weight: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)


class KnowledgeGraph:
    """知识图谱"""

    def __init__(self):
        self.graph = nx.DiGraph()
        self.nodes: Dict[str, KnowledgePoint] = {}
        self.edges: List[Relationship] = []

    @property
    def points(self) -> Dict[str, KnowledgePoint]:
        """Return knowledge points keyed by id."""
        return self.nodes

    def add_point(self, point: KnowledgePoint) -> None:
        """添加知识点"""
        self.nodes[point.id] = point
        self.graph.add_node(point.id, **point.__dict__)

    def add_relationship(self, relationship: Relationship) -> None:
        """添加关系"""
        self.edges.append(relationship)
        self.graph.add_edge(relationship.source_id, relationship.target_id, **relationship.__dict__)

    def get_point(self, point_id: str) -> Optional[KnowledgePoint]:
        """获取知识点"""
        return self.nodes.get(point_id)

    def get_related_points(self, point_id: str) -> List[KnowledgePoint]:
        """获取相关知识点"""
        related_ids = list(self.graph.neighbors(point_id))
        return [self.nodes[pid] for pid in related_ids if pid in self.nodes]

    def find_path(self, source_id: str, target_id: str) -> List[str]:
        """查找路径"""
        try:
            path = nx.shortest_path(self.graph, source_id, target_id)
            return path
        except nx.NetworkXNoPath:
            return []

    def get_important_points(self, top_k: int = 10) -> List[KnowledgePoint]:
        """获取重要知识点"""
        sorted_points = sorted(self.nodes.values(), key=lambda x: x.importance, reverse=True)
        return sorted_points[:top_k]
