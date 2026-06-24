from __future__ import annotations

from datetime import datetime, timezone
import os
import time

from src.config import load_product_config
from src.db import Base, ExportJobRecord, ProcessingJob, create_session_factory, get_engine
from src.storage.backend import create_storage_backend
from src.workers.queue import QueuePayload, RedisTaskQueue
from src.workers.tasks import run_export_task, run_product_document_task


DOCUMENT_TASK_TYPES = {"process_document", "document_processing"}


def run_queue_payload(payload: QueuePayload, *, session_factory, storage) -> None:
    if payload.task_type in DOCUMENT_TASK_TYPES:
        if payload.job_id is None or payload.document_id is None:
            raise ValueError("job_id and document_id are required")
        run_product_document_task(
            job_id=payload.job_id,
            document_id=payload.document_id,
            owner_id=payload.owner_id,
            session_factory=session_factory,
            storage=storage,
        )
        return
    if payload.task_type == "export":
        if payload.export_job_id is None:
            raise ValueError("export_job_id is required")
        run_export_task(
            export_job_id=payload.export_job_id,
            owner_id=payload.owner_id,
            session_factory=session_factory,
            storage=storage,
        )
        return
    raise ValueError(f"unsupported task type: {payload.task_type}")


def run_worker_once(queue, session_factory, storage, poll_seconds: float = 1.0, on_error=None) -> bool:
    raw_payload = None
    try:
        raw_payload = queue.dequeue_raw() if hasattr(queue, "dequeue_raw") else None
        if raw_payload is None:
            payload = queue.dequeue() if hasattr(queue, "dequeue") else None
            if payload is None:
                time.sleep(poll_seconds)
                return False
        else:
            payload = QueuePayload.from_json(raw_payload)
    except Exception as exc:
        _dead_letter_raw(queue, raw_payload, exc)
        _notify_error(on_error, exc, None)
        return True
    try:
        run_queue_payload(payload, session_factory=session_factory, storage=storage)
    except Exception as exc:
        _mark_payload_failed(payload, session_factory, str(exc))
        _dead_letter(queue, payload, exc)
        _notify_error(on_error, exc, payload)
    return True


def run_worker_loop(queue, session_factory, storage, poll_seconds: float = 1.0) -> None:
    while True:
        run_worker_once(queue, session_factory=session_factory, storage=storage, poll_seconds=poll_seconds)


def main() -> None:
    config = load_product_config()
    engine = get_engine(config.database_url)
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    storage = create_storage_backend(config)
    queue_name = os.getenv("QUEUE_NAME", "study-agent-tasks")
    queue = RedisTaskQueue(redis_url=config.redis_url, queue_name=queue_name)
    run_worker_loop(queue, session_factory=session_factory, storage=storage)


def _dead_letter_raw(queue, raw_payload, error: Exception) -> None:
    if raw_payload is not None and hasattr(queue, "dead_letter_raw"):
        queue.dead_letter_raw(raw_payload, error)


def _dead_letter(queue, payload: QueuePayload, error: Exception) -> None:
    if hasattr(queue, "dead_letter"):
        queue.dead_letter(payload, error)


def _notify_error(on_error, error: Exception, payload: QueuePayload | None) -> None:
    if on_error is not None:
        on_error(error, payload)


def _mark_payload_failed(payload: QueuePayload, session_factory, error_message: str) -> None:
    failed_at = datetime.now(timezone.utc)
    try:
        with session_factory() as session:
            if payload.task_type in DOCUMENT_TASK_TYPES and payload.job_id is not None:
                job = session.get(ProcessingJob, payload.job_id)
                if job is not None and job.owner_id == payload.owner_id:
                    job.status = "failed"
                    job.error_message = error_message
                    job.completed_at = failed_at
                    job.updated_at = failed_at
                    session.commit()
            elif payload.task_type == "export" and payload.export_job_id is not None:
                export = session.get(ExportJobRecord, payload.export_job_id)
                if export is not None and export.owner_id == payload.owner_id:
                    export.status = "failed"
                    export.error_message = error_message
                    export.completed_at = failed_at
                    session.commit()
    except Exception:
        return


if __name__ == "__main__":
    main()
