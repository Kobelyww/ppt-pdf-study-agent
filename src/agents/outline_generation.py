from collections import defaultdict
from typing import DefaultDict, List

from .base_agent import BaseAgent, AgentResult
from ..knowledge.knowledge_graph import KnowledgePoint, PointType


class OutlineGenerationAgent(BaseAgent):
    """大纲生成智能体 — 使用本地确定性规则生成Markdown复习大纲"""

    role = "大纲生成专家"
    system_prompt = "你是一个专业的大纲生成智能体，负责将知识点整理为复习大纲。"

    async def process(self, input_data: dict) -> AgentResult:
        """根据知识点生成确定性的Markdown大纲"""
        if not isinstance(input_data, dict):
            return AgentResult(
                success=False,
                data={},
                message="输入错误: 缺少参数 knowledge_points",
            )

        knowledge_points = input_data.get("knowledge_points")
        if not isinstance(knowledge_points, list):
            return AgentResult(
                success=False,
                data={},
                message="缺少参数: knowledge_points",
            )

        invalid_items = [
            index
            for index, point in enumerate(knowledge_points)
            if not isinstance(point, KnowledgePoint)
        ]
        if invalid_items:
            return AgentResult(
                success=False,
                data={},
                message=(
                    "knowledge_points 中存在非 KnowledgePoint 元素: " f"indices={invalid_items}"
                ),
            )

        title = str(input_data.get("title") or "Study Outline").strip()
        if not title:
            title = "Study Outline"

        markdown = self._build_markdown(
            title=title,
            knowledge_points=knowledge_points,
        )

        return AgentResult(
            success=True,
            data={"markdown": markdown},
            message="生成复习大纲完成",
        )

    def _build_markdown(
        self,
        title: str,
        knowledge_points: List[KnowledgePoint],
    ) -> str:
        concept_groups: DefaultDict[str, List[KnowledgePoint]] = defaultdict(list)
        formula_points: List[KnowledgePoint] = []

        for point in knowledge_points:
            if point.point_type == PointType.FORMULA:
                formula_points.append(point)
            else:
                concept_groups[point.category or "Uncategorized"].append(point)

        lines = [f"# {title}", "", "## Core Concepts"]

        if concept_groups:
            for category in sorted(concept_groups):
                lines.extend(["", f"### {category}"])
                for point in concept_groups[category]:
                    lines.append(f"- **{point.name}**: {point.description}")
        else:
            lines.extend(["", "- 暂无核心概念。"])

        if formula_points:
            lines.extend(["", "## Formula", ""])
            for point in formula_points:
                lines.append(f"- **{point.name}**: {point.description}")

        lines.extend(
            [
                "",
                "## 复习建议",
                "",
                "- 先通读核心概念，确认每个术语的定义和适用场景。",
                "- 对公式类知识点进行推导练习，并配合例题检查理解。",
                "- 最后回到原始材料，补齐薄弱类别中的细节。",
            ]
        )

        return "\n".join(lines)
