import re
from typing import List, Optional

from .base_agent import BaseAgent, AgentResult
from ..knowledge.knowledge_graph import KnowledgePoint, PointType
from ..parsers.marker_pdf import Formula, Section, StructuredDocument


class ContentUnderstandingAgent(BaseAgent):
    """内容理解智能体 — 使用本地启发式提取知识点"""

    role = "内容理解专家"
    system_prompt = "你是一个专业的内容理解智能体，负责从结构化文档中提取知识点。"

    async def process(self, input_data: dict) -> AgentResult:
        """从StructuredDocument中提取确定性的知识点列表"""
        if not isinstance(input_data, dict):
            return AgentResult(
                success=False,
                data={},
                message="输入错误: 缺少参数 document",
            )

        document = input_data.get("document")
        if not isinstance(document, StructuredDocument):
            return AgentResult(
                success=False,
                data={},
                message="缺少参数: document",
            )

        knowledge_points: List[KnowledgePoint] = []

        for section_index, section in enumerate(document.sections, start=1):
            self._collect_section_points(
                section=section,
                document_title=document.title,
                section_path=str(section_index),
                points=knowledge_points,
            )

        for formula_index, formula in enumerate(document.formulas, start=1):
            point = self._formula_point(
                formula=formula,
                category=document.title or "Document",
                point_id=f"formula-{formula_index}",
                section_title=document.title or "Document",
            )
            if point is not None:
                knowledge_points.append(point)

        return AgentResult(
            success=True,
            data={"knowledge_points": knowledge_points},
            message=f"提取知识点完成: {len(knowledge_points)}个",
        )

    def _collect_section_points(
        self,
        section: Section,
        document_title: str,
        section_path: str,
        points: List[KnowledgePoint],
    ) -> None:
        category = document_title or section.title or "Document"
        section_title = section.title.strip() or f"Section {section_path}"

        if section.title.strip():
            points.append(
                KnowledgePoint(
                    id=f"section-{section_path}",
                    name=section_title,
                    description=section.content.strip() or section_title,
                    category=category,
                    importance=0.9,
                    point_type=PointType.CONCEPT,
                    metadata={
                        "source": "section_title",
                        "section_level": section.level,
                        "section_path": section_path,
                    },
                )
            )

        for sentence_index, sentence in enumerate(self._split_sentences(section.content), start=1):
            points.append(
                KnowledgePoint(
                    id=f"section-{section_path}-concept-{sentence_index}",
                    name=self._sentence_name(sentence),
                    description=sentence,
                    category=category,
                    importance=0.65,
                    point_type=PointType.CONCEPT,
                    metadata={
                        "source": "section_content",
                        "section_title": section_title,
                        "section_path": section_path,
                    },
                )
            )

        for formula_index, formula in enumerate(section.formulas, start=1):
            point = self._formula_point(
                formula=formula,
                category=category,
                point_id=f"section-{section_path}-formula-{formula_index}",
                section_title=section_title,
            )
            if point is not None:
                points.append(point)

        for subsection_index, subsection in enumerate(section.subsections, start=1):
            self._collect_section_points(
                section=subsection,
                document_title=document_title,
                section_path=f"{section_path}-{subsection_index}",
                points=points,
            )

    def _formula_point(
        self,
        formula: Formula,
        category: str,
        point_id: str,
        section_title: str,
    ) -> Optional[KnowledgePoint]:
        latex = formula.latex.strip()
        description = formula.description.strip()
        if not latex and not description:
            return None

        name_source = description or latex
        return KnowledgePoint(
            id=point_id,
            name=self._formula_name(name_source),
            description=description or latex,
            category=category,
            importance=0.8,
            point_type=PointType.FORMULA,
            metadata={
                "source": "formula",
                "latex": latex,
                "section_title": section_title,
                "page_number": formula.page_number,
            },
        )

    def _split_sentences(self, content: str) -> List[str]:
        normalized = " ".join(content.split())
        if not normalized:
            return []

        return [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?。！？])\s+", normalized)
            if sentence.strip()
        ]

    def _sentence_name(self, sentence: str) -> str:
        cleaned = sentence.strip().rstrip(".!?。！？")
        words = cleaned.split()
        if len(words) <= 8:
            return cleaned
        return " ".join(words[:8])

    def _formula_name(self, source: str) -> str:
        cleaned = source.strip()
        if len(cleaned) <= 40:
            return cleaned
        return f"{cleaned[:37]}..."
