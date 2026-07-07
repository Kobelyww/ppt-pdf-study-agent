from __future__ import annotations

from sqlalchemy import create_engine

from src.db import Base, StudyAgentTraceRecord, create_session_factory
from src.services.study_agent_skill_performance import StudyAgentSkillPerformanceService


def _session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


def _trace(
    *,
    trace_id: str,
    owner_id: str,
    skill_name: str = "concept_explanation",
    skill_version: str = "v1",
    needs_review: bool = False,
    fallback_reason: str | None = None,
    confidence: float = 0.8,
    source_recall: float = 1.0,
    answer_term_recall: float = 1.0,
    expert=None,
    review_reason: str | None = None,
):
    workflow_stage = {
        "stage": "review_gate",
        "status": "needs_review" if needs_review else "passed",
        "duration_ms": 0,
        "input_summary": {},
        "output_summary": {
            "needs_review": needs_review,
            "review_reason": review_reason,
        },
        "error_code": None,
        "review_reason": review_reason,
    }
    return StudyAgentTraceRecord(
        id=trace_id,
        owner_id=owner_id,
        request_id=f"req-{trace_id}",
        query_hash=f"sha256:{trace_id}",
        target="answer",
        document_ids=["doc-1"],
        selected_mode="simple_rag",
        route_reason="safe reason",
        estimated_cost="low",
        fallback_chain=[],
        chunk_source="persisted",
        fallback_reason=fallback_reason,
        source_count=1,
        used_chunk_count=1,
        confidence=confidence,
        source_recall=source_recall,
        answer_term_recall=answer_term_recall,
        needs_review=needs_review,
        latency_ms=10,
        trace_metadata={
            "skill": {
                "skill_name": skill_name,
                "skill_version": skill_version,
            },
            "workflow": {
                "workflow_id": "workflow-0123456789abcdef0123456789abcdef",
                "status": "needs_review" if needs_review else "completed",
                "current_stage": "trace",
                "needs_review": needs_review,
                "stage_count": 1,
                "stages": [workflow_stage],
            },
            "expert": expert
            or {
                "enabled": False,
                "branch_count": 0,
                "timeout_count": 0,
                "failure_count": 0,
            },
        },
    )


def test_skill_performance_summary_is_owner_scoped_and_aggregate_only():
    Session = _session_factory()
    with Session() as session:
        session.add_all(
            [
                _trace(
                    trace_id="trace-1",
                    owner_id="owner-1",
                    needs_review=False,
                    confidence=0.8,
                ),
                _trace(
                    trace_id="trace-2",
                    owner_id="owner-1",
                    needs_review=True,
                    fallback_reason="persisted_chunks_missing",
                    confidence=0.4,
                    source_recall=0.5,
                    answer_term_recall=0.25,
                    expert={
                        "enabled": True,
                        "branch_count": 2,
                        "timeout_count": 1,
                        "failure_count": 0,
                        "fallback_reason": "branch_timeout",
                    },
                    review_reason="low_confidence",
                ),
                _trace(
                    trace_id="trace-3",
                    owner_id="owner-2",
                    skill_name="practice_question",
                    needs_review=True,
                ),
            ]
        )
        session.commit()

    summary = StudyAgentSkillPerformanceService(Session).summary(owner_id="owner-1")

    assert summary == {
        "skills": [
            {
                "skill_name": "concept_explanation",
                "skill_version": "v1",
                "run_count": 2,
                "needs_review_count": 1,
                "review_rate": 0.5,
                "fallback_count": 1,
                "fallback_rate": 0.5,
                "expert_run_count": 1,
                "expert_timeout_count": 1,
                "average_confidence": 0.6,
                "average_source_recall": 0.75,
                "average_answer_term_recall": 0.625,
                "review_reason_counts": {"low_confidence": 1},
            }
        ]
    }
    serialized = str(summary).lower()
    assert "owner-2" not in serialized
    assert "trace-3" not in serialized


def test_skill_performance_summary_can_filter_skill_version():
    Session = _session_factory()
    with Session() as session:
        session.add_all(
            [
                _trace(
                    trace_id="trace-1",
                    owner_id="owner-1",
                    skill_name="concept_explanation",
                    skill_version="v1",
                ),
                _trace(
                    trace_id="trace-2",
                    owner_id="owner-1",
                    skill_name="practice_question",
                    skill_version="v1",
                ),
            ]
        )
        session.commit()

    summary = StudyAgentSkillPerformanceService(Session).summary(
        owner_id="owner-1",
        skill_name="practice_question",
        skill_version="v1",
    )

    assert [item["skill_name"] for item in summary["skills"]] == ["practice_question"]


def test_skill_performance_summary_drops_unknown_review_reason_counts():
    Session = _session_factory()
    with Session() as session:
        session.add_all(
            [
                _trace(
                    trace_id="trace-safe",
                    owner_id="owner-1",
                    needs_review=True,
                    review_reason="low_confidence",
                ),
                _trace(
                    trace_id="trace-unsafe",
                    owner_id="owner-1",
                    needs_review=True,
                    review_reason="custom_lowercase_reason",
                ),
            ]
        )
        session.commit()

    summary = StudyAgentSkillPerformanceService(Session).summary(owner_id="owner-1")

    counts = summary["skills"][0]["review_reason_counts"]
    assert counts == {"low_confidence": 1}
    assert "unknown" not in counts
