import pytest

from src.workers.queue import InProcessJobQueue, QueueBackend, create_job_queue
from src.workers.tasks import (
    DocumentProcessingTask,
    metadata_document_task,
    run_document_processing_task,
)


class RecordingJobService:
    def __init__(self):
        self.jobs = {}
        self.transitions = []
        self.stage_events = []

    def update_job_status(self, job_id, status, error_message=None, **metadata):
        self.transitions.append((job_id, status, error_message, metadata))
        job = self.jobs.setdefault(job_id, {"job_id": job_id})
        job["status"] = status
        job["error_message"] = error_message
        job.update(metadata)

    def record_job_stage(self, job_id, stage, status, error_message=None):
        self.stage_events.append((job_id, stage, status, error_message))


def test_in_process_queue_persists_job_state_before_and_after_each_stage():
    service = RecordingJobService()
    queue = InProcessJobQueue(job_service=service)
    task = DocumentProcessingTask(
        job_id="job-1",
        document_id="doc-1",
        stages=[("parse", lambda: None), ("extract", lambda: None)],
    )

    queue.enqueue(task)
    queue.run_next()

    assert service.transitions == [
        ("job-1", "queued", None, {}),
        ("job-1", "running", None, {}),
        ("job-1", "completed", None, {}),
    ]
    assert service.stage_events == [
        ("job-1", "parse", "running", None),
        ("job-1", "parse", "completed", None),
        ("job-1", "extract", "running", None),
        ("job-1", "extract", "completed", None),
    ]
    assert service.jobs["job-1"]["status"] == "completed"


def test_document_processing_task_marks_failed_when_stage_raises():
    service = RecordingJobService()

    def fail_stage():
        raise RuntimeError("parser failed")

    task = DocumentProcessingTask(
        job_id="job-1",
        document_id="doc-1",
        stages=[("parse", fail_stage)],
    )

    with pytest.raises(RuntimeError, match="parser failed"):
        run_document_processing_task(task, service)

    assert service.transitions == [
        ("job-1", "running", None, {}),
        ("job-1", "failed", "parser failed", {}),
    ]
    assert service.stage_events == [
        ("job-1", "parse", "running", None),
        ("job-1", "parse", "failed", "parser failed"),
    ]
    assert service.jobs["job-1"]["status"] == "failed"


def test_document_processing_task_validates_stage_entries_before_running():
    service = RecordingJobService()
    task = DocumentProcessingTask(
        job_id="job-1",
        document_id="doc-1",
        stages=[("parse", lambda: None), ("bad-stage",)],
    )

    with pytest.raises(ValueError, match="stage must be a"):
        run_document_processing_task(task, service)

    assert service.transitions == [
        ("job-1", "running", None, {}),
        ("job-1", "failed", "stage must be a (name, callable) pair", {}),
    ]


def test_metadata_document_task_records_observable_validation_stage():
    service = RecordingJobService()
    task = metadata_document_task(
        job_id="job-1",
        document_id="doc-1",
        metadata={"title": "Calculus Notes", "source_type": "pdf"},
    )

    run_document_processing_task(task, service)

    assert task.stage_keys == [
        "metadata_validation",
        "parse",
        "extract",
        "outline",
        "questions",
    ]
    assert service.stage_events == [
        ("job-1", "metadata_validation", "running", None),
        ("job-1", "metadata_validation", "completed", None),
    ]
    assert service.jobs["job-1"]["status"] == "completed"


def test_metadata_document_task_fails_for_invalid_metadata():
    service = RecordingJobService()
    task = metadata_document_task(
        job_id="job-1",
        document_id="doc-1",
        metadata={"source_type": "pdf"},
    )

    with pytest.raises(ValueError, match="title"):
        run_document_processing_task(task, service)

    assert service.stage_events == [
        ("job-1", "metadata_validation", "running", None),
        (
            "job-1",
            "metadata_validation",
            "failed",
            "document metadata must include title",
        ),
    ]


class FakeRedisClient:
    def __init__(self):
        self.pushed = []

    def rpush(self, key, value):
        self.pushed.append((key, value))
        return len(self.pushed)


def test_create_job_queue_supports_redis_backend_enqueue():
    service = RecordingJobService()
    redis_client = FakeRedisClient()
    queue = create_job_queue(
        backend=QueueBackend.REDIS,
        job_service=service,
        redis_url="redis://localhost:6379/0",
        redis_client=redis_client,
    )
    task = DocumentProcessingTask(job_id="job-1", document_id="doc-1")

    queued_job_id = queue.enqueue(task)

    assert queued_job_id == "job-1"
    assert queue.backend == QueueBackend.REDIS
    assert queue.redis_url == "redis://localhost:6379/0"
    assert service.transitions == [("job-1", "queued", None, {})]
    assert redis_client.pushed
    assert '"job_id": "job-1"' in redis_client.pushed[0][1]
    assert '"task_type": "document_processing"' in redis_client.pushed[0][1]
    assert '"stage_keys": []' in redis_client.pushed[0][1]


def test_create_job_queue_defaults_to_in_process_backend():
    queue = create_job_queue(job_service=RecordingJobService())

    assert isinstance(queue, InProcessJobQueue)
    assert queue.backend == QueueBackend.IN_PROCESS
