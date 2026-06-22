from dataclasses import dataclass
from typing import List

from .base_agent import BaseAgent, AgentResult
from ..knowledge.knowledge_graph import KnowledgePoint


@dataclass
class Question:
    """复习题目"""

    stem: str
    answer: str
    explanation: str
    difficulty: str
    question_type: str
    knowledge_point_id: str


class QuestionGenerationAgent(BaseAgent):
    """题目生成智能体 — 使用本地确定性规则生成复习题"""

    role = "题目生成专家"
    system_prompt = "你是一个专业的题目生成智能体，负责根据知识点生成复习题。"

    async def process(self, input_data: dict) -> AgentResult:
        """根据知识点生成确定性的复习题列表"""
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

        count = input_data.get("count", len(knowledge_points))
        if isinstance(count, bool) or not isinstance(count, int):
            return AgentResult(
                success=False,
                data={},
                message="参数错误: count 必须是整数",
            )

        if count < 0:
            return AgentResult(
                success=False,
                data={},
                message="参数错误: count 不能为负数",
            )

        questions = self._build_questions(
            knowledge_points=knowledge_points,
            count=count,
        )

        return AgentResult(
            success=True,
            data={"questions": questions},
            message=f"生成复习题完成: {len(questions)}道",
        )

    def _build_questions(
        self,
        knowledge_points: List[KnowledgePoint],
        count: int,
    ) -> List[Question]:
        if not knowledge_points or count == 0:
            return []

        questions: List[Question] = []
        builders = [
            self._definition_question,
            self._fill_in_question,
            self._short_answer_question,
        ]

        for index in range(count):
            point = knowledge_points[index % len(knowledge_points)]
            builder = builders[index % len(builders)]
            questions.append(builder(point))

        return questions

    def _definition_question(self, point: KnowledgePoint) -> Question:
        return Question(
            stem=f"What is {point.name}?",
            answer=point.description,
            explanation=(
                f"{point.name} belongs to {point.category} and is described as: "
                f"{point.description}"
            ),
            difficulty=self._difficulty_for(point),
            question_type="definition",
            knowledge_point_id=point.id,
        )

    def _fill_in_question(self, point: KnowledgePoint) -> Question:
        return Question(
            stem=f"Fill in the blank: {point.name} refers to ____.",
            answer=point.description,
            explanation=(
                f"The blank should capture the core description of {point.name}: "
                f"{point.description}"
            ),
            difficulty=self._difficulty_for(point),
            question_type="fill-in",
            knowledge_point_id=point.id,
        )

    def _short_answer_question(self, point: KnowledgePoint) -> Question:
        return Question(
            stem=f"Briefly explain {point.name} in your own words.",
            answer=point.description,
            explanation=(
                f"A complete response should mention the key idea: " f"{point.description}"
            ),
            difficulty=self._difficulty_for(point),
            question_type="short-answer",
            knowledge_point_id=point.id,
        )

    def _difficulty_for(self, point: KnowledgePoint) -> str:
        if point.importance >= 0.8:
            return "hard"
        if point.importance >= 0.6:
            return "medium"
        return "easy"
