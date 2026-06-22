from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from enum import Enum
from datetime import datetime


class CoordinatorStatus(Enum):
    """协调器状态"""

    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


@dataclass
class Checkpoint:
    """检查点"""

    stage: str
    timestamp: datetime
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CoordinatorState:
    """协调器状态"""

    current_stage: str = "idle"
    completed_stages: List[str] = field(default_factory=list)
    results: Dict[str, Any] = field(default_factory=dict)
    errors: List[Dict[str, Any]] = field(default_factory=list)
    checkpoints: List[Checkpoint] = field(default_factory=list)
    status: CoordinatorStatus = CoordinatorStatus.IDLE

    def advance_stage(self) -> None:
        """推进到下一阶段"""
        self.completed_stages.append(self.current_stage)
        stage_order = [
            "document_parsing",
            "content_understanding",
            "knowledge_extraction",
            "outline_generation",
            "question_generation",
            "quality_evaluation",
            "completed",
        ]
        current_index = (
            stage_order.index(self.current_stage) if self.current_stage in stage_order else -1
        )
        if current_index < len(stage_order) - 1:
            self.current_stage = stage_order[current_index + 1]

    def save_checkpoint(self) -> Checkpoint:
        """保存检查点"""
        checkpoint = Checkpoint(
            stage=self.current_stage,
            timestamp=datetime.now(),
            data={
                "completed_stages": self.completed_stages.copy(),
                "results": self.results.copy(),
            },
        )
        self.checkpoints.append(checkpoint)
        return checkpoint


class MainCoordinator:
    """主协调器"""

    def __init__(self):
        self.state = CoordinatorState()
        self.sub_coordinators: Dict[str, Any] = {}

    def register_sub_coordinator(self, name: str, coordinator: Any) -> None:
        """注册子协调器"""
        self.sub_coordinators[name] = coordinator

    async def invoke(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """执行协调流程"""
        self.state.status = CoordinatorStatus.RUNNING
        self.state.current_stage = "request_validation"

        if not isinstance(request, dict):
            return self._stage_failure(
                "request_validation",
                "请求参数必须是字典",
                {"request_type": type(request).__name__},
            )["response"]

        self.state.current_stage = "document_parsing"

        try:
            document_result = await self._invoke_stage(
                "document_parsing",
                {
                    "pdf_path": request.get("pdf_path"),
                    "request": request,
                },
            )
            if not document_result["success"]:
                return document_result["response"]

            document_data = document_result["data"]
            document = document_data.get("document")
            title = document_data.get("title") or getattr(document, "title", None)

            understanding_result = await self._invoke_stage(
                "content_understanding",
                {"document": document},
            )
            if not understanding_result["success"]:
                return understanding_result["response"]

            understanding_data = understanding_result["data"]
            knowledge_points = understanding_data.get("knowledge_points", [])

            outline_result = await self._invoke_stage(
                "outline_generation",
                {
                    "knowledge_points": knowledge_points,
                    "title": title,
                },
            )
            if not outline_result["success"]:
                return outline_result["response"]

            outline_data = outline_result["data"]
            outline = outline_data.get("markdown") or outline_data.get("outline", "")

            question_result = await self._invoke_stage(
                "question_generation",
                {
                    "knowledge_points": knowledge_points,
                    "count": request.get("count", len(knowledge_points)),
                },
            )
            if not question_result["success"]:
                return question_result["response"]

            question_data = question_result["data"]
            questions = question_data.get("questions", [])

            self.state.status = CoordinatorStatus.COMPLETED
            self.state.current_stage = "completed"

            return {
                "status": "success",
                "message": "协调流程执行完成",
                "data": {
                    "document": document,
                    "knowledge_points": knowledge_points,
                    "outline": outline,
                    "questions": questions,
                },
            }
        except Exception as e:
            self.state.status = CoordinatorStatus.FAILED
            self.state.errors.append(
                {"stage": self.state.current_stage, "error": str(e), "timestamp": datetime.now()}
            )
            raise

    async def _invoke_stage(
        self,
        stage: str,
        input_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """调用一个已注册阶段并更新协调器状态"""
        self.state.current_stage = stage
        coordinator = self.sub_coordinators.get(stage)
        if coordinator is None:
            return self._stage_failure(stage, f"未注册子协调器: {stage}")

        result = await coordinator.invoke(input_data)
        success, data, message = self._normalize_stage_result(result)

        if not success:
            return self._stage_failure(stage, message or f"阶段失败: {stage}", data)

        self.state.results[stage] = data
        self.state.completed_stages.append(stage)
        self.state.save_checkpoint()
        return {"success": True, "data": data}

    def _normalize_stage_result(self, result: Any) -> tuple[bool, Dict[str, Any], str]:
        """统一解析AgentResult、dict或具有同名属性的返回值"""
        if isinstance(result, dict):
            success = result.get("success", False)
            data = result.get("data", {}) or {}
            message = result.get("message", "")
        else:
            success = getattr(result, "success", False)
            data = getattr(result, "data", {}) or {}
            message = getattr(result, "message", "")

        if not isinstance(data, dict):
            data = {}

        return bool(success), data, str(message or "")

    def _stage_failure(
        self,
        stage: str,
        message: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """构造阶段失败响应并记录状态"""
        self.state.status = CoordinatorStatus.FAILED
        error = {
            "stage": stage,
            "error": message,
            "timestamp": datetime.now(),
        }
        self.state.errors.append(error)
        return {
            "success": False,
            "response": {
                "status": "failed",
                "message": message,
                "data": {
                    "failed_stage": stage,
                    "stage_data": data or {},
                    "completed_stages": self.state.completed_stages.copy(),
                },
            },
        }

    def get_status(self) -> Dict[str, Any]:
        """获取状态"""
        return {
            "current_stage": self.state.current_stage,
            "completed_stages": self.state.completed_stages,
            "status": self.state.status.value,
            "errors": len(self.state.errors),
        }
