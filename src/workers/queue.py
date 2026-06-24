from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
import inspect
import json

from src.workers.tasks import DocumentProcessingTask, run_document_processing_task


DEFAULT_TASK_QUEUE_NAME = "study-agent-tasks"


class QueueBackend(str, Enum):
    IN_PROCESS = "in_process"
    REDIS = "redis"


class InProcessJobQueue:
    backend = QueueBackend.IN_PROCESS

    def __init__(self, job_service) -> None:
        self.job_service = job_service
        self._tasks: deque[DocumentProcessingTask] = deque()

    def enqueue(self, task: DocumentProcessingTask) -> str:
        _update_job_status(self.job_service, task, "queued")
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

    def healthcheck(self) -> bool:
        return True


@dataclass
class QueuePayload:
    task_type: str
    owner_id: str
    job_id: str | None = None
    document_id: str | None = None
    export_job_id: str | None = None
    stage_keys: list[str] | None = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "task_type": self.task_type,
                "owner_id": self.owner_id,
                "job_id": self.job_id,
                "document_id": self.document_id,
                "export_job_id": self.export_job_id,
                "stage_keys": self.stage_keys or [],
            },
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, raw: str | bytes) -> "QueuePayload":
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        data = json.loads(raw)
        return cls(
            task_type=data["task_type"],
            owner_id=data["owner_id"],
            job_id=data.get("job_id"),
            document_id=data.get("document_id"),
            export_job_id=data.get("export_job_id"),
            stage_keys=data.get("stage_keys") or [],
        )


@dataclass
class RedisTaskQueue:
    redis_client: object | None = None
    queue_name: str = DEFAULT_TASK_QUEUE_NAME
    redis_url: str | None = None

    def enqueue(self, payload: QueuePayload) -> None:
        self._client().rpush(self.queue_name, payload.to_json())

    def dequeue_raw(self):
        return self._client().lpop(self.queue_name)

    def dequeue(self) -> QueuePayload | None:
        raw = self.dequeue_raw()
        if raw is None:
            return None
        return QueuePayload.from_json(raw)

    def dead_letter(self, payload: QueuePayload | str | bytes, error: Exception) -> None:
        raw = payload.to_json() if isinstance(payload, QueuePayload) else payload
        self.dead_letter_raw(raw, error)

    def dead_letter_raw(self, raw: str | bytes, error: Exception) -> None:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        payload = json.dumps(
            {"error": str(error), "payload": raw},
            separators=(",", ":"),
            sort_keys=True,
        )
        self._client().rpush(f"{self.queue_name}:dead", payload)

    def _client(self):
        if self.redis_client is not None:
            return self.redis_client
        try:
            import redis
        except ImportError as exc:
            raise RuntimeError("Redis queue requires the redis package") from exc
        self.redis_client = redis.from_url(self.redis_url or "redis://localhost:6379/0")
        return self.redis_client

    def healthcheck(self) -> bool:
        return bool(self._client().ping())


@dataclass
class RedisJobQueue:
    job_service: object
    redis_url: str
    redis_client: object | None = None
    queue_name: str = DEFAULT_TASK_QUEUE_NAME
    backend: QueueBackend = QueueBackend.REDIS

    def enqueue(self, task: DocumentProcessingTask | QueuePayload) -> str | None:
        if isinstance(task, QueuePayload):
            self._client().rpush(self.queue_name, task.to_json())
            return task.job_id or task.export_job_id
        payload = QueuePayload(
            task_type=task.task_type,
            owner_id=task.owner_id,
            job_id=task.job_id,
            document_id=task.document_id,
            stage_keys=task.stage_keys,
        )
        self._client().rpush(self.queue_name, payload.to_json())
        _update_job_status(self.job_service, task, "queued")
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

    def healthcheck(self) -> bool:
        return bool(self._client().ping())


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


def _update_job_status(job_service, task: DocumentProcessingTask, status: str) -> None:
    if _supports_owner_scoped_status(job_service):
        try:
            job_service.update_job_status(
                job_id=task.job_id,
                status=status,
                owner_id=task.owner_id,
            )
            return
        except TypeError:
            pass
    try:
        job_service.update_job_status(job_id=task.job_id, status=status)
    except TypeError:
        job_service.update_job_status(task.job_id, status)


def _supports_owner_scoped_status(job_service) -> bool:
    try:
        signature = inspect.signature(job_service.update_job_status)
    except (AttributeError, TypeError, ValueError):
        return False
    parameter = signature.parameters.get("owner_id")
    if parameter is None:
        return False
    return parameter.kind in {
        inspect.Parameter.KEYWORD_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    }
