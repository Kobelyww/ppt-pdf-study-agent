from datetime import datetime, timedelta, timezone
import json

import pytest
from sqlalchemy import create_engine

from src.db import Base, StudyAgentMemoryRecord, create_session_factory
from src.services.study_agent_memory import StudyAgentMemoryService


@pytest.fixture()
def memory_context(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'memory.db'}")
    Base.metadata.create_all(engine)
    Session = create_session_factory(engine)
    return StudyAgentMemoryService(Session), Session


@pytest.fixture()
def memory_service(memory_context):
    service, _Session = memory_context
    return service


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


def test_review_outcome_rejects_empty_or_unknown_reasons(memory_service):
    for reasons in ([], ["raw_private_reason"]):
        with pytest.raises(ValueError, match="requires at least one safe reason"):
            memory_service.store_review_outcome(
                owner_id="owner-1",
                workflow_id="workflow-1",
                review_task_id="review-1",
                reasons=reasons,
                decision="accepted",
                metadata={"confidence": 0.2},
            )

    assert memory_service.summary("owner-1")["memory_record_count"] == 0


def test_memory_rejects_private_looking_ids_before_persisting(memory_context):
    service, Session = memory_context

    with pytest.raises(ValueError):
        service.store_preference(
            "owner-1",
            "answer_style",
            "concise",
            "raw private query with spaces",
        )

    with pytest.raises(ValueError):
        service.store_review_outcome(
            owner_id="owner-1",
            workflow_id="workflow raw private query",
            review_task_id="review-1",
            reasons=["low_confidence"],
            decision="accepted",
            metadata={"confidence": 0.2},
        )

    with pytest.raises(ValueError):
        service.store_review_outcome(
            owner_id="owner-1",
            workflow_id="workflow-1",
            review_task_id="r" * 129,
            reasons=["low_confidence"],
            decision="accepted",
            metadata={"confidence": 0.2},
        )

    with Session() as session:
        assert session.query(StudyAgentMemoryRecord).count() == 0


def test_review_outcome_persisted_value_json_excludes_raw_metadata(memory_context):
    service, Session = memory_context

    memory_id = service.store_review_outcome(
        owner_id="owner-1",
        workflow_id="workflow-1",
        review_task_id="review-1",
        reasons=["low_confidence"],
        decision="accepted",
        metadata={
            "query": "raw private query",
            "chunk_content": "raw chunk text",
            "token": "sk-secret",
            "source_snippet": "raw source snippet",
            "nested": {"prompt": "raw hidden prompt"},
            "confidence": 0.2,
            "source_count": 3,
            "chunk_count": 4,
        },
    )

    with Session() as session:
        record = session.get(StudyAgentMemoryRecord, memory_id)

    encoded_value = json.dumps(record.value_json, sort_keys=True)
    assert record.value_json == {
        "decision": "accepted",
        "reasons": ["low_confidence"],
        "metrics": {"chunk_count": 4, "confidence": 0.2, "source_count": 3},
    }
    assert "query" not in encoded_value
    assert "chunk_content" not in encoded_value
    assert "token" not in encoded_value
    assert "source_snippet" not in encoded_value
    assert "nested" not in encoded_value
    assert "prompt" not in encoded_value
    assert "raw private query" not in encoded_value
    assert "raw chunk text" not in encoded_value
    assert "sk-secret" not in encoded_value
    assert "raw source snippet" not in encoded_value
    assert "raw hidden prompt" not in encoded_value


def test_review_outcome_is_idempotent_per_review_task(memory_context):
    service, Session = memory_context

    first_id = service.store_review_outcome(
        owner_id="owner-1",
        workflow_id="workflow-1",
        review_task_id="review-1",
        reasons=["low_confidence"],
        decision="accepted",
        metadata={"confidence": 0.2, "source_count": 1, "chunk_count": 2},
    )
    second_id = service.store_review_outcome(
        owner_id="owner-1",
        workflow_id="workflow-1",
        review_task_id="review-1",
        reasons=["low_confidence"],
        decision="resolved",
        metadata={"confidence": 0.4, "source_count": 3, "chunk_count": 4},
    )

    assert second_id == first_id
    assert service.summary("owner-1")["review_reason_counts"] == {"low_confidence": 1}
    with Session() as session:
        records = session.query(StudyAgentMemoryRecord).all()

    assert len(records) == 1
    assert records[0].value_json == {
        "decision": "resolved",
        "reasons": ["low_confidence"],
        "metrics": {"chunk_count": 4, "confidence": 0.4, "source_count": 3},
    }
    assert records[0].confidence == 0.4


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
