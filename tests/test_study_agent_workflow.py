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
    new_workflow_id,
    sanitize_stage_summary,
    sanitize_workflow_payload,
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


def test_stage_result_normalizes_unsafe_duration_values():
    stage = WorkflowStageResult(
        stage_name=WorkflowStageName.RETRIEVE,
        status=WorkflowStageStatus.PASSED,
        input_summary={},
        output_summary={},
        duration_ms="private text",
    )

    payload = stage.to_safe_dict()

    assert payload["duration_ms"] == 0.0
    assert "private text" not in json.dumps(payload, ensure_ascii=False)


def test_stage_result_normalizes_non_finite_bool_and_missing_duration_values():
    for duration in (float("nan"), float("inf"), True):
        stage = WorkflowStageResult(
            stage_name=WorkflowStageName.RETRIEVE,
            status=WorkflowStageStatus.PASSED,
            input_summary={},
            output_summary={},
            duration_ms=duration,
        )

        assert stage.to_safe_dict()["duration_ms"] == 0.0

    missing_duration = WorkflowStageResult(
        stage_name=WorkflowStageName.RETRIEVE,
        status=WorkflowStageStatus.PASSED,
        input_summary={},
        output_summary={},
        duration_ms=None,
    )

    assert missing_duration.to_safe_dict()["duration_ms"] is None


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


def test_sanitize_stage_summary_normalizes_bool_count_values_to_zero():
    assert sanitize_stage_summary({"chunk_count": True})["chunk_count"] == 0


def test_sanitize_stage_summary_normalizes_non_finite_float_values_to_zero():
    assert sanitize_stage_summary({"confidence": "nan"})["confidence"] == 0.0
    assert sanitize_stage_summary({"confidence": "inf"})["confidence"] == 0.0


def test_sanitize_stage_summary_normalizes_overflowing_float_values_to_zero():
    class OverflowingFloat:
        def __float__(self):
            raise OverflowError("too large")

    assert sanitize_stage_summary({"confidence": OverflowingFloat()})["confidence"] == 0.0


def test_sanitize_stage_summary_normalizes_non_finite_integer_values_to_zero():
    assert sanitize_stage_summary({"chunk_count": float("inf")})["chunk_count"] == 0
    assert sanitize_stage_summary({"chunk_count": float("nan")})["chunk_count"] == 0


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


def test_summarize_workflow_status_ignores_unrecognized_fallback_reason():
    stage = WorkflowStageResult(
        stage_name=WorkflowStageName.RETRIEVE,
        status=WorkflowStageStatus.PASSED,
        input_summary={},
        output_summary={"fallback_reason": "raw private fallback text"},
    )

    assert summarize_workflow_status([stage]) == WorkflowStatus.COMPLETED


def test_summarize_workflow_status_allows_graph_seed_fallback_reason():
    stage = WorkflowStageResult(
        stage_name=WorkflowStageName.RETRIEVE,
        status=WorkflowStageStatus.PASSED,
        input_summary={},
        output_summary={"fallback_reason": "matched graph seed but no chunks recovered"},
    )

    payload = build_workflow_payload(
        workflow_id="workflow-123",
        stages=[stage],
        needs_review=False,
    )

    assert summarize_workflow_status([stage]) == WorkflowStatus.COMPLETED_WITH_FALLBACK
    assert payload["status"] == "completed_with_fallback"


def test_summarize_workflow_status_prefers_partial_over_earlier_fallback():
    retrieve = WorkflowStageResult(
        stage_name=WorkflowStageName.RETRIEVE,
        status=WorkflowStageStatus.PASSED,
        input_summary={},
        output_summary={"fallback_reason": "persisted_chunks_missing"},
    )
    trace = WorkflowStageResult(
        stage_name=WorkflowStageName.TRACE,
        status=WorkflowStageStatus.RUNNING,
        input_summary={},
        output_summary={},
    )

    assert summarize_workflow_status([retrieve, trace]) == WorkflowStatus.PARTIAL


def test_summarize_workflow_status_mixed_priority_regressions():
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
    partial = WorkflowStageResult(
        stage_name=WorkflowStageName.TRACE,
        status=WorkflowStageStatus.RUNNING,
        input_summary={},
        output_summary={},
    )
    fallback = WorkflowStageResult(
        stage_name=WorkflowStageName.RETRIEVE,
        status=WorkflowStageStatus.PASSED,
        input_summary={},
        output_summary={"fallback_reason": "persisted_chunks_missing"},
    )

    assert (
        summarize_workflow_status([fallback, partial, needs_review, failed])
        == WorkflowStatus.FAILED
    )
    assert (
        summarize_workflow_status([fallback, partial, needs_review])
        == WorkflowStatus.NEEDS_REVIEW
    )


def test_summarize_workflow_status_marks_incomplete_stage_states_partial():
    for status in (
        WorkflowStageStatus.PENDING,
        WorkflowStageStatus.RUNNING,
        WorkflowStageStatus.SKIPPED,
    ):
        stage = WorkflowStageResult(
            stage_name=WorkflowStageName.RETRIEVE,
            status=status,
            input_summary={},
            output_summary={},
        )

        assert summarize_workflow_status([stage]) == WorkflowStatus.PARTIAL


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


def test_review_gate_marks_empty_evidence_for_review():
    gate = ReviewGate(confidence_threshold=0.5)
    evidence = EvidenceBundle(
        mode=RetrievalMode.SIMPLE,
        chunks=(),
        sources=(),
        concept_ids=(),
        confidence=0.8,
        reason="simple",
    )
    draft = StudyDraft(
        target=StudyTarget.ANSWER,
        content="answer",
        citations=("doc:1",),
        used_chunk_count=0,
    )
    verification = StudyVerification(
        passed=True,
        needs_review=False,
        confidence=0.8,
        issues=(),
        source_recall=1.0,
        answer_term_recall=1.0,
    )

    decision = gate.evaluate(
        target=StudyTarget.ANSWER,
        evidence=evidence,
        draft=draft,
        verification=verification,
        policy_status="allowed",
    )

    assert decision.status == WorkflowStageStatus.NEEDS_REVIEW
    assert decision.review_reasons == ("empty_evidence",)


def test_review_gate_marks_blocked_policy_without_successful_fallback_for_review():
    gate = ReviewGate(confidence_threshold=0.5)
    evidence = EvidenceBundle(
        mode=RetrievalMode.SIMPLE,
        chunks=(Chunk(content="private", source="doc:1"),),
        sources=("doc:1",),
        concept_ids=(),
        confidence=0.8,
        reason="simple",
    )
    draft = StudyDraft(
        target=StudyTarget.ANSWER,
        content="answer",
        citations=("doc:1",),
        used_chunk_count=1,
    )
    verification = StudyVerification(
        passed=True,
        needs_review=False,
        confidence=0.8,
        issues=(),
        source_recall=1.0,
        answer_term_recall=1.0,
    )

    decision = gate.evaluate(
        target=StudyTarget.ANSWER,
        evidence=evidence,
        draft=draft,
        verification=verification,
        policy_status="blocked_by_budget",
    )

    assert decision.status == WorkflowStageStatus.NEEDS_REVIEW
    assert decision.review_reasons == ("policy_blocked_without_fallback",)


def test_review_gate_ignores_unrecognized_blocked_policy_text_without_fallback():
    gate = ReviewGate(confidence_threshold=0.5)
    evidence = EvidenceBundle(
        mode=RetrievalMode.SIMPLE,
        chunks=(Chunk(content="private", source="doc:1"),),
        sources=("doc:1",),
        concept_ids=(),
        confidence=0.8,
        reason="simple",
    )
    draft = StudyDraft(
        target=StudyTarget.ANSWER,
        content="answer",
        citations=("doc:1",),
        used_chunk_count=1,
    )
    verification = StudyVerification(
        passed=True,
        needs_review=False,
        confidence=0.8,
        issues=(),
        source_recall=1.0,
        answer_term_recall=1.0,
    )

    decision = gate.evaluate(
        target=StudyTarget.ANSWER,
        evidence=evidence,
        draft=draft,
        verification=verification,
        policy_status="blocked private text",
    )

    assert decision.status == WorkflowStageStatus.PASSED
    assert "policy_blocked_without_fallback" not in decision.review_reasons


def test_review_gate_allows_blocked_policy_with_successful_fallback():
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
        target=StudyTarget.ANSWER,
        content="answer",
        citations=("doc:1",),
        used_chunk_count=1,
    )
    verification = StudyVerification(
        passed=True,
        needs_review=False,
        confidence=0.8,
        issues=(),
        source_recall=1.0,
        answer_term_recall=1.0,
    )

    decision = gate.evaluate(
        target=StudyTarget.ANSWER,
        evidence=evidence,
        draft=draft,
        verification=verification,
        policy_status="blocked_by_budget",
    )

    assert decision.status == WorkflowStageStatus.PASSED
    assert decision.review_reasons == ()


def test_review_gate_marks_agentic_step_budget_exhaustion_for_review():
    gate = ReviewGate(confidence_threshold=0.5)
    evidence = EvidenceBundle(
        mode=RetrievalMode.AGENTIC,
        chunks=(Chunk(content="private", source="doc:1"),),
        sources=("doc:1",),
        concept_ids=(),
        confidence=0.8,
        reason="agentic",
        metadata={"step_budget_exhausted": True},
    )
    draft = StudyDraft(
        target=StudyTarget.ANSWER,
        content="answer",
        citations=("doc:1",),
        used_chunk_count=1,
    )
    verification = StudyVerification(
        passed=True,
        needs_review=False,
        confidence=0.8,
        issues=(),
        source_recall=1.0,
        answer_term_recall=1.0,
    )

    decision = gate.evaluate(
        target=StudyTarget.ANSWER,
        evidence=evidence,
        draft=draft,
        verification=verification,
        policy_status="allowed",
    )

    assert decision.status == WorkflowStageStatus.NEEDS_REVIEW
    assert decision.review_reasons == ("agentic_step_budget_exhausted",)


def test_review_gate_passes_when_contract_conditions_are_satisfied():
    gate = ReviewGate(confidence_threshold=0.5)
    evidence = EvidenceBundle(
        mode=RetrievalMode.SIMPLE,
        chunks=(Chunk(content="private", source="doc:1"),),
        sources=("doc:1",),
        concept_ids=(),
        confidence=0.8,
        reason="simple",
    )
    draft = StudyDraft(
        target=StudyTarget.ANSWER,
        content="answer",
        citations=("doc:1",),
        used_chunk_count=1,
    )
    verification = StudyVerification(
        passed=True,
        needs_review=False,
        confidence=0.8,
        issues=(),
        source_recall=1.0,
        answer_term_recall=1.0,
    )

    decision = gate.evaluate(
        target=StudyTarget.ANSWER,
        evidence=evidence,
        draft=draft,
        verification=verification,
        policy_status="allowed",
    )

    assert decision.status == WorkflowStageStatus.PASSED
    assert decision.review_reasons == ()


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

    assert payload["workflow_id"] is None
    assert payload["status"] == "completed"
    assert payload["current_stage"] == "intake"
    assert payload["needs_review"] is False
    assert payload["stage_count"] == 1
    assert payload["stages"][0]["output_summary"] == {
        "document_count": 1,
        "target": "answer",
    }
    assert "什么是导数" not in json.dumps(payload, ensure_ascii=False)


def test_build_workflow_payload_filters_unsafe_workflow_id():
    payload = build_workflow_payload(
        workflow_id="raw private text",
        stages=[],
        needs_review=False,
    )

    assert payload["workflow_id"] is None
    assert "raw private text" not in json.dumps(payload, ensure_ascii=False)


def test_build_workflow_payload_filters_secret_like_workflow_id():
    payload = build_workflow_payload(
        workflow_id="sk-secret-token",
        stages=[],
        needs_review=False,
    )

    assert payload["workflow_id"] is None
    assert "sk-secret-token" not in json.dumps(payload, ensure_ascii=False)


def test_build_workflow_payload_filters_non_generated_workflow_id():
    payload = build_workflow_payload(
        workflow_id="workflow-123",
        stages=[],
        needs_review=False,
    )

    assert payload["workflow_id"] is None


def test_build_workflow_payload_keeps_generated_workflow_id():
    generated_id = new_workflow_id()

    payload = build_workflow_payload(
        workflow_id=generated_id,
        stages=[],
        needs_review=False,
    )

    assert payload["workflow_id"] == generated_id


def test_new_workflow_id_uses_stable_prefix_and_unique_uuid_hex():
    first = new_workflow_id()
    second = new_workflow_id()

    assert first.startswith("workflow-")
    assert second.startswith("workflow-")
    assert first != second
    assert len(first) == len("workflow-") + 32
    int(first.removeprefix("workflow-"), 16)


def test_sanitize_stage_summary_filters_non_generated_workflow_ids():
    assert sanitize_stage_summary({"workflow_id": "sk-secret-token"}) == {}
    assert sanitize_stage_summary({"workflow_id": "workflow-123"}) == {}


def test_sanitize_stage_summary_keeps_generated_workflow_id():
    generated_id = new_workflow_id()

    assert sanitize_stage_summary({"workflow_id": generated_id}) == {
        "workflow_id": generated_id,
    }


def test_stage_result_safe_dict_filters_nested_secret_like_workflow_id():
    stage = WorkflowStageResult(
        stage_name=WorkflowStageName.INTAKE,
        status=WorkflowStageStatus.PASSED,
        input_summary={"workflow_id": "sk-secret-token"},
        output_summary={},
    )

    payload = stage.to_safe_dict()
    serialized = json.dumps(payload, ensure_ascii=False)

    assert payload["input_summary"] == {}
    assert "sk-secret-token" not in serialized


def test_sanitize_stage_summary_allows_owner_and_request_ids_but_blocks_other_strings():
    summary = sanitize_stage_summary(
        {
            "workflow_id": "workflow-1",
            "request_id": "request-1",
            "owner_id": "user-123",
            "query": "什么是导数？",
        }
    )

    assert summary == {
        "request_id": "request-1",
        "owner_id": "user-123",
    }


def test_sanitize_stage_summary_filters_unsafe_opaque_ids():
    summary = sanitize_stage_summary(
        {
            "workflow_id": "workflow-123",
            "request_id": "request:abc.123",
            "owner_id": "user@example.com",
            "document_ids": ["doc-1", "文件名.pdf", "../secret"],
        }
    )

    assert summary == {
        "request_id": "request:abc.123",
        "document_ids": ["doc-1"],
    }


def test_workflow_sanitizer_keeps_safe_expert_gate_metadata_only():
    safe = sanitize_workflow_payload(
        {
            "workflow_id": "workflow-0123456789abcdef0123456789abcdef",
            "status": "partial",
            "current_stage": "expert_gate",
            "needs_review": False,
            "stages": [
                {
                    "stage": "expert_gate",
                    "status": "skipped",
                    "duration_ms": 0,
                    "input_summary": {
                        "query": "raw private query",
                        "skill_name": "concept_explanation",
                        "skill_version": "v1",
                        "policy_status": "allowed",
                    },
                    "output_summary": {
                        "expert_enabled": False,
                        "expert_branch_count": 0,
                        "expert_timeout_count": 0,
                        "expert_failure_count": 0,
                        "expert_fallback_reason": "expert_disabled",
                        "prompt": "hidden prompt",
                        "token": "sk-secret-token",
                    },
                }
            ],
        }
    )

    assert safe is not None
    stage = safe["stages"][0]
    assert stage["stage"] == "expert_gate"
    assert stage["status"] == "skipped"
    assert stage["input_summary"] == {
        "skill_name": "concept_explanation",
        "skill_version": "v1",
        "policy_status": "allowed",
    }
    assert stage["output_summary"] == {
        "expert_enabled": False,
        "expert_branch_count": 0,
        "expert_timeout_count": 0,
        "expert_failure_count": 0,
        "expert_fallback_reason": "expert_disabled",
    }
    assert "query" not in stage["input_summary"]
    assert "prompt" not in stage["output_summary"]
    assert "token" not in stage["output_summary"]
    serialized = str(safe).lower()
    assert "raw private query" not in serialized
    assert "hidden prompt" not in serialized
    assert "sk-secret-token" not in serialized
