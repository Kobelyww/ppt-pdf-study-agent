from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re
from typing import Protocol
from urllib.parse import quote, unquote, urlparse
from uuid import uuid4


class StorageError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredObject:
    storage_uri: str
    content_hash: str
    original_filename: str
    content_type: str
    size_bytes: int


class StorageBackend(Protocol):
    def put_bytes(
        self,
        *,
        namespace: str,
        original_filename: str,
        content: bytes,
        content_type: str,
    ) -> StoredObject:
        ...

    def read_bytes(self, storage_uri: str) -> bytes:
        ...

    def exists(self, storage_uri: str) -> bool:
        ...


def _safe_filename(original_filename: str) -> str:
    suffix = LocalStorageBackend._safe_suffix(original_filename)
    base = Path(original_filename).name
    if suffix:
        base = base[: -len(suffix)]
    normalized = re.sub(r"[^a-z0-9_-]+", "-", base.lower()).strip("-")
    return f"{normalized[:64] or 'upload'}{suffix}"


def create_storage_backend(config) -> StorageBackend:
    if config.storage_backend == "local":
        return LocalStorageBackend(config.local_storage_root)
    if config.storage_backend == "s3":
        import boto3

        client_kwargs = {"region_name": config.s3_region}
        if config.s3_endpoint_url:
            client_kwargs["endpoint_url"] = config.s3_endpoint_url
            client_kwargs["use_ssl"] = config.s3_secure
        if config.s3_access_key_id:
            client_kwargs["aws_access_key_id"] = config.s3_access_key_id
        if config.s3_secret_access_key:
            client_kwargs["aws_secret_access_key"] = config.s3_secret_access_key

        from src.storage.s3_backend import S3StorageBackend

        return S3StorageBackend(
            bucket=config.s3_bucket,
            client=boto3.client("s3", **client_kwargs),
        )
    raise ValueError(f"unsupported storage backend: {config.storage_backend}")


class LocalStorageBackend:
    def __init__(self, root: Path | str):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put_bytes(
        self,
        *,
        namespace: str,
        original_filename: str,
        content: bytes,
        content_type: str,
    ) -> StoredObject:
        namespace_path = self._safe_namespace(namespace)
        target_dir = self.root / namespace_path
        target_dir.mkdir(parents=True, exist_ok=True)
        suffix = self._safe_suffix(original_filename)
        stored_name = f"{uuid4().hex}{suffix}"
        target_path = target_dir / stored_name
        target_path.write_bytes(content)
        return StoredObject(
            storage_uri=f"local://{quote(namespace_path)}/{stored_name}",
            content_hash=f"sha256:{sha256(content).hexdigest()}",
            original_filename=original_filename,
            content_type=content_type,
            size_bytes=len(content),
        )

    def read_bytes(self, storage_uri: str) -> bytes:
        return self._path_from_uri(storage_uri).read_bytes()

    def exists(self, storage_uri: str) -> bool:
        try:
            return self._path_from_uri(storage_uri).exists()
        except StorageError:
            return False

    def healthcheck(self) -> bool:
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root.exists() and self.root.is_dir()

    def _path_from_uri(self, storage_uri: str) -> Path:
        parsed = urlparse(storage_uri)
        if parsed.scheme != "local" or not parsed.netloc or not parsed.path:
            raise StorageError("invalid storage uri")
        namespace = unquote(parsed.netloc)
        if namespace != self._safe_namespace(namespace):
            raise StorageError("invalid storage uri")
        filename = Path(unquote(parsed.path.lstrip("/"))).name
        if not filename or filename != unquote(parsed.path.lstrip("/")):
            raise StorageError("invalid storage uri")
        path = (self.root / namespace / filename).resolve()
        if self.root not in path.parents:
            raise StorageError("invalid storage uri")
        return path

    @staticmethod
    def _safe_namespace(namespace: str) -> str:
        normalized = re.sub(r"[^a-z0-9_-]+", "-", namespace.lower()).strip("-")
        if not normalized:
            raise StorageError("invalid storage namespace")
        return normalized

    @staticmethod
    def _safe_suffix(original_filename: str) -> str:
        suffix = Path(original_filename).suffix.lower()
        if suffix and re.fullmatch(r"\\.[a-z0-9]{1,10}", suffix):
            return suffix
        return ""
