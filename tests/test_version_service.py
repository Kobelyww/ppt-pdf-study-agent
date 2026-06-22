from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.db.models import Base, ContentVersionRecord
from src.services.version_service import ContentVersionService


def test_version_service_creates_incrementing_versions():
    service = ContentVersionService()

    first = service.create_version(
        target_type="outline",
        target_id="outline-1",
        content="# First outline",
        created_by="system",
        change_summary="initial generation",
    )
    second = service.create_version(
        target_type="outline",
        target_id="outline-1",
        content="# Edited outline",
        created_by="user-1",
        change_summary="user edited section title",
    )

    assert first.version == 1
    assert second.version == 2
    assert service.list_versions("outline", "outline-1")[-1].content == "# Edited outline"


def test_version_service_lists_versions_without_exposing_internal_storage():
    service = ContentVersionService()
    service.create_version(
        target_type="question",
        target_id="question-1",
        content="What is regression?",
        created_by="system",
        change_summary="initial question",
    )

    versions = service.list_versions("question", "question-1")
    versions.clear()

    assert len(service.list_versions("question", "question-1")) == 1


def test_content_version_record_can_be_persisted(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'versions.db'}")
    Base.metadata.create_all(engine)

    created_at = datetime.now(timezone.utc)
    with Session(engine) as session:
        session.add(
            ContentVersionRecord(
                id="outline:outline-1:v1",
                target_type="outline",
                target_id="outline-1",
                version=1,
                content="# First outline",
                created_by="system",
                created_at=created_at,
                change_summary="initial generation",
            )
        )
        session.commit()

    with Session(engine) as session:
        record = session.get(ContentVersionRecord, "outline:outline-1:v1")

    assert record is not None
    assert record.target_type == "outline"
    assert record.version == 1
    assert record.content == "# First outline"


def test_content_version_record_rejects_duplicate_target_version(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'versions.db'}")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add_all(
            [
                ContentVersionRecord(
                    id="outline:outline-1:v1",
                    target_type="outline",
                    target_id="outline-1",
                    version=1,
                    content="# First outline",
                    created_by="system",
                    created_at=datetime.now(timezone.utc),
                    change_summary="initial generation",
                ),
                ContentVersionRecord(
                    id="other-id",
                    target_type="outline",
                    target_id="outline-1",
                    version=1,
                    content="# Duplicate outline",
                    created_by="system",
                    created_at=datetime.now(timezone.utc),
                    change_summary="duplicate",
                ),
            ]
        )

        with pytest.raises(IntegrityError):
            session.commit()
