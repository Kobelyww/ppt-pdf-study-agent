from pathlib import Path

import pytest

from src.storage.backend import LocalStorageBackend, StorageError


def test_local_storage_backend_puts_and_reads_upload(tmp_path: Path):
    backend = LocalStorageBackend(root=tmp_path)

    stored = backend.put_bytes(
        namespace="uploads",
        original_filename="Lecture Notes.pdf",
        content=b"study content",
        content_type="application/pdf",
    )

    assert stored.storage_uri.startswith("local://uploads/")
    assert stored.original_filename == "Lecture Notes.pdf"
    assert stored.content_type == "application/pdf"
    assert stored.size_bytes == len(b"study content")
    assert backend.exists(stored.storage_uri)
    assert backend.read_bytes(stored.storage_uri) == b"study content"


def test_local_storage_backend_rejects_path_traversal_uri(tmp_path: Path):
    backend = LocalStorageBackend(root=tmp_path)

    with pytest.raises(StorageError, match="invalid storage uri"):
        backend.read_bytes("local://uploads/../secret.txt")


def test_local_storage_backend_writes_export_namespace(tmp_path: Path):
    backend = LocalStorageBackend(root=tmp_path)

    stored = backend.put_bytes(
        namespace="exports",
        original_filename="outline.md",
        content=b"# Outline",
        content_type="text/markdown",
    )

    assert stored.storage_uri.startswith("local://exports/")
    assert backend.read_bytes(stored.storage_uri) == b"# Outline"
