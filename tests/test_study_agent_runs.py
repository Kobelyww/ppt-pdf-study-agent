from __future__ import annotations

import pytest
from sqlalchemy import create_engine

from src.db import Base, create_session_factory
from src.services.study_agent_runs import (
    StudyAgentRunConflict,
    StudyAgentRunNotFound,
    StudyAgentRunService,
)


def _service(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'runs.db'}")
    Base.metadata.create_all(engine)
    return StudyAgentRunService(create_session_factory(engine))


def _payload() -> dict:
    return {
        "query": "Explain the private derivative note",
        "target": "answer",
        "document_ids": ["doc-1"],
        "preferred_mode": "simple_rag",
        "budget": "balanced",
        "expected_terms": ["derivative", "slope"],
        "skill_name": "concept_explanation",
        "skill_version": "v1",
    }


def test_create_run_stores_safe_request_metadata_without_raw_query(tmp_path):
    service = _service(tmp_path)

    run = service.create_run(
        owner_id="user-1",
        request_id="req-1",
        payload=_payload(),
    )

    assert run["id"].startswith("run-")
    assert run["status"] == "queued"
    assert run["query_hash"].startswith("sha256:")
    assert run["target"] == "answer"
    assert run["document_ids"] == ["doc-1"]
    assert run["preferred_mode"] == "simple_rag"
    assert run["budget"] == "balanced"
    assert run["skill_name"] == "concept_explanation"
    assert run["skill_version"] == "v1"
    assert run["expected_term_count"] == 2
    assert "explain the" not in str(run).lower()
    assert "private derivative note" not in str(run).lower()


def test_create_run_drops_unsafe_request_metadata_labels(tmp_path):
    service = _service(tmp_path)

    run = service.create_run(
        owner_id="user-1",
        request_id="req-1",
        payload={
            "query": "Safe hash only",
            "target": "/tmp/target sk-secret-token",
            "document_ids": ["doc-safe-1", "/Users/private.pdf", "sk-secret-token"],
            "preferred_mode": "../../agentic_rag",
            "budget": "sk-secret-token",
            "skill_name": "concept_explanation",
            "skill_version": "v1",
            "expected_terms": ["a"],
        },
    )

    assert run["target"] == "unknown"
    assert run["preferred_mode"] is None
    assert run["budget"] is None
    assert run["document_ids"] == ["doc-safe-1"]
    assert run["skill_name"] == "concept_explanation"
    assert run["skill_version"] == "v1"
    assert run["query_hash"].startswith("sha256:")

    serialized = str(run)
    assert "/tmp" not in serialized
    assert "/Users/private" not in serialized
    assert "sk-secret-token" not in serialized
    assert "../../" not in serialized


def test_mark_completed_stores_safe_result_summary_only(tmp_path):
    service = _service(tmp_path)
    run = service.create_run(owner_id="user-1", request_id="req-1", payload=_payload())
    running = service.mark_running(owner_id="user-1", run_id=run["id"])

    completed = service.mark_terminal(
        owner_id="user-1",
        run_id=running["id"],
        status="completed",
        result_summary={
            "trace_id": "trace-abc",
            "workflow_id": "workflow-" + "a" * 32,
            "review_task_id": "review-1",
            "selected_mode": "simple_rag",
            "policy_status": "allowed",
            "category": "definition",
            "source_count": 1,
            "used_chunk_count": 1,
            "confidence": 0.83,
            "source_recall": 1.0,
            "answer_term_recall": 1.0,
            "needs_review": False,
            "latency_ms": 12.5,
            "stage_count": 8,
            "answer": "raw generated answer",
            "prompt": "hidden prompt",
            "token": "sk-secret-token",
        },
    )

    assert completed["status"] == "completed"
    assert completed["trace_id"] == "trace-abc"
    assert completed["workflow_id"] == "workflow-" + "a" * 32
    assert completed["result_summary"] == {
        "trace_id": "trace-abc",
        "workflow_id": "workflow-" + "a" * 32,
        "review_task_id": "review-1",
        "selected_mode": "simple_rag",
        "policy_status": "allowed",
        "category": "definition",
        "source_count": 1,
        "used_chunk_count": 1,
        "confidence": 0.83,
        "source_recall": 1.0,
        "answer_term_recall": 1.0,
        "needs_review": False,
        "latency_ms": 12.5,
        "stage_count": 8,
    }
    serialized = str(completed).lower()
    assert "raw generated answer" not in serialized
    assert "hidden prompt" not in serialized
    assert "sk-secret-token" not in serialized


def test_mark_completed_rejects_unsafe_allowed_string_result_values(tmp_path):
    service = _service(tmp_path)
    run = service.create_run(owner_id="user-1", request_id="req-1", payload=_payload())
    running = service.mark_running(owner_id="user-1", run_id=run["id"])

    completed = service.mark_terminal(
        owner_id="user-1",
        run_id=running["id"],
        status="completed",
        result_summary={
            "trace_id": "trace-safe-1",
            "workflow_id": "workflow-" + "a" * 32,
            "review_task_id": "review-safe-1",
            "selected_mode": "../../agentic_rag",
            "policy_status": "sk-secret-token",
            "category": "/tmp/private-category",
            "source_count": 2,
            "confidence": 0.9,
            "needs_review": False,
            "latency_ms": 12.5,
            "stage_count": 8,
            "expert_enabled": True,
            "expert_branch_count": 1,
            "token": "sk-secret-token",
            "answer": "raw answer",
        },
    )

    assert completed["trace_id"] == "trace-safe-1"
    assert completed["workflow_id"] == "workflow-" + "a" * 32
    assert completed["review_task_id"] == "review-safe-1"
    assert completed["result_summary"].get("trace_id") == "trace-safe-1"
    assert completed["result_summary"].get("workflow_id") == "workflow-" + "a" * 32
    assert completed["result_summary"].get("review_task_id") == "review-safe-1"
    assert completed["result_summary"].get("selected_mode") is None
    assert completed["result_summary"].get("policy_status") is None
    assert completed["result_summary"].get("category") is None
    assert completed["result_summary"]["source_count"] == 2
    assert completed["result_summary"]["confidence"] == 0.9
    assert completed["result_summary"]["needs_review"] is False
    assert completed["result_summary"]["latency_ms"] == 12.5
    assert completed["result_summary"]["stage_count"] == 8
    assert completed["result_summary"]["expert_enabled"] is True
    assert completed["result_summary"]["expert_branch_count"] == 1

    serialized = str(completed).lower()
    assert "sk-secret-token" not in serialized
    assert "/tmp/private" not in serialized
    assert "../../" not in serialized
    assert "raw answer" not in serialized


def test_mark_failed_persists_only_safe_error_labels(tmp_path):
    service = _service(tmp_path)
    run = service.create_run(owner_id="user-1", request_id="req-1", payload=_payload())
    service.mark_running(owner_id="user-1", run_id=run["id"])

    failed = service.mark_terminal(
        owner_id="user-1",
        run_id=run["id"],
        status="failed",
        error_code="ValueError /tmp/private sk-secret-token",
        error_message="Traceback token sk-secret-token /Users/private",
    )
    persisted = service.get_run(owner_id="user-1", run_id=run["id"])

    for observed in (failed, persisted):
        assert observed["error_code"] in {"unknown", "run_failed"}
        assert observed["error_message"] in {"unknown", "run_failed"}
        serialized = str(observed)
        assert "sk-secret-token" not in serialized
        assert "/tmp" not in serialized
        assert "/Users/private" not in serialized
        assert "Traceback" not in serialized
        assert "ValueError" not in serialized


def test_control_transitions_enforce_allowed_statuses(tmp_path):
    service = _service(tmp_path)
    run = service.create_run(owner_id="user-1", request_id="req-1", payload=_payload())
    paused = service.pause(owner_id="user-1", run_id=run["id"])
    assert paused["status"] == "paused"
    resumed = service.resume(owner_id="user-1", run_id=run["id"])
    assert resumed["status"] == "queued"
    cancelled = service.cancel(owner_id="user-1", run_id=run["id"])
    assert cancelled["status"] == "cancelled"

    with pytest.raises(StudyAgentRunConflict):
        service.pause(owner_id="user-1", run_id=run["id"])


def test_retry_child_links_to_parent_without_reusing_raw_query(tmp_path):
    service = _service(tmp_path)
    parent = service.create_run(owner_id="user-1", request_id="req-1", payload=_payload())
    service.mark_running(owner_id="user-1", run_id=parent["id"])
    service.mark_terminal(
        owner_id="user-1",
        run_id=parent["id"],
        status="failed",
        error_code="bad_study_request",
        error_message="bad_study_request",
    )

    child = service.create_retry_run(
        owner_id="user-1",
        request_id="req-2",
        parent_run_id=parent["id"],
        payload={**_payload(), "query": "Fresh retry query"},
    )

    assert child["retry_of_run_id"] == parent["id"]
    assert child["attempt"] == 2
    assert "fresh retry query" not in str(child).lower()


def test_owner_isolation_for_detail_and_controls(tmp_path):
    service = _service(tmp_path)
    run = service.create_run(owner_id="user-1", request_id="req-1", payload=_payload())

    assert service.get_run(owner_id="user-1", run_id=run["id"])["id"] == run["id"]
    assert service.get_run(owner_id="user-2", run_id=run["id"]) is None
    assert service.run_exists(run["id"]) is True
    with pytest.raises(StudyAgentRunNotFound):
        service.cancel(owner_id="user-2", run_id=run["id"])


def test_list_runs_excludes_archived_by_default_and_filters_status(tmp_path):
    service = _service(tmp_path)
    first = service.create_run(owner_id="user-1", request_id="req-1", payload=_payload())
    second = service.create_run(owner_id="user-1", request_id="req-2", payload=_payload())
    service.mark_running(owner_id="user-1", run_id=first["id"])
    service.mark_terminal(owner_id="user-1", run_id=first["id"], status="completed")
    service.archive(owner_id="user-1", run_id=first["id"])

    active = service.list_runs(owner_id="user-1")
    assert [run["id"] for run in active] == [second["id"]]

    archived = service.list_runs(owner_id="user-1", status="archived")
    assert [run["id"] for run in archived] == [first["id"]]

    with_archived = service.list_runs(owner_id="user-1", include_archived=True)
    assert {run["id"] for run in with_archived} == {first["id"], second["id"]}
