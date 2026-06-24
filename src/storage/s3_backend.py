from __future__ import annotations

from hashlib import sha256
from urllib.parse import quote, unquote, urlparse

from src.storage.backend import StoredObject, StorageError, _safe_filename


class S3StorageBackend:
    def __init__(self, *, bucket: str, client):
        self.bucket = bucket
        self.client = client

    def put_bytes(
        self,
        *,
        namespace: str,
        original_filename: str,
        content: bytes,
        content_type: str,
    ) -> StoredObject:
        content_hash = f"sha256:{sha256(content).hexdigest()}"
        safe_name = _safe_filename(original_filename)
        key = f"{self._safe_namespace(namespace)}/{content_hash}-{safe_name}"
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=content,
            ContentType=content_type,
        )
        return StoredObject(
            storage_uri=f"s3://{self.bucket}/{quote(key, safe='/:')}",
            content_hash=content_hash,
            original_filename=original_filename,
            content_type=content_type,
            size_bytes=len(content),
        )

    def read_bytes(self, storage_uri: str) -> bytes:
        bucket, key = self._bucket_key_from_uri(storage_uri)
        if bucket != self.bucket:
            raise StorageError("invalid storage uri")
        response = self.client.get_object(Bucket=bucket, Key=key)
        return response["Body"].read()

    def exists(self, storage_uri: str) -> bool:
        try:
            bucket, key = self._bucket_key_from_uri(storage_uri)
            if bucket != self.bucket:
                return False
            self.client.head_object(Bucket=bucket, Key=key)
            return True
        except Exception:
            return False

    def healthcheck(self) -> bool:
        self.client.head_bucket(Bucket=self.bucket)
        return True

    @staticmethod
    def _safe_namespace(namespace: str) -> str:
        from src.storage.backend import LocalStorageBackend

        return LocalStorageBackend._safe_namespace(namespace)

    @staticmethod
    def _bucket_key_from_uri(storage_uri: str) -> tuple[str, str]:
        parsed = urlparse(storage_uri)
        if parsed.scheme != "s3" or not parsed.netloc or not parsed.path:
            raise StorageError("invalid storage uri")
        key = unquote(parsed.path.lstrip("/"))
        if not key:
            raise StorageError("invalid storage uri")
        return parsed.netloc, key
