from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from pathlib import Path


@dataclass
class Section:
    """文档章节"""

    level: int = 1
    title: str = ""
    content: str = ""
    subsections: List["Section"] = field(default_factory=list)
    tables: List["Table"] = field(default_factory=list)
    figures: List["Figure"] = field(default_factory=list)
    formulas: List["Formula"] = field(default_factory=list)


@dataclass
class Table:
    """表格数据"""

    headers: List[str] = field(default_factory=list)
    rows: List[List[str]] = field(default_factory=list)
    caption: str = ""
    page_number: int = 0


@dataclass
class Figure:
    """图表数据"""

    image_path: str = ""
    caption: str = ""
    description: str = ""
    page_number: int = 0


@dataclass
class Formula:
    """公式数据"""

    latex: str = ""
    description: str = ""
    page_number: int = 0


@dataclass
class StructuredDocument:
    """结构化文档"""

    title: str = ""
    sections: List[Section] = field(default_factory=list)
    tables: List[Table] = field(default_factory=list)
    figures: List[Figure] = field(default_factory=list)
    formulas: List[Formula] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class MarkerPDFParser:
    """Marker PDF解析器"""

    def __init__(self, model_path: Optional[str] = None):
        self.model_path = model_path
        self.model = None
        self.converter = None

    def load_model(self):
        """加载Marker PDF转换器"""
        try:
            from marker.config.parser import ConfigParser
            from marker.converters.pdf import PdfConverter
            from marker.models import create_model_dict
        except ImportError:
            raise ImportError("请安装marker-pdf: pip install marker-pdf")

        config = {"output_format": "markdown"}
        if self.model_path:
            config["model_path"] = self.model_path

        config_parser = ConfigParser(config)
        self.converter = PdfConverter(
            config=config_parser.generate_config_dict(),
            artifact_dict=create_model_dict(),
            processor_list=config_parser.get_processors(),
            renderer=config_parser.get_renderer(),
            llm_service=config_parser.get_llm_service(),
        )
        self.model = self.converter

    async def parse(self, pdf_path: str) -> StructuredDocument:
        """解析PDF文件"""
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF文件不存在: {pdf_path}")

        try:
            if self.converter is None:
                self.load_model()

            rendered = self.converter(str(pdf_path))
            return self._map_marker_output(rendered)
        except Exception as e:
            raise RuntimeError(f"PDF解析失败: {str(e)}")

    def _map_marker_output(self, rendered) -> StructuredDocument:
        """将Marker渲染结果映射为内部结构化文档"""
        metadata = getattr(rendered, "metadata", None) or {}
        markdown = getattr(rendered, "markdown", "") or ""
        title = metadata.get("title", "")

        sections = self._sections_from_markdown(markdown, fallback_title=title)

        return StructuredDocument(
            title=title,
            sections=sections,
            tables=self._extract_tables(rendered),
            figures=self._extract_figures(rendered),
            formulas=self._extract_formulas(rendered),
            metadata=metadata,
        )

    def _sections_from_markdown(self, markdown: str, fallback_title: str = "") -> List[Section]:
        """从Markdown标题和正文构建扁平章节列表"""
        sections: List[Section] = []
        current_section: Optional[Section] = None
        content_lines: List[str] = []

        def flush_current_section():
            nonlocal current_section, content_lines
            if current_section is not None:
                current_section.content = "\n".join(content_lines).strip()
                sections.append(current_section)
                content_lines = []

        for line in markdown.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                heading_text = stripped.lstrip("#").strip()
                if heading_text:
                    flush_current_section()
                    level = len(stripped) - len(stripped.lstrip("#"))
                    current_section = Section(level=level, title=heading_text)
                    continue
            content_lines.append(line)

        flush_current_section()

        remaining_content = "\n".join(content_lines).strip()
        if remaining_content:
            sections.append(
                Section(
                    level=1,
                    title=fallback_title or "Document",
                    content=remaining_content,
                )
            )

        if not sections and markdown.strip():
            sections.append(
                Section(
                    level=1,
                    title=fallback_title or "Document",
                    content=markdown.strip(),
                )
            )

        return sections

    def _extract_sections(self, rendered) -> List[Section]:
        """提取章节结构"""
        sections = []
        # 根据Marker的输出格式提取章节
        # 这里需要根据实际Marker API进行调整
        return sections

    def _extract_tables(self, rendered) -> List[Table]:
        """提取表格数据"""
        tables = []
        # 根据Marker的输出格式提取表格
        return tables

    def _extract_figures(self, rendered) -> List[Figure]:
        """提取图表数据"""
        figures = []
        # 根据Marker的输出格式提取图表
        return figures

    def _extract_formulas(self, rendered) -> List[Formula]:
        """提取公式数据"""
        formulas = []
        # 根据Marker的输出格式提取公式
        return formulas
