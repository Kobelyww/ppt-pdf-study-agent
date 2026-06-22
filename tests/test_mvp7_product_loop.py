from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.app import create_app
from src.db.models import Base
from src.services.document_service import DocumentService
from src.services.version_service import create_persisted_version
from src.storage.backend import LocalStorageBackend


def test_mvp7_internal_beta_product_loop(tmp_path: Path):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    service = DocumentService(
        session_factory=Session,
        storage=LocalStorageBackend(tmp_path / "objects"),
    )
    client = TestClient(create_app(document_service=service))

    upload = client.post(
        "/api/documents",
        headers={"x-user-id": "user-1"},
        files={"file": ("notes.pdf", b"Derivatives measure change.", "application/pdf")},
    )
    assert upload.status_code == 202
    document_id = upload.json()["document"]["id"]

    create_persisted_version(
        session_factory=Session,
        document_id=document_id,
        target_type="outline",
        target_id=document_id,
        content="# Derivatives",
        created_by="test",
        change_summary="test outline",
        content_metadata={},
    )
    create_persisted_version(
        session_factory=Session,
        document_id=document_id,
        target_type="question_set",
        target_id=document_id,
        content="# Question Set",
        created_by="test",
        change_summary="test questions",
        content_metadata={},
    )

    assert client.get("/api/documents", headers={"x-user-id": "user-1"}).status_code == 200
    assert (
        client.get(
            f"/api/documents/{document_id}/outline",
            headers={"x-user-id": "user-1"},
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"/api/documents/{document_id}/questions",
            headers={"x-user-id": "user-1"},
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"/api/documents/{document_id}",
            headers={"x-user-id": "user-2"},
        ).status_code
        == 403
    )
