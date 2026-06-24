import pytest

from src.services.rag_router import RetrievalMode
from src.services.study_agent import (
    StudyBudget,
    StudyRequest,
    StudyTarget,
    normalize_study_request,
)


def test_normalizes_minimal_study_request_defaults():
    request = normalize_study_request({"query": "  什么是导数？  "})

    assert request == StudyRequest(
        query="什么是导数？",
        target=StudyTarget.ANSWER,
        document_ids=(),
        preferred_mode=None,
        budget=StudyBudget.BALANCED,
        expected_terms=(),
    )


def test_normalizes_optional_fields_and_deduplicates_document_ids():
    request = normalize_study_request(
        {
            "query": "基于第2章出一道题",
            "target": "question",
            "document_ids": ["doc-1", "doc-1", "doc-2", ""],
            "preferred_mode": "agentic_rag",
            "budget": "high",
            "expected_terms": ["特征值", "特征值", "矩阵"],
        }
    )

    assert request.target == StudyTarget.QUESTION
    assert request.document_ids == ("doc-1", "doc-2")
    assert request.preferred_mode == RetrievalMode.AGENTIC
    assert request.budget == StudyBudget.HIGH
    assert request.expected_terms == ("特征值", "矩阵")


def test_rejects_empty_query():
    with pytest.raises(ValueError, match="query must not be empty"):
        normalize_study_request({"query": "   "})


def test_rejects_unknown_target_budget_and_mode():
    with pytest.raises(ValueError, match="unsupported study target"):
        normalize_study_request({"query": "x", "target": "essay"})

    with pytest.raises(ValueError, match="unsupported study budget"):
        normalize_study_request({"query": "x", "budget": "expensive"})

    with pytest.raises(ValueError, match="unsupported retrieval mode"):
        normalize_study_request({"query": "x", "preferred_mode": "hybrid"})
