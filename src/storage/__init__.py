from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from src.storage.backend import LocalStorageBackend, StorageBackend, StoredObject, StorageError


@dataclass(frozen=True)
class SavedFile:
    storage_uri: str
    content_hash: str
    original_filename: str
    content_type: str
    size_bytes: int


class FileStore:
    def __init__(self, root: Path | str):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def save_bytes(
        self,
        *,
        original_filename: str,
        content: bytes,
        content_type: str,
    ) -> SavedFile:
        suffix = LocalStorageBackend._safe_suffix(original_filename)
        target_path = self.root / f"{uuid4().hex}{suffix}"
        target_path.write_bytes(content)
        return SavedFile(
            storage_uri=target_path.resolve().as_uri(),
            content_hash=f"sha256:{sha256(content).hexdigest()}",
            original_filename=original_filename,
            content_type=content_type,
            size_bytes=len(content),
        )


__all__ = [
    "FileStore",
    "LocalStorageBackend",
    "SavedFile",
    "StorageBackend",
    "StorageError",
    "StoredObject",
]
