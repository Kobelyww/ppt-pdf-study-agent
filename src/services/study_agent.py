from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.services.rag_router import RetrievalMode
from src.services.rag_service import Chunk


class StudyTarget(str, Enum):
    ANSWER = "answer"
    QUESTION = "question"
    OUTLINE_FRAGMENT = "outline_fragment"


class StudyBudget(str, Enum):
    LOW = "low"
    BALANCED = "balanced"
    HIGH = "high"


@dataclass(frozen=True)
class StudyRequest:
    query: str
    target: StudyTarget = StudyTarget.ANSWER
    document_ids: tuple[str, ...] = ()
    preferred_mode: RetrievalMode | None = None
    budget: StudyBudget = StudyBudget.BALANCED
    expected_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class StudyPlan:
    mode: RetrievalMode
    reason: str
    steps: tuple[str, ...]
    estimated_cost: str
    fallbacks: tuple[RetrievalMode, ...] = ()


@dataclass(frozen=True)
class EvidenceBundle:
    mode: RetrievalMode
    chunks: tuple[Chunk, ...]
    sources: tuple[str, ...]
    concept_ids: tuple[str, ...]
    confidence: float
    reason: str
    fallback_reason: str | None = None


@dataclass(frozen=True)
class StudyDraft:
    target: StudyTarget
    content: str
    citations: tuple[str, ...]
    used_chunk_count: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StudyVerification:
    passed: bool
    needs_review: bool
    confidence: float
    issues: tuple[str, ...]
    source_recall: float
    answer_term_recall: float


@dataclass(frozen=True)
class StudyAgentResult:
    request: StudyRequest
    plan: StudyPlan
    evidence: EvidenceBundle
    draft: StudyDraft
    verification: StudyVerification
    audit_metadata: dict[str, Any]


def normalize_study_request(payload: dict[str, Any]) -> StudyRequest:
    query = str(payload.get("query", "")).strip()
    if not query:
        raise ValueError("query must not be empty")

    target = _enum_value(
        StudyTarget,
        payload.get("target", StudyTarget.ANSWER.value),
        "unsupported study target",
    )
    budget = _enum_value(
        StudyBudget,
        payload.get("budget", StudyBudget.BALANCED.value),
        "unsupported study budget",
    )
    preferred_mode = payload.get("preferred_mode")
    mode = None
    if preferred_mode not in {None, ""}:
        mode = _enum_value(RetrievalMode, preferred_mode, "unsupported retrieval mode")

    return StudyRequest(
        query=query,
        target=target,
        document_ids=_dedupe_nonempty(payload.get("document_ids") or []),
        preferred_mode=mode,
        budget=budget,
        expected_terms=_dedupe_nonempty(payload.get("expected_terms") or []),
    )


def _enum_value(enum_type, raw_value: Any, error_message: str):
    try:
        return enum_type(str(raw_value))
    except ValueError as exc:
        raise ValueError(error_message) from exc


def _dedupe_nonempty(values: list[Any] | tuple[Any, ...]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for value in values:
        normalized = str(value).strip()
        if normalized:
            seen.setdefault(normalized, None)
    return tuple(seen)
