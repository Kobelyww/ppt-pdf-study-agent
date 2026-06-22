from pathlib import Path
from typing import Any, Optional

from .base_agent import BaseAgent, AgentResult, AgentStatus
from ..parsers.marker_pdf import MarkerPDFParser, StructuredDocument
from ..config import ParserConfig


class DocumentParsingAgent(BaseAgent):
    """文档解析智能体 — 使用Marker解析PDF并返回结构化文档"""

    role = "文档解析专家"
    system_prompt = "你是一个专业的文档解析智能体，负责将PDF文档转换为结构化数据。"

    def __init__(self, config: Optional[ParserConfig] = None):
        super().__init__()
        config = config or ParserConfig()
        self.parser = MarkerPDFParser(model_path=config.marker_model_path)
        self.enable_ocr = config.enable_ocr
        self.max_file_size_mb = config.max_file_size_mb

    async def process(self, input_data: dict) -> AgentResult:
        """处理PDF文件路径，返回结构化文档

        Args:
            input_data: 字典，包含以下键:
                - pdf_path (str): PDF文件路径

        Returns:
            AgentResult，data中包含 StructuredDocument
        """
        pdf_path = input_data.get("pdf_path", "")

        if not pdf_path:
            return AgentResult(
                success=False,
                data={},
                message="缺少参数: pdf_path",
            )

        path = Path(pdf_path)
        if not path.exists():
            return AgentResult(
                success=False,
                data={},
                message=f"PDF文件不存在: {pdf_path}",
            )

        file_size_mb = path.stat().st_size / (1024 * 1024)
        if file_size_mb > self.max_file_size_mb:
            return AgentResult(
                success=False,
                data={},
                message=f"文件大小 ({file_size_mb:.1f}MB) 超过限制 ({self.max_file_size_mb}MB)",
            )

        doc: StructuredDocument = await self.parser.parse(pdf_path)

        return AgentResult(
            success=True,
            data={
                "document": doc,
                "title": doc.title,
                "section_count": len(doc.sections),
                "table_count": len(doc.tables),
                "figure_count": len(doc.figures),
                "formula_count": len(doc.formulas),
            },
            message=f"解析完成: {doc.title or '(无标题)'}",
        )
