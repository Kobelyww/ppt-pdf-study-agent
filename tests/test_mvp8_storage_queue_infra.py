from pathlib import Path

from src.storage.s3_backend import S3StorageBackend
from src.workers.queue import QueuePayload, RedisJobQueue, RedisTaskQueue


ROOT = Path(__file__).resolve().parents[1]


class FakeS3Client:
    def __init__(self):
        self.objects = {}
        self.head_bucket_calls = []

    def put_object(self, *, Bucket, Key, Body, ContentType):
        self.objects[(Bucket, Key)] = {"body": Body, "content_type": ContentType}

    def get_object(self, *, Bucket, Key):
        return {"Body": FakeBody(self.objects[(Bucket, Key)]["body"])}

    def head_object(self, *, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise KeyError(Key)
        return {}

    def head_bucket(self, *, Bucket):
        self.head_bucket_calls.append(Bucket)
        return {}


class FakeBody:
    def __init__(self, body: bytes):
        self.body = body

    def read(self):
        return self.body


class FakeRedisClient:
    def __init__(self):
        self.items = []

    def rpush(self, key, value):
        self.items.append((key, value))

    def lpop(self, key):
        for index, (queued_key, value) in enumerate(self.items):
            if queued_key == key:
                self.items.pop(index)
                return value
        return None

    def ping(self):
        return True


def test_s3_storage_backend_puts_reads_and_healthchecks():
    client = FakeS3Client()
    backend = S3StorageBackend(bucket="study-agent", client=client)

    stored = backend.put_bytes(
        namespace="uploads",
        original_filename="../Lecture Notes.pdf",
        content=b"study content",
        content_type="application/pdf",
    )

    assert stored.storage_uri.startswith("s3://study-agent/uploads/")
    assert ".." not in stored.storage_uri
    assert backend.exists(stored.storage_uri)
    assert backend.read_bytes(stored.storage_uri) == b"study content"
    assert backend.healthcheck() is True
    assert client.head_bucket_calls == ["study-agent"]


def test_redis_payload_round_trip_and_healthcheck():
    redis_client = FakeRedisClient()
    queue = RedisTaskQueue(redis_client=redis_client)
    payload = QueuePayload(
        task_type="process_document",
        owner_id="user-1",
        job_id="job-1",
        document_id="doc-1",
        stage_keys=["metadata_validation"],
    )

    queue.enqueue(payload)
    dequeued = queue.dequeue()

    assert dequeued == payload
    assert queue.healthcheck() is True


def test_redis_job_queue_healthcheck_uses_ping():
    redis_client = FakeRedisClient()
    queue = RedisJobQueue(
        job_service=object(),
        redis_url="redis://localhost:6379/0",
        redis_client=redis_client,
    )

    assert queue.healthcheck() is True


def test_redis_job_queue_accepts_export_payload():
    redis_client = FakeRedisClient()
    queue = RedisJobQueue(
        job_service=object(),
        redis_url="redis://localhost:6379/0",
        redis_client=redis_client,
    )
    payload = QueuePayload(
        task_type="export",
        owner_id="user-1",
        export_job_id="export-1",
    )

    queued_id = queue.enqueue(payload)

    assert queued_id == "export-1"
    assert '"task_type": "export"' in redis_client.items[0][1]


def test_docker_compose_declares_production_services_and_env():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    for expected in [
        "api:",
        "worker:",
        "postgres:",
        "redis:",
        "minio:",
        "APP_ENV: production",
        "ALLOW_DEV_USER_HEADER: \"false\"",
        "QUEUE_BACKEND: redis",
        "STORAGE_BACKEND: s3",
        "S3_BUCKET: study-agent",
    ]:
        assert expected in compose
