import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from src.db import Base, RAGEvaluationRunRecord, create_session_factory
from src.services.rag_evaluation import (
    RAGEvaluator,
    RAGEvalCase,
    RAGQualityEvaluationService,
    load_rag_eval_cases,
    summarize_policy_statuses,
)
from src.services.rag_router import RAGStrategyRouter
from src.storage.backend import LocalStorageBackend


def _valid_policy_fixture_case(**overrides):
    case = {
        "id": "policy-valid-001",
        "query": "what is a derivative?",
        "target": "answer",
        "category": "definition",
        "document_fixture_ids": ["doc-1"],
        "expected_sources": ["doc:source"],
        "expected_terms": ["term"],
        "expected_category": "definition",
        "expected_router_mode": "simple_rag",
        "expected_selected_mode_when_ready": "simple_rag",
        "expected_selected_mode_when_not_ready": "simple_rag",
        "requires_persisted_chunks": False,
        "max_allowed_cost": "low",
        "policy_notes": "Definition requests should stay on simple retrieval.",
    }
    case.update(overrides)
    return case


def test_rag_evaluator_scores_terms_and_sources():
    case = RAGEvalCase(
        id="def-001",
        query="什么是导数？",
        category="definition",
        expected_sources=["calculus:derivative"],
        expected_terms=["变化率"],
    )

    score = RAGEvaluator().score(
        case,
        answer="导数描述函数的变化率。",
        sources=["calculus:derivative"],
        latency_ms=10,
        token_cost=0,
    )

    assert score.answer_term_recall == 1.0
    assert score.source_recall == 1.0
    assert score.latency_ms == 10
    assert score.token_cost == 0


def test_rag_evaluator_scores_partial_term_and_source_recall():
    case = RAGEvalCase(
        id="relation-001",
        query="导数和梯度有什么关系？",
        category="concept_relation",
        expected_sources=["calculus:gradient", "calculus:derivative"],
        expected_terms=["多变量", "方向"],
    )

    score = RAGEvaluator().score(
        case,
        answer="梯度是多变量函数的一类导数表示。",
        sources=["calculus:gradient"],
        latency_ms=12,
        token_cost=3,
    )

    assert score.answer_term_recall == 0.5
    assert score.source_recall == 0.5


def test_rag_evaluator_deduplicates_expected_values():
    case = RAGEvalCase(
        id="def-001",
        query="什么是导数？",
        category="definition",
        expected_sources=[
            "calculus:derivative",
            "calculus:derivative",
            "calculus:gradient",
        ],
        expected_terms=["变化率", "变化率", "函数"],
    )

    score = RAGEvaluator().score(
        case,
        answer="导数描述变化率。",
        sources=["calculus:derivative"],
        latency_ms=10,
        token_cost=0,
    )

    assert score.answer_term_recall == 0.5
    assert score.source_recall == 0.5

    duplicate_only_case = RAGEvalCase(
        id="def-002",
        query="什么是导数？",
        category="definition",
        expected_sources=["calculus:derivative", "calculus:derivative"],
        expected_terms=["变化率", "变化率"],
    )

    duplicate_only_score = RAGEvaluator().score(
        duplicate_only_case,
        answer="导数描述变化率。",
        sources=["calculus:derivative"],
        latency_ms=10,
        token_cost=0,
    )

    assert duplicate_only_score.answer_term_recall == 1.0
    assert duplicate_only_score.source_recall == 1.0


def test_rag_evaluator_empty_expected_lists_return_full_recall():
    case = RAGEvalCase(
        id="empty-001",
        query="空期望",
        category="empty",
        expected_sources=[],
        expected_terms=[],
    )

    score = RAGEvaluator().score(
        case,
        answer="",
        sources=[],
        latency_ms=0,
        token_cost=0,
    )

    assert score.answer_term_recall == 1.0
    assert score.source_recall == 1.0


def test_rag_evaluator_handles_none_answer_and_sources():
    case = RAGEvalCase(
        id="def-001",
        query="什么是导数？",
        category="definition",
        expected_sources=["calculus:derivative"],
        expected_terms=["变化率"],
    )

    score = RAGEvaluator().score(
        case,
        answer=None,
        sources=None,
        latency_ms=10,
        token_cost=0,
    )

    assert score.answer_term_recall == 0.0
    assert score.source_recall == 0.0


def test_rag_evaluation_fixture_loads_expected_cases():
    fixture_path = Path(__file__).parent / "fixtures" / "rag_eval_set.json"

    cases = load_rag_eval_cases(fixture_path)

    assert len(cases) == 9
    assert {case.category for case in cases} == {
        "direct_lookup",
        "definition",
        "concept_relation",
        "learning_path",
        "multi_document_synthesis",
        "question_generation",
        "outline_fragment",
    }
    assert cases[0].target == "answer"
    assert cases[0].document_fixture_ids == ["calculus-basics"]
    assert "simple_rag" in cases[0].preferred_modes
    assert all(case.expected_sources for case in cases)
    assert all(case.expected_terms for case in cases)
    assert all(case.expected_category == case.category for case in cases)
    assert all(case.expected_router_mode for case in cases)
    assert all(case.expected_selected_mode_when_ready for case in cases)
    assert all(case.expected_selected_mode_when_not_ready for case in cases)
    assert all(isinstance(case.requires_persisted_chunks, bool) for case in cases)
    assert all(case.max_allowed_cost in {"low", "balanced", "high"} for case in cases)
    assert all(case.policy_notes for case in cases)
    assert (
        sum(1 for case in cases if case.category == "question_generation") >= 2
    )
    assert (
        sum(1 for case in cases if case.category == "multi_document_synthesis") >= 2
    )


def test_rag_evaluation_fixture_policy_expectations_match_router():
    fixture_path = Path(__file__).parent / "fixtures" / "rag_eval_set.json"
    cases = load_rag_eval_cases(fixture_path)
    router = RAGStrategyRouter()

    for case in cases:
        decision = router.route(case.query, target=case.target)

        assert case.expected_category == decision.category.value
        assert case.expected_router_mode == decision.mode.value


def test_rag_evaluation_fixture_rejects_private_keys(tmp_path):
    fixture_path = tmp_path / "private_fixture.json"
    fixture_path.write_text(
        json.dumps(
            [
                {
                    "id": "private-001",
                    "query": "what is private?",
                    "target": "answer",
                    "category": "definition",
                    "document_fixture_ids": ["doc-1"],
                    "expected_sources": ["doc:source"],
                    "expected_terms": ["term"],
                    "raw_content": "do not persist this",
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="private keys"):
        load_rag_eval_cases(fixture_path)


def test_rag_evaluation_fixture_rejects_missing_required_fields(tmp_path):
    fixture_path = tmp_path / "missing_required_fixture.json"
    fixture_path.write_text(
        json.dumps(
            [
                {
                    "id": "missing-001",
                    "query": "what is missing?",
                    "target": "answer",
                    "category": "definition",
                    "document_fixture_ids": ["doc-1"],
                    "expected_sources": ["doc:source"],
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing keys"):
        load_rag_eval_cases(fixture_path)


def test_rag_evaluation_fixture_requires_policy_fields(tmp_path):
    fixture_path = tmp_path / "missing_policy_fixture.json"
    fixture_path.write_text(
        json.dumps(
            [
                {
                    "id": "policy-missing-001",
                    "query": "what is missing?",
                    "target": "answer",
                    "category": "definition",
                    "document_fixture_ids": ["doc-1"],
                    "expected_sources": ["doc:source"],
                    "expected_terms": ["term"],
                    "expected_category": "definition",
                    "expected_router_mode": "simple_rag",
                    "expected_selected_mode_when_ready": "simple_rag",
                    "expected_selected_mode_when_not_ready": "simple_rag",
                    "requires_persisted_chunks": False,
                    "max_allowed_cost": "low",
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="policy_notes"):
        load_rag_eval_cases(fixture_path)


def test_rag_evaluation_fixture_rejects_non_boolean_persisted_chunk_requirement(
    tmp_path,
):
    fixture_path = tmp_path / "invalid_boolean_fixture.json"
    fixture_path.write_text(
        json.dumps(
            [
                _valid_policy_fixture_case(
                    requires_persisted_chunks="false",
                )
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="requires_persisted_chunks"):
        load_rag_eval_cases(fixture_path)


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("expected_router_mode", "raw query from reviewer"),
        ("expected_selected_mode_when_ready", "unsafe-mode"),
        ("expected_selected_mode_when_not_ready", "unsafe-mode"),
        ("max_allowed_cost", "password"),
        ("expected_category", "source_snippet"),
        ("category", "raw query: 什么是导数？"),
    ],
)
def test_rag_evaluation_fixture_rejects_invalid_policy_enum_values(
    tmp_path,
    field_name,
    invalid_value,
):
    fixture_path = tmp_path / f"invalid_{field_name}.json"
    fixture_path.write_text(
        json.dumps([_valid_policy_fixture_case(**{field_name: invalid_value})]),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=field_name):
        load_rag_eval_cases(fixture_path)


def test_summarize_policy_statuses_counts_status_and_category_without_private_text():
    rows = [
        {
            "case_id": "def-001",
            "category": "definition",
            "policy_status": "matched",
            "selected_mode": "simple_rag",
            "query": "什么是导数？",
            "answer": "导数描述函数的变化率。",
            "source_snippet": "private source",
            "token": "secret-token",
        },
        {
            "case_id": "synthesis-001",
            "category": "multi_document_synthesis",
            "policy_status": "fallback",
            "selected_mode": "agentic_rag",
            "chunk_content": "private chunk",
            "prompt": "hidden prompt",
        },
        {
            "case_id": "synthesis-002",
            "expected_category": "multi_document_synthesis",
            "status": "matched",
            "selected_mode": "agentic_rag",
            "hidden_reasoning": "do not expose",
        },
    ]

    summary = summarize_policy_statuses(rows)

    assert summary == {
        "case_count": 3,
        "status_counts": {"fallback": 1, "matched": 2},
        "category_counts": {"definition": 1, "multi_document_synthesis": 2},
        "selected_mode_counts": {"agentic_rag": 2, "simple_rag": 1},
    }
    serialized = json.dumps(summary, ensure_ascii=False)
    for private_value in [
        "什么是导数",
        "导数描述",
        "private source",
        "secret-token",
        "private chunk",
        "hidden prompt",
        "do not expose",
    ]:
        assert private_value not in serialized


def test_summarize_policy_statuses_buckets_unknown_or_unsafe_values():
    rows = [
        {
            "policy_status": "expected_ready_mode",
            "category": "definition",
            "selected_mode": "simple_rag",
        },
        {
            "policy_status": "raw query: 什么是导数？",
            "category": "source_snippet",
            "selected_mode": "secret-token",
        },
        {
            "status": "fallback",
            "expected_category": "multi_document_synthesis",
            "mode": "agentic_rag",
        },
    ]

    summary = summarize_policy_statuses(rows)

    assert summary == {
        "case_count": 3,
        "status_counts": {
            "expected_ready_mode": 1,
            "fallback": 1,
            "unknown": 1,
        },
        "category_counts": {
            "definition": 1,
            "multi_document_synthesis": 1,
            "unknown": 1,
        },
        "selected_mode_counts": {
            "agentic_rag": 1,
            "simple_rag": 1,
            "unknown": 1,
        },
    }
    serialized = json.dumps(summary, ensure_ascii=False)
    assert "什么是导数" not in serialized
    assert "source_snippet" not in serialized
    assert "secret-token" not in serialized


def test_rag_quality_evaluation_service_runs_modes_and_writes_reports(tmp_path):
    fixture_path = Path(__file__).parent / "fixtures" / "rag_eval_set.json"
    service = RAGQualityEvaluationService(report_dir=tmp_path)

    run = service.run_fixture_file(
        fixture_path,
        modes=["simple_rag", "graph_rag_lite"],
        created_by="admin-1",
    )

    assert run.id.startswith("eval-run-")
    assert run.case_count == 9
    assert set(run.modes) == {"simple_rag", "graph_rag_lite"}
    assert run.summary["simple_rag"]["case_count"] == 9
    assert run.summary["graph_rag_lite"]["case_count"] == 9
    assert len(run.scores) == run.case_count * len(run.modes)

    expected_score_keys = {
        "case_id",
        "mode",
        "category",
        "source_recall",
        "answer_term_recall",
        "answer_coverage",
        "latency_ms",
        "estimated_cost",
        "needs_review",
        "fallback_reason",
        "policy_status",
    }
    assert all(isinstance(score, dict) for score in run.scores)
    assert all(expected_score_keys.issubset(score) for score in run.scores)

    assert run.report_json_path.exists()
    payload = json.loads(run.report_json_path.read_text(encoding="utf-8"))
    assert len(payload["scores"]) == run.case_count * len(run.modes)
    assert all(expected_score_keys.issubset(score) for score in payload["scores"])
    assert payload["policy_summary"]["category_counts"]["question_generation"] == 4
    assert payload["policy_summary"]["category_counts"]["multi_document_synthesis"] == 4
    serialized = json.dumps(payload["policy_summary"], ensure_ascii=False)
    assert "什么是导数" not in serialized
    assert "导数描述" not in serialized
    assert run.report_markdown_path.exists()
    markdown = run.report_markdown_path.read_text(encoding="utf-8")
    assert "Mode Comparison" in markdown
    assert "Policy Summary" in markdown


def test_rag_quality_evaluation_service_stores_reports_in_storage_backend(tmp_path):
    fixture_path = Path(__file__).parent / "fixtures" / "rag_eval_set.json"
    backend = LocalStorageBackend(tmp_path / "objects")
    service = RAGQualityEvaluationService(
        report_dir=tmp_path / "reports",
        storage=backend,
    )

    run = service.run_fixture_file(
        fixture_path,
        modes=["simple_rag", "graph_rag_lite"],
        created_by="admin-1",
    )

    assert run.report_markdown_uri.startswith("local://")
    markdown = backend.read_bytes(run.report_markdown_uri).decode("utf-8")
    assert "Mode Comparison" in markdown
    assert run.report_json_uri.startswith("local://")
    payload = json.loads(backend.read_bytes(run.report_json_uri).decode("utf-8"))
    assert payload["id"] == run.id
    assert not (tmp_path / "reports").exists()


def test_rag_quality_evaluation_service_persists_runs_and_case_scores(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'eval.db'}")
    Base.metadata.create_all(engine)
    Session = create_session_factory(engine)
    fixture_path = Path(__file__).parent / "fixtures" / "rag_eval_set.json"
    service = RAGQualityEvaluationService(
        report_dir=tmp_path / "reports",
        session_factory=Session,
    )

    run = service.run_fixture_file(
        fixture_path,
        modes=["simple_rag", "graph_rag_lite"],
        created_by="admin-1",
    )

    with Session() as session:
        record = session.get(RAGEvaluationRunRecord, run.id)
        assert record is not None
        assert record.created_by == "admin-1"
        assert record.status == "completed"
        assert record.case_count == 9
        assert len(record.scores) == 18
        assert record.report_uri.endswith(".md")


def test_rag_quality_evaluation_reports_readiness_gates(tmp_path):
    fixture_path = Path(__file__).parent / "fixtures" / "rag_eval_set.json"
    service = RAGQualityEvaluationService(report_dir=tmp_path)

    run = service.run_fixture_file(
        fixture_path,
        modes=["simple_rag", "agentic_rag"],
        created_by="admin-1",
    )

    readiness = run.readiness["agentic_rag"]
    assert readiness["overall"] in {"candidate", "hold", "insufficient_data"}
    assert "question_generation" in readiness["by_category"]
