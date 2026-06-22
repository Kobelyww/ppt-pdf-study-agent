from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from enum import Enum


class AgentStatus(Enum):
    """智能体状态"""

    IDLE = "idle"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class AgentResult:
    """智能体结果"""

    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    message: str = ""
    status: AgentStatus = AgentStatus.COMPLETED


class BaseAgent(ABC):
    """基础智能体类"""

    role: str = ""
    system_prompt: str = ""
    max_retries: int = 3

    def __init__(self):
        self.status = AgentStatus.IDLE
        self.retry_count = 0

    @abstractmethod
    async def process(self, input_data: Any) -> AgentResult:
        """处理输入数据"""
        pass

    async def invoke(self, input_data: Any) -> AgentResult:
        """调用智能体处理"""
        self.status = AgentStatus.PROCESSING
        self.retry_count = 0

        while self.retry_count <= self.max_retries:
            try:
                result = await self.process(input_data)
                self.status = AgentStatus.COMPLETED
                return result
            except Exception as e:
                self.retry_count += 1
                if self.retry_count > self.max_retries:
                    self.status = AgentStatus.FAILED
                    return AgentResult(
                        success=False,
                        data={},
                        message=f"处理失败 (重试{self.max_retries}次后): {str(e)}",
                        status=AgentStatus.FAILED,
                    )

        return AgentResult(success=False, data={}, message="未知错误", status=AgentStatus.FAILED)

    def reset(self):
        """重置智能体状态"""
        self.status = AgentStatus.IDLE
        self.retry_count = 0
