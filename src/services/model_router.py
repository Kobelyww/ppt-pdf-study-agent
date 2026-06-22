"""模型路由器 - 根据任务特点智能选择模型"""

from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from enum import Enum
import re

from src.config import LLMConfig, TaskCategory


class TaskComplexity(Enum):
    """任务复杂度"""

    SIMPLE = "simple"  # 简单任务
    MEDIUM = "medium"  # 中等任务
    COMPLEX = "complex"  # 复杂任务


@dataclass
class TaskAnalysis:
    """任务分析结果"""

    category: TaskCategory
    complexity: TaskComplexity
    requires_multimodal: bool
    requires_reasoning: bool
    requires_long_context: bool
    estimated_tokens: int
    recommended_model: str
    confidence: float  # 0-1，模型选择的置信度


class ModelRouter:
    """模型路由器"""

    def __init__(self, config: LLMConfig):
        self.config = config
        self._task_keywords = self._build_task_keywords()

    def _build_task_keywords(self) -> Dict[TaskCategory, List[str]]:
        """构建任务关键词映射"""
        return {
            # MiMo V2.5 擅长的任务
            TaskCategory.MULTIMODAL: [
                "图片",
                "图像",
                "图表",
                "照片",
                "扫描",
                "视觉",
                "image",
                "picture",
                "photo",
                "chart",
                "graph",
                "visual",
            ],
            TaskCategory.OCR: [
                "ocr",
                "识别文字",
                "提取文字",
                "扫描",
                "手写",
                "recognize text",
                "extract text",
                "scan",
            ],
            TaskCategory.TABLE_UNDERSTANDING: [
                "表格",
                "行列",
                "单元格",
                "表头",
                "table",
                "row",
                "column",
                "cell",
                "header",
            ],
            TaskCategory.FORMULA_RECOGNITION: [
                "公式",
                "方程",
                "数学表达式",
                "latex",
                "formula",
                "equation",
                "mathematical expression",
            ],
            TaskCategory.IMAGE_DESCRIPTION: [
                "描述图片",
                "图片内容",
                "图片里",
                "图中",
                "describe image",
                "image content",
                "what's in the image",
            ],
            # DeepSeek V4 擅长的任务
            TaskCategory.REASONING: [
                "推理",
                "逻辑",
                "分析",
                "为什么",
                "原因",
                "reason",
                "logic",
                "why",
                "because",
                "analyze",
            ],
            TaskCategory.MATH_REASONING: [
                "计算",
                "数学",
                "求解",
                "证明",
                "公式推导",
                "calculate",
                "math",
                "solve",
                "prove",
                "derivation",
            ],
            TaskCategory.CODE_GENERATION: [
                "代码",
                "编程",
                "实现",
                "函数",
                "算法",
                "code",
                "programming",
                "implement",
                "function",
                "algorithm",
            ],
            TaskCategory.CODE_DEBUG: [
                "调试",
                "bug",
                "错误",
                "修复",
                "问题",
                "debug",
                "error",
                "fix",
                "bug",
                "issue",
            ],
            TaskCategory.LONG_TEXT: [
                "长文",
                "文档",
                "论文",
                "文章",
                "全文",
                "long text",
                "document",
                "paper",
                "article",
                "full text",
            ],
            TaskCategory.SUMMARIZATION: [
                "总结",
                "摘要",
                "概括",
                "归纳",
                "summarize",
                "summary",
                "overview",
                "abstract",
            ],
            TaskCategory.ANALYSIS: [
                "分析",
                "解析",
                "剖析",
                "研究",
                "analysis",
                "analyze",
                "examine",
                "study",
            ],
            # 通用任务
            TaskCategory.QA: [
                "什么",
                "如何",
                "怎么",
                "哪些",
                "是否",
                "what",
                "how",
                "which",
                "whether",
                "is",
            ],
            TaskCategory.TRANSLATION: ["翻译", "translate", "translation"],
            TaskCategory.CREATIVE: [
                "创作",
                "写",
                "故事",
                "诗歌",
                "创意",
                "create",
                "write",
                "story",
                "poem",
                "creative",
            ],
            TaskCategory.EXTRACTION: [
                "提取",
                "抽取",
                "获取",
                "找出",
                "extract",
                "get",
                "find",
                "retrieve",
            ],
        }

    def analyze_task(
        self, task_description: str, context: Optional[Dict[str, Any]] = None
    ) -> TaskAnalysis:
        """分析任务并推荐模型"""
        task_lower = task_description.lower()

        # 1. 检测任务类别
        category = self._detect_category(task_lower)

        # 2. 评估复杂度
        complexity = self._assess_complexity(task_description, context)

        # 3. 检测是否需要多模态
        requires_multimodal = self._requires_multimodal(task_lower)

        # 4. 检测是否需要强推理
        requires_reasoning = self._requires_reasoning(task_lower)

        # 5. 检测是否需要长上下文
        requires_long_context = self._requires_long_context(task_description, context)

        # 6. 估算token数量
        estimated_tokens = self._estimate_tokens(task_description, context)

        # 7. 选择模型
        model, confidence = self._select_model(
            category, complexity, requires_multimodal, requires_reasoning, requires_long_context
        )

        return TaskAnalysis(
            category=category,
            complexity=complexity,
            requires_multimodal=requires_multimodal,
            requires_reasoning=requires_reasoning,
            requires_long_context=requires_long_context,
            estimated_tokens=estimated_tokens,
            recommended_model=model,
            confidence=confidence,
        )

    def _detect_category(self, task_lower: str) -> TaskCategory:
        """检测任务类别"""
        scores = {}

        for category, keywords in self._task_keywords.items():
            score = sum(1 for kw in keywords if kw in task_lower)
            if score > 0:
                scores[category] = score

        if scores:
            return max(scores, key=scores.get)

        # 默认类别
        return TaskCategory.QA

    def _assess_complexity(
        self, task: str, context: Optional[Dict[str, Any]] = None
    ) -> TaskComplexity:
        """评估任务复杂度"""
        # 高复杂度指标
        high_complexity_keywords = [
            "复杂",
            "深入",
            "综合",
            "多步骤",
            "全面",
            "详细分析",
            "complex",
            "deep",
            "multi-step",
            "comprehensive",
            "detailed analysis",
            "系统性",
            "多维度",
            "跨领域",
            "systematic",
            "multi-dimensional",
        ]

        # 低复杂度指标
        low_complexity_keywords = [
            "简单",
            "快速",
            "简短",
            "概述",
            "简介",
            "simple",
            "quick",
            "short",
            "overview",
            "brief",
        ]

        task_lower = task.lower()

        # 检查高复杂度指标
        if any(kw in task_lower for kw in high_complexity_keywords):
            return TaskComplexity.COMPLEX

        # 检查低复杂度指标
        if any(kw in task_lower for kw in low_complexity_keywords):
            return TaskComplexity.SIMPLE

        # 基于任务长度和内容评估
        if len(task) < 20:
            return TaskComplexity.SIMPLE
        elif len(task) < 50:
            return TaskComplexity.MEDIUM
        else:
            # 长任务默认为中等或复杂
            return TaskComplexity.COMPLEX

    def _requires_multimodal(self, task_lower: str) -> bool:
        """检测是否需要多模态"""
        multimodal_keywords = [
            "图片",
            "图像",
            "图表",
            "照片",
            "扫描",
            "视觉",
            "表格",
            "公式",
            "image",
            "picture",
            "photo",
            "chart",
            "graph",
            "visual",
            "table",
            "formula",
        ]
        return any(kw in task_lower for kw in multimodal_keywords)

    def _requires_reasoning(self, task_lower: str) -> bool:
        """检测是否需要强推理"""
        reasoning_keywords = [
            "推理",
            "逻辑",
            "分析",
            "为什么",
            "原因",
            "证明",
            "reason",
            "logic",
            "why",
            "because",
            "prove",
            "analyze",
        ]
        return any(kw in task_lower for kw in reasoning_keywords)

    def _requires_long_context(self, task: str, context: Optional[Dict[str, Any]] = None) -> bool:
        """检测是否需要长上下文"""
        # 检查任务描述长度
        if len(task) > 1000:
            return True

        # 检查上下文中的文档长度
        if context:
            doc_content = context.get("document_content", "")
            if len(doc_content) > 5000:
                return True

        return False

    def _estimate_tokens(self, task: str, context: Optional[Dict[str, Any]] = None) -> int:
        """估算token数量"""
        # 简单估算：中文约1.5 token/字，英文约0.75 token/词
        task_tokens = int(len(task) * 1.2)

        if context:
            doc_content = context.get("document_content", "")
            doc_tokens = int(len(doc_content) * 1.2)
            task_tokens += doc_tokens

        return task_tokens

    def _select_model(
        self,
        category: TaskCategory,
        complexity: TaskComplexity,
        requires_multimodal: bool,
        requires_reasoning: bool,
        requires_long_context: bool,
    ) -> tuple[str, float]:
        """选择模型"""
        # 规则1：如果需要多模态，使用 MiMo V2.5
        if requires_multimodal:
            return "mimo-v2.5", 0.95

        # 规则2：如果需要强推理，使用 DeepSeek V4
        if requires_reasoning:
            return "deepseek-v4", 0.90

        # 规则3：如果需要长上下文，使用 DeepSeek V4
        if requires_long_context:
            return "deepseek-v4", 0.85

        # 规则4：根据任务类别选择
        model = self.config.task_model_mapping.get(category)
        if model:
            return model, 0.80

        # 规则5：根据复杂度选择
        if complexity == TaskComplexity.COMPLEX:
            return "deepseek-v4", 0.75
        elif complexity == TaskComplexity.SIMPLE:
            return "deepseek-v4", 0.70  # 简单任务用 DeepSeek 更经济
        else:
            return "mimo-v2.5", 0.70

    def get_model_for_task(
        self, task_description: str, context: Optional[Dict[str, Any]] = None
    ) -> str:
        """获取任务对应的模型"""
        analysis = self.analyze_task(task_description, context)
        return analysis.recommended_model

    def get_routing_stats(self, tasks: List[str]) -> Dict[str, int]:
        """统计任务路由分布"""
        stats = {"mimo-v2.5": 0, "deepseek-v4": 0}

        for task in tasks:
            model = self.get_model_for_task(task)
            stats[model] = stats.get(model, 0) + 1

        return stats


def create_model_router(config: LLMConfig) -> ModelRouter:
    """创建模型路由器"""
    return ModelRouter(config)
