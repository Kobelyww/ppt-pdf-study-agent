import json
from datetime import datetime, timezone

from src.services.rag_router import RetrievalMode
from src.services.rag_service import Chunk
from src.services.study_agent import (
    EvidenceBundle,
    StudyDraft,
    StudyTarget,
    StudyVerification,
)
from src.services.study_agent_workflow import (
    ReviewGate,
    WorkflowStageName,
    WorkflowStageResult,
    WorkflowStageStatus,
    WorkflowStatus,
    build_workflow_payload,
    sanitize_stage_summary,
    summarize_workflow_status,
)


def test_stage_result_serializes_safe_payload_without_private_values():
    started_at = datetime(2026, 6, 29, tzinfo=timezone.utc)
    completed_at = datetime(2026, 6, 29, 0, 0, 1, tzinfo=timezone.utc)

    stage = WorkflowStageResult(
        stage_name=WorkflowStageName.RETRIEVE,
        status=WorkflowStageStatus.PASSED,
        input_summary={
            "query": "什么是导数？",
            "document_count": 1,
            "mode": "simple_rag",
            "token": "secret-token",
        },
        output_summary={
            "chunk_count": 1,
            "source_count": 1,
            "chunk_content": "导数描述函数变化率。",
            "fallback_reason": None,
        },
        started_at=started_at,
        completed_at=completed_at,
        duration_ms=1000.0,
    )

    payload = stage.to_safe_dict()

    assert payload == {
        "stage": "retrieve",
        "status": "passed",
        "duration_ms": 1000.0,
        "input_summary": {"document_count": 1, "mode": "simple_rag"},
        "output_summary": {
            "chunk_count": 1,
            "source_count": 1,
            "fallback_reason": None,
        },
        "error_code": None,
        "review_reason": None,
    }
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "什么是导数" not in serialized
    assert "secret-token" not in serialized
    assert "导数描述" not in serialized


def test_sanitize_stage_summary_buckets_unknown_or_unsafe_values():
    summary = sanitize_stage_summary(
        {
            "stage": "retrieve",
            "mode": "raw query: 什么是导数？",
            "category": "definition",
            "fallback_reason": "persisted_chunks_missing",
            "review_reason": "missing_citations",
            "authorization": "Bearer secret-token",
            "chunk_count": "3",
            "needs_review": True,
        }
    )

    assert summary == {
        "stage": "retrieve",
        "mode": "unknown",
        "category": "definition",
        "fallback_reason": "persisted_chunks_missing",
        "review_reason": "missing_citations",
        "chunk_count": 3,
        "needs_review": True,
    }


def test_summarize_workflow_status_prefers_failed_then_needs_review_then_fallback():
    failed = WorkflowStageResult(
        stage_name=WorkflowStageName.RETRIEVE,
        status=WorkflowStageStatus.FAILED,
        input_summary={},
        output_summary={},
        error_code="document_evidence_missing",
    )
    needs_review = WorkflowStageResult(
        stage_name=WorkflowStageName.REVIEW_GATE,
        status=WorkflowStageStatus.NEEDS_REVIEW,
        input_summary={},
        output_summary={},
        review_reason="low_confidence",
    )
    fallback = WorkflowStageResult(
        stage_name=WorkflowStageName.RETRIEVE,
        status=WorkflowStageStatus.PASSED,
        input_summary={},
        output_summary={"fallback_reason": "persisted_chunks_missing"},
    )

    assert summarize_workflow_status([failed]) == WorkflowStatus.FAILED
    assert summarize_workflow_status([fallback, needs_review]) == WorkflowStatus.NEEDS_REVIEW
    assert summarize_workflow_status([fallback]) == WorkflowStatus.COMPLETED_WITH_FALLBACK


def test_review_gate_marks_missing_citations_and_synthesis_fallback_for_review():
    gate = ReviewGate(confidence_threshold=0.5)
    evidence = EvidenceBundle(
        mode=RetrievalMode.SIMPLE,
        chunks=(Chunk(content="private", source="doc:1"),),
        sources=("doc:1",),
        concept_ids=(),
        confidence=0.8,
        reason="simple",
        fallback_reason="agentic evidence unavailable",
    )
    draft = StudyDraft(
        target=StudyTarget.QUESTION,
        content="private generated answer",
        citations=(),
        used_chunk_count=1,
    )
    verification = StudyVerification(
        passed=False,
        needs_review=True,
        confidence=0.4,
        issues=("missing citations",),
        source_recall=0.0,
        answer_term_recall=1.0,
    )

    decision = gate.evaluate(
        target=StudyTarget.QUESTION,
        evidence=evidence,
        draft=draft,
        verification=verification,
        policy_status="allowed",
    )

    assert decision.status == WorkflowStageStatus.NEEDS_REVIEW
    assert decision.review_reasons == (
        "verification_failed",
        "low_confidence",
        "missing_citations",
        "target_used_fallback_evidence",
    )


def test_build_workflow_payload_uses_safe_stage_payloads():
    stage = WorkflowStageResult(
        stage_name=WorkflowStageName.INTAKE,
        status=WorkflowStageStatus.PASSED,
        input_summary={"query": "什么是导数？"},
        output_summary={"document_count": 1, "target": "answer"},
    )

    payload = build_workflow_payload(
        workflow_id="workflow-1",
        stages=[stage],
        needs_review=False,
    )

    assert payload["workflow_id"] == "workflow-1"
    assert payload["status"] == "completed"
    assert payload["current_stage"] == "intake"
    assert payload["needs_review"] is False
    assert payload["stage_count"] == 1
    assert payload["stages"][0]["output_summary"] == {
        "document_count": 1,
        "target": "answer",
    }
    assert "什么是导数" not in json.dumps(payload, ensure_ascii=False)
