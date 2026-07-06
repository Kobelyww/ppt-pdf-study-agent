from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base, ReviewTaskRecord
from src.services.study_agent_review_tasks import (
    StudyAgentReviewTaskService,
    safe_review_task_metadata,
)


def _session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _workflow(*, workflow_id: str = "workflow-1", needs_review: bool = True) -> dict:
    return {
        "workflow_id": workflow_id,
        "status": "needs_review" if needs_review else "completed",
        "current_stage": "review_gate" if needs_review else "trace",
        "needs_review": needs_review,
        "stage_count": 2,
        "stages": [
            {
                "stage": "intake",
                "status": "passed",
                "input_summary": {
                    "workflow_id": workflow_id,
                    "query": "什么是导数",
                    "prompt": "hidden prompt",
                    "document_count": 2,
                },
                "output_summary": {
                    "selected_mode": "simple_rag",
                    "answer": "generated answer text",
                    "source_count": 3,
                },
            },
            {
                "stage": "review_gate",
                "status": "needs_review" if needs_review else "passed",
                "review_reason": "low_confidence" if needs_review else None,
                "input_summary": {"chunk_content": "导数原文"},
                "output_summary": {
                    "needs_review": needs_review,
                    "review_reason": "low_source_recall" if needs_review else None,
                    "confidence": 0.42,
                    "source_recall": 0.5,
                    "answer_term_recall": 0.25,
                    "chunk_count": 4,
                    "citation_count": 1,
                    "issue_count": 2,
                    "token": "sk-secret-token",
                },
            },
        ],
    }


def test_safe_review_task_metadata_omits_nested_raw_content_and_keeps_safe_counts():
    metadata = safe_review_task_metadata(
        workflow=_workflow(),
        trace_payload={
            "trace_id": "trace-1",
            "selected_mode": "agentic_rag",
            "confidence": 0.4,
            "source_recall": 0.5,
            "answer_term_recall": 0.25,
            "source_count": 3,
            "used_chunk_count": 4,
            "query": "什么是导数",
        },
        result_audit_metadata={
            "mode": "simple_rag",
            "source_count": 3,
            "chunk_count": 4,
            "citation_count": 1,
            "issue_count": 2,
            "prompt": "hidden prompt",
        },
    )

    assert metadata == {
        "workflow_id": "workflow-1",
        "trace_id": "trace-1",
        "selected_mode": "agentic_rag",
        "review_reasons": ["low_confidence", "low_source_recall"],
        "confidence": 0.4,
        "source_recall": 0.5,
        "answer_term_recall": 0.25,
        "source_count": 3,
        "chunk_count": 4,
        "citation_count": 1,
        "issue_count": 2,
    }
    serialized = str(metadata)
    for forbidden in [
        "什么是导数",
        "generated answer text",
        "导数原文",
        "hidden prompt",
        "sk-secret-token",
        "input_summary",
        "output_summary",
    ]:
        assert forbidden not in serialized


def test_ensure_for_workflow_creates_one_open_task_when_workflow_needs_review():
    Session = _session_factory()
    service = StudyAgentReviewTaskService(Session)

    task = service.ensure_for_workflow(
        owner_id="owner-1",
        request_id="req-1",
        workflow=_workflow(),
        trace_payload={"trace_id": "trace-1"},
        result_audit_metadata={},
    )

    assert task is not None
    assert task["target_type"] == "study_agent_workflow"
    assert task["target_id"] == "workflow-1"
    assert task["status"] == "open"
    assert task["reason"] == "low_confidence"
    assert task["metadata"]["workflow_id"] == "workflow-1"
    with Session() as session:
        records = session.query(ReviewTaskRecord).all()
    assert len(records) == 1


def test_ensure_for_workflow_reuses_open_task_for_same_owner_and_workflow():
    Session = _session_factory()
    service = StudyAgentReviewTaskService(Session)

    first = service.ensure_for_workflow(
        owner_id="owner-1",
        request_id="req-1",
        workflow=_workflow(),
        trace_payload={"trace_id": "trace-1"},
        result_audit_metadata={},
    )
    second = service.ensure_for_workflow(
        owner_id="owner-1",
        request_id="req-2",
        workflow=_workflow(),
        trace_payload={"trace_id": "trace-2"},
        result_audit_metadata={},
    )

    assert first is not None
    assert second is not None
    assert second["id"] == first["id"]
    with Session() as session:
        records = session.query(ReviewTaskRecord).all()
    assert len(records) == 1


def test_ensure_for_workflow_is_owner_scoped_for_same_workflow_id():
    Session = _session_factory()
    service = StudyAgentReviewTaskService(Session)

    owner_one_first = service.ensure_for_workflow(
        owner_id="owner-1",
        request_id="req-1",
        workflow=_workflow(),
        trace_payload={"trace_id": "trace-1"},
        result_audit_metadata={},
    )
    owner_two = service.ensure_for_workflow(
        owner_id="owner-2",
        request_id="req-2",
        workflow=_workflow(),
        trace_payload={"trace_id": "trace-2"},
        result_audit_metadata={},
    )
    owner_one_second = service.ensure_for_workflow(
        owner_id="owner-1",
        request_id="req-3",
        workflow=_workflow(),
        trace_payload={"trace_id": "trace-3"},
        result_audit_metadata={},
    )

    assert owner_one_first is not None
    assert owner_two is not None
    assert owner_one_second is not None
    assert owner_two["id"] != owner_one_first["id"]
    assert owner_one_second["id"] == owner_one_first["id"]
    with Session() as session:
        records = session.query(ReviewTaskRecord).all()
    assert len(records) == 2


def test_ensure_for_workflow_skips_workflow_that_does_not_need_review():
    Session = _session_factory()
    service = StudyAgentReviewTaskService(Session)

    task = service.ensure_for_workflow(
        owner_id="owner-1",
        request_id="req-1",
        workflow=_workflow(needs_review=False),
        trace_payload={"trace_id": "trace-1"},
        result_audit_metadata={},
    )

    assert task is None
    with Session() as session:
        records = session.query(ReviewTaskRecord).all()
    assert records == []
