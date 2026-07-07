from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import select

from src.db import StudyAgentTraceRecord
from src.services.study_agent_experts import safe_expert_metadata
from src.services.study_agent_trace import safe_skill_metadata
from src.services.study_agent_workflow import sanitize_workflow_payload


class StudyAgentSkillPerformanceService:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    def summary(
        self,
        *,
        owner_id: str,
        skill_name: str | None = None,
        skill_version: str | None = None,
    ) -> dict[str, Any]:
        with self.session_factory() as session:
            records = list(
                session.scalars(
                    select(StudyAgentTraceRecord).where(
                        StudyAgentTraceRecord.owner_id == owner_id
                    )
                )
            )

        buckets: dict[tuple[str, str], list[StudyAgentTraceRecord]] = defaultdict(list)
        for record in records:
            skill = safe_skill_metadata((record.trace_metadata or {}).get("skill"))
            if skill is None:
                continue
            name = skill.get("skill_name")
            version = skill.get("skill_version")
            if not isinstance(name, str) or not isinstance(version, str):
                continue
            if skill_name is not None and name != skill_name:
                continue
            if skill_version is not None and version != skill_version:
                continue
            buckets[(name, version)].append(record)

        return {
            "skills": [
                _summarize_bucket(name, version, bucket)
                for (name, version), bucket in sorted(buckets.items())
            ]
        }


def _summarize_bucket(
    skill_name: str,
    skill_version: str,
    records: list[StudyAgentTraceRecord],
) -> dict[str, Any]:
    run_count = len(records)
    needs_review_count = sum(1 for record in records if record.needs_review)
    fallback_count = sum(1 for record in records if record.fallback_reason)
    expert_run_count = 0
    expert_timeout_count = 0
    review_reasons: Counter[str] = Counter()
    for record in records:
        expert = safe_expert_metadata((record.trace_metadata or {}).get("expert")) or {}
        if expert.get("enabled") is True:
            expert_run_count += 1
        expert_timeout_count += int(expert.get("timeout_count") or 0)
        workflow = sanitize_workflow_payload((record.trace_metadata or {}).get("workflow"))
        if workflow is not None:
            for stage in workflow.get("stages", []):
                reason = stage.get("review_reason") or stage.get(
                    "output_summary", {}
                ).get("review_reason")
                if isinstance(reason, str):
                    review_reasons[reason] += 1

    return {
        "skill_name": skill_name,
        "skill_version": skill_version,
        "run_count": run_count,
        "needs_review_count": needs_review_count,
        "review_rate": _rate(needs_review_count, run_count),
        "fallback_count": fallback_count,
        "fallback_rate": _rate(fallback_count, run_count),
        "expert_run_count": expert_run_count,
        "expert_timeout_count": expert_timeout_count,
        "average_confidence": _avg(record.confidence for record in records),
        "average_source_recall": _avg(record.source_recall for record in records),
        "average_answer_term_recall": _avg(
            record.answer_term_recall for record in records
        ),
        "review_reason_counts": dict(sorted(review_reasons.items())),
    }


def _rate(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(count / total, 6)


def _avg(values) -> float:
    items = [float(value) for value in values if value is not None]
    if not items:
        return 0.0
    return round(sum(items) / len(items), 6)
