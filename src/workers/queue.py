from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
import json

from src.workers.tasks import DocumentProcessingTask, run_document_processing_task


class QueueBackend(str, Enum):
    IN_PROCESS = "in_process"
    REDIS = "redis"


class InProcessJobQueue:
    backend = QueueBackend.IN_PROCESS

    def __init__(self, job_service) -> None:
        self.job_service = job_service
        self._tasks: deque[DocumentProcessingTask] = deque()

    def enqueue(self, task: DocumentProcessingTask) -> str:
        self.job_service.update_job_status(task.job_id, "queued")
        self._tasks.append(task)
        return task.job_id

    def run_next(self) -> bool:
        if not self._tasks:
            return False

        task = self._tasks.popleft()
        run_document_processing_task(task, self.job_service)
        return True

    def run_all(self) -> int:
        processed = 0
        while self.run_next():
            processed += 1
        return processed

    def __len__(self) -> int:
        return len(self._tasks)


@dataclass
class RedisJobQueue:
    job_service: object
    redis_url: str
    redis_client: object | None = None
    queue_name: str = "study_agent:jobs"
    backend: QueueBackend = QueueBackend.REDIS

    def enqueue(self, task: DocumentProcessingTask) -> str:
        payload = json.dumps(
            {
                "job_id": task.job_id,
                "document_id": task.document_id,
                "task_type": task.task_type,
                "stage_keys": task.stage_keys or [stage_name for stage_name, _ in task.stages],
            }
        )
        self._client().rpush(self.queue_name, payload)
        self.job_service.update_job_status(task.job_id, "queued")
        return task.job_id

    def _client(self):
        if self.redis_client is not None:
            return self.redis_client

        try:
            import redis
        except ImportError as exc:
            raise RuntimeError("Redis queue requires the redis package") from exc

        self.redis_client = redis.from_url(self.redis_url)
        return self.redis_client


def create_job_queue(
    *,
    job_service,
    backend: QueueBackend | str = QueueBackend.IN_PROCESS,
    redis_url: str | None = None,
    redis_client=None,
):
    queue_backend = QueueBackend(backend)
    if queue_backend == QueueBackend.REDIS:
        return RedisJobQueue(
            job_service=job_service,
            redis_url=redis_url or "redis://localhost:6379/0",
            redis_client=redis_client,
        )
    return InProcessJobQueue(job_service=job_service)
