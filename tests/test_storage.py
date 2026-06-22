from hashlib import sha256
from pathlib import Path
from urllib.parse import unquote, urlparse

from src.storage import FileStore


def _path_from_file_uri(uri: str) -> Path:
    parsed = urlparse(uri)
    assert parsed.scheme == "file"
    return Path(unquote(parsed.path))


def test_save_bytes_stores_content_by_generated_name_and_preserves_metadata(tmp_path: Path):
    store = FileStore(tmp_path)

    saved = store.save_bytes(
        original_filename="Lecture Notes.pdf",
        content=b"abc",
        content_type="application/pdf",
    )

    saved_path = _path_from_file_uri(saved.storage_uri)
    assert saved_path.exists()
    assert saved_path.is_relative_to(tmp_path.resolve())
    assert saved_path.read_bytes() == b"abc"
    assert "Lecture Notes" not in saved_path.name
    assert saved.original_filename == "Lecture Notes.pdf"
    assert saved.content_type == "application/pdf"
    assert saved.size_bytes == 3
    assert saved.content_hash == f"sha256:{sha256(b'abc').hexdigest()}"


def test_save_bytes_uses_stable_checksum_for_same_content(tmp_path: Path):
    store = FileStore(tmp_path)

    first = store.save_bytes(
        original_filename="first.pdf",
        content=b"same document",
        content_type="application/pdf",
    )
    second = store.save_bytes(
        original_filename="second.pdf",
        content=b"same document",
        content_type="application/pdf",
    )

    assert first.content_hash == second.content_hash
    assert _path_from_file_uri(first.storage_uri).name != "first.pdf"
    assert _path_from_file_uri(second.storage_uri).name != "second.pdf"


def test_save_bytes_uses_absolute_file_uri_for_relative_roots(tmp_path: Path, monkeypatch):
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    store = FileStore("uploads")

    saved = store.save_bytes(
        original_filename="relative.pdf",
        content=b"content",
        content_type="application/pdf",
    )

    saved_path = _path_from_file_uri(saved.storage_uri)
    assert saved_path.is_absolute()
    assert saved_path.is_relative_to((workdir / "uploads").resolve())


def test_save_bytes_strips_suspicious_suffixes(tmp_path: Path):
    store = FileStore(tmp_path)

    saved = store.save_bytes(
        original_filename="../Lecture.P$D",
        content=b"content",
        content_type="application/pdf",
    )

    saved_path = _path_from_file_uri(saved.storage_uri)
    assert saved_path.suffix == ""
    assert "$" not in saved_path.name
