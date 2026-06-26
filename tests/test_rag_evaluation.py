from pathlib import Path

from src.services.rag_evaluation import (
    RAGEvaluator,
    RAGEvalCase,
    RAGQualityEvaluationService,
    load_rag_eval_cases,
)


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

    assert len(cases) == 4
    assert {case.category for case in cases} == {
        "definition",
        "formula_lookup",
        "concept_relation",
        "question_generation",
    }
    assert cases[0].target == "answer"
    assert cases[0].document_fixture_ids == ["calculus-basics"]
    assert "simple_rag" in cases[0].preferred_modes
    assert all(case.expected_sources for case in cases)
    assert all(case.expected_terms for case in cases)


def test_rag_quality_evaluation_service_runs_modes_and_writes_reports(tmp_path):
    fixture_path = Path(__file__).parent / "fixtures" / "rag_eval_set.json"
    service = RAGQualityEvaluationService(report_dir=tmp_path)

    run = service.run_fixture_file(
        fixture_path,
        modes=["simple_rag", "graph_rag_lite"],
        created_by="admin-1",
    )

    assert run.id.startswith("eval-run-")
    assert run.case_count == 4
    assert set(run.modes) == {"simple_rag", "graph_rag_lite"}
    assert run.summary["simple_rag"]["case_count"] == 4
    assert run.summary["graph_rag_lite"]["case_count"] == 4
    assert run.report_json_path.exists()
    assert run.report_markdown_path.exists()
    assert "Mode Comparison" in run.report_markdown_path.read_text(encoding="utf-8")


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
