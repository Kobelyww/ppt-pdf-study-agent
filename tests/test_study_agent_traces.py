from __future__ import annotations

import json

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
