from datetime import datetime, timedelta, timezone
import json

import pytest
from sqlalchemy import create_engine

from src.db import Base, create_session_factory
from src.services.study_agent_memory import StudyAgentMemoryService


@pytest.fixture()
def memory_service(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'memory.db'}")
    Base.metadata.create_all(engine)
    Session = create_session_factory(engine)
    return StudyAgentMemoryService(Session)


def test_memory_store_and_recall_is_owner_scoped(memory_service):
    memory_service.store_preference("owner-1", "answer_style", "concise", "source-1")
    memory_service.store_preference("owner-2", "answer_style", "detailed", "source-2")

    summary = memory_service.summary("owner-1")

    assert summary["preferences"] == {"answer_style": "concise"}
    assert "detailed" not in json.dumps(summary, sort_keys=True)
    assert summary["memory_record_count"] == 1


def test_memory_rejects_raw_content_like_values(memory_service):
    memory_id = memory_service.store_review_outcome(
        owner_id="owner-1",
        workflow_id="workflow-1",
        review_task_id="review-1",
        reasons=["low_confidence"],
        decision="accepted",
        metadata={
            "query": "raw private query",
            "chunk_content": "raw chunk text",
            "token": "sk-secret",
            "confidence": 0.2,
        },
    )

    summary = memory_service.summary("owner-1")
    encoded_summary = json.dumps(summary, sort_keys=True)

    assert memory_id.startswith("memory-")
    assert summary["review_reason_counts"] == {"low_confidence": 1}
    assert "raw private query" not in encoded_summary
    assert "raw chunk text" not in encoded_summary
    assert "sk-secret" not in encoded_summary


def test_expired_memory_is_not_recalled(memory_service):
    memory_service.store_preference(
        "owner-1",
        "answer_style",
        "concise",
        "source-1",
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )

    assert memory_service.summary("owner-1") == {
        "preferences": {},
        "review_reason_counts": {},
        "memory_record_count": 0,
    }


def test_memory_summary_is_deterministic_for_identical_inputs(memory_service):
    memory_service.store_preference("owner-1", "language", "zh", "source-1")
    memory_service.store_review_outcome(
        "owner-1",
        "workflow-1",
        "review-1",
        ["missing_citations", "low_confidence"],
        "unexpected_decision",
        metadata={"confidence": 0.41, "source_count": 2, "chunk_count": 3},
    )

    assert memory_service.summary("owner-1") == memory_service.summary("owner-1")


def test_delete_memory_is_owner_scoped(memory_service):
    memory_id = memory_service.store_preference(
        "owner-2", "answer_style", "detailed", "source-1"
    )

    assert memory_service.delete_memory("owner-1", memory_id) is False
    assert memory_service.summary("owner-2")["preferences"] == {
        "answer_style": "detailed"
    }

    assert memory_service.delete_memory("owner-2", memory_id) is True
    assert memory_service.summary("owner-2") == {
        "preferences": {},
        "review_reason_counts": {},
        "memory_record_count": 0,
    }


def test_preference_rejects_unsupported_value(memory_service):
    with pytest.raises(ValueError):
        memory_service.store_preference("owner-1", "answer_style", "verbose", "source-1")

    with pytest.raises(ValueError):
        memory_service.store_preference("owner-1", "favorite_prompt", "concise", "source-1")
