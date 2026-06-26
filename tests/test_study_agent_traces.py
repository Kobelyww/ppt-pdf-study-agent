from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine, select

from src.db import Base, StudyAgentTraceRecord, create_session_factory
from src.services.rag_router import RetrievalMode
from src.services.rag_service import Chunk
from src.services.study_agent import (
    EvidenceBundle,
    StudyAgentResult,
    StudyBudget,
    StudyDraft,
    StudyPlan,
    StudyRequest,
    StudyTarget,
    StudyVerification,
)
from src.services.study_agent_trace import StudyAgentTraceService
from src.services.study_agent_trace import safe_policy_metadata


def _session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


def _study_result() -> StudyAgentResult:
    chunk = Chunk(
        content="导数是函数在某一点附近变化快慢的局部描述。",
        source="document:doc-1:chunk:0",
        metadata={"snippet": "函数变化率原文片段", "page": 1},
        score=0.91,
    )
    request = StudyRequest(
        query="什么是导数？",
        target=StudyTarget.ANSWER,
        document_ids=("doc-1",),
        preferred_mode=RetrievalMode.SIMPLE,
        budget=StudyBudget.BALANCED,
        expected_terms=("变化率", "函数"),
        authenticated_user_id="owner-1",
        request_id="req-1",
    )
    return StudyAgentResult(
        request=request,
        plan=StudyPlan(
            mode=RetrievalMode.SIMPLE,
            reason="definition or direct lookup query",
            steps=("retrieve chunks", "draft grounded answer"),
            estimated_cost="low",
            fallbacks=(RetrievalMode.GRAPH,),
        ),
        evidence=EvidenceBundle(
            mode=RetrievalMode.SIMPLE,
            chunks=(chunk,),
            sources=("document:doc-1:chunk:0",),
            concept_ids=("derivative",),
            confidence=0.82,
            reason="selected simple RAG for direct lookup",
        ),
        draft=StudyDraft(
            target=StudyTarget.ANSWER,
            content="导数描述函数变化率。",
            citations=("document:doc-1:chunk:0",),
            used_chunk_count=1,
            metadata={"source_snippets": ["导数描述函数变化率。"]},
        ),
        verification=StudyVerification(
            passed=True,
            needs_review=False,
            confidence=0.8,
            issues=(),
            source_recall=1.0,
            answer_term_recall=1.0,
        ),
        audit_metadata={
            "chunk_source": "document:doc-1:chunk:0",
            "fallback_reason": "primary index available",
            "authorization": "Bearer secret-token",
        },
    )


def test_record_success_persists_safe_study_agent_trace():
    SessionFactory = _session_factory()
    service = StudyAgentTraceService(SessionFactory)
    result = _study_result()

    payload = service.record_success(
        owner_id="owner-1",
        request_id="req-1",
        result=result,
        latency_ms=42.5,
        index_statuses={
            "doc-1": {
                "status": "ready",
                "fallback_reason": "not used",
                "chunk_count": 7,
                "chunk_content": "导数是函数变化率。",
                "password": "secret",
            },
            "doc-2": {
                "status": "missing",
                "fallback_reason": "not indexed",
                "chunk_count": "0",
                "token": "abc",
            },
        },
    )

    assert set(payload) == {
        "trace_id",
        "request_id",
        "selected_mode",
        "route_reason",
        "chunk_source",
        "fallback_reason",
        "document_count",
        "source_count",
        "used_chunk_count",
        "confidence",
        "source_recall",
        "answer_term_recall",
        "needs_review",
        "latency_ms",
    }
    assert payload["trace_id"]
    assert payload["request_id"] == "req-1"
    assert payload["selected_mode"] == "simple_rag"
    assert payload["route_reason"] == "definition or direct lookup query"
    assert payload["chunk_source"] == "document:doc-1:chunk:0"
    assert payload["fallback_reason"] == "primary index available"
    assert payload["document_count"] == 1
    assert payload["source_count"] == 1
    assert payload["used_chunk_count"] == 1
    assert payload["confidence"] == 0.8
    assert payload["source_recall"] == 1.0
    assert payload["answer_term_recall"] == 1.0
    assert payload["latency_ms"] == 42.5
    assert "query_hash" not in payload

    with SessionFactory() as session:
        record = session.scalar(select(StudyAgentTraceRecord))

    assert record is not None
    assert record.query_hash.startswith("sha256:")
    assert record.query_hash != result.request.query
    assert record.trace_metadata == {
        "expected_term_count": 2,
        "index_statuses": {
            "doc-1": {
                "status": "ready",
                "fallback_reason": "not used",
                "chunk_count": 7,
            },
            "doc-2": {
                "status": "missing",
                "fallback_reason": "not indexed",
                "chunk_count": 0,
            },
        },
    }

    serialized_record = json.dumps(
        {
            "id": record.id,
            "owner_id": record.owner_id,
            "request_id": record.request_id,
            "query_hash": record.query_hash,
            "target": record.target,
            "document_ids": record.document_ids,
            "selected_mode": record.selected_mode,
            "route_reason": record.route_reason,
            "estimated_cost": record.estimated_cost,
            "fallback_chain": record.fallback_chain,
            "chunk_source": record.chunk_source,
            "fallback_reason": record.fallback_reason,
            "source_count": record.source_count,
            "used_chunk_count": record.used_chunk_count,
            "confidence": record.confidence,
            "source_recall": record.source_recall,
            "answer_term_recall": record.answer_term_recall,
            "needs_review": record.needs_review,
            "latency_ms": record.latency_ms,
            "trace_metadata": record.trace_metadata,
        },
        ensure_ascii=False,
        sort_keys=True,
    )

    forbidden_values = [
        "什么是导数？",
        "导数描述函数变化率。",
        "变化率",
        "函数",
        "导数是函数在某一点附近变化快慢的局部描述。",
        "函数变化率原文片段",
        "导数是函数变化率。",
        "Bearer secret-token",
        "secret-token",
        "secret",
        "abc",
    ]
    for value in forbidden_values:
        assert value not in serialized_record

    forbidden_keys = ["authorization", "token", "password", "secret", "chunk_content", "snippet"]
    for key in forbidden_keys:
        assert key not in serialized_record.lower()


def test_get_trace_is_scoped_to_owner_and_can_include_query_hash():
    SessionFactory = _session_factory()
    service = StudyAgentTraceService(SessionFactory)

    created = service.record_success(
        owner_id="owner-1",
        request_id="req-1",
        result=_study_result(),
        latency_ms=42.5,
        index_statuses={},
    )

    owner_payload = service.get_trace("owner-1", created["trace_id"])
    other_owner_payload = service.get_trace("owner-2", created["trace_id"])

    assert owner_payload is not None
    assert set(owner_payload) == {
        "trace_id",
        "request_id",
        "selected_mode",
        "route_reason",
        "chunk_source",
        "fallback_reason",
        "document_count",
        "source_count",
        "used_chunk_count",
        "confidence",
        "source_recall",
        "answer_term_recall",
        "needs_review",
        "latency_ms",
        "query_hash",
    }
    assert owner_payload["trace_id"] == created["trace_id"]
    assert owner_payload["request_id"] == "req-1"
    assert owner_payload["selected_mode"] == "simple_rag"
    assert owner_payload["document_count"] == 1
    assert owner_payload["query_hash"].startswith("sha256:")
    assert "什么是导数？" not in json.dumps(owner_payload, ensure_ascii=False)
    assert other_owner_payload is None


def test_trace_serializes_safe_policy_subset():
    SessionFactory = _session_factory()
    service = StudyAgentTraceService(SessionFactory)
    result = _study_result()
    result.audit_metadata["policy"] = {
        "selected_mode": "simple_rag",
        "router_mode": "graph_rag_lite",
        "effective_mode": "graph_rag_lite",
        "category": "concept_relation",
        "status": "blocked_by_flag",
        "reason": "advanced routing is disabled",
        "fallback_chain": ["simple_rag"],
        "blocked_reason": "advanced routing is disabled",
        "estimated_cost": "medium",
        "experiment_enabled": False,
        "policy_version": "rag-policy-v1",
        "query": "什么是导数？",
        "content": "导数描述函数变化率。",
        "snippet": "函数变化率原文片段",
        "token": "abc",
        "password": "secret",
    }

    payload = service.record_success(
        owner_id="owner-1",
        request_id="req-policy",
        result=result,
        latency_ms=15.0,
        index_statuses={},
    )
    trace = service.get_trace("owner-1", payload["trace_id"])

    expected_policy = {
        "selected_mode": "simple_rag",
        "router_mode": "graph_rag_lite",
        "effective_mode": "graph_rag_lite",
        "category": "concept_relation",
        "status": "blocked_by_flag",
        "reason": "advanced routing is disabled",
        "fallback_chain": ["simple_rag"],
        "blocked_reason": "advanced routing is disabled",
        "estimated_cost": "medium",
        "experiment_enabled": False,
        "policy_version": "rag-policy-v1",
    }
    assert payload["policy"] == expected_policy
    assert trace is not None
    assert trace["policy"] == expected_policy

    with SessionFactory() as session:
        record = session.scalar(select(StudyAgentTraceRecord))
    serialized_record = json.dumps(
        {
            "trace_metadata": record.trace_metadata,
            "selected_mode": record.selected_mode,
            "route_reason": record.route_reason,
        },
        ensure_ascii=False,
        sort_keys=True,
    )

    forbidden_values = [
        "什么是导数？",
        "导数描述函数变化率。",
        "函数变化率原文片段",
        "abc",
        "secret",
    ]
    for value in forbidden_values:
        assert value not in serialized_record

    for key in ['"query"', '"content"', '"snippet"', '"token"', '"password"', '"secret"']:
        assert key not in serialized_record.lower()


def test_trace_policy_sanitizer_drops_sensitive_values_inside_allowed_keys():
    SessionFactory = _session_factory()
    service = StudyAgentTraceService(SessionFactory)
    result = _study_result()
    result.audit_metadata["policy"] = {
        "selected_mode": "simple_rag",
        "router_mode": "graph_rag_lite",
        "effective_mode": "graph_rag_lite",
        "category": "concept_relation",
        "status": "blocked_by_flag",
        "reason": "用户问：什么是导数？",
        "fallback_chain": [
            "graph_rag_lite",
            "simple_rag",
            "raw chunk content: 导数描述函数变化率。",
        ],
        "readiness_status": "hold because prompt leaked",
        "blocked_reason": "secret-token abc",
        "estimated_cost": "medium",
        "experiment_enabled": False,
        "policy_version": "rag-policy-v1",
    }

    payload = service.record_success(
        owner_id="owner-1",
        request_id="req-policy-sensitive",
        result=result,
        latency_ms=16.0,
        index_statuses={},
    )
    trace = service.get_trace("owner-1", payload["trace_id"])

    expected_policy = {
        "selected_mode": "simple_rag",
        "router_mode": "graph_rag_lite",
        "effective_mode": "graph_rag_lite",
        "category": "concept_relation",
        "status": "blocked_by_flag",
        "fallback_chain": ["graph_rag_lite", "simple_rag"],
        "estimated_cost": "medium",
        "experiment_enabled": False,
        "policy_version": "rag-policy-v1",
    }
    assert payload["policy"] == expected_policy
    assert trace is not None
    assert trace["policy"] == expected_policy

    with SessionFactory() as session:
        record = session.scalar(select(StudyAgentTraceRecord))
    serialized_record = json.dumps(record.trace_metadata, ensure_ascii=False, sort_keys=True)

    for value in [
        "什么是导数？",
        "导数描述函数变化率。",
        "raw chunk content",
        "prompt leaked",
        "secret-token",
        "abc",
    ]:
        assert value not in serialized_record


@pytest.mark.parametrize(
    "reason",
    [
        "graph_rag_lite is allowed by route policy",
        "readiness snapshot is unavailable",
        "agentic_rag requires high budget",
        "agentic_rag is not candidate for question_generation",
        "learning_path is not enabled",
    ],
)
def test_policy_sanitizer_keeps_known_safe_policy_reasons(reason: str):
    policy = safe_policy_metadata(
        {
            "selected_mode": "simple_rag",
            "router_mode": "graph_rag_lite",
            "category": "learning_path",
            "status": "blocked_by_readiness",
            "reason": reason,
            "blocked_reason": reason,
            "policy_version": "rag-policy-v1",
        }
    )

    assert policy["reason"] == reason
    assert policy["blocked_reason"] == reason
