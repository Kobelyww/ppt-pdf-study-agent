import json
from pathlib import Path

from src.services.rag_evaluation import RAGEvaluator, RAGEvalCase


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

    cases = json.loads(fixture_path.read_text(encoding="utf-8"))
    required_keys = {
        "id",
        "query",
        "category",
        "expected_sources",
        "expected_terms",
    }

    assert len(cases) == 4
    assert all(set(case) == required_keys for case in cases)
    assert {case["category"] for case in cases} == {
        "definition",
        "formula_lookup",
        "concept_relation",
        "question_generation",
    }
    assert all(case["id"] for case in cases)
    assert all(case["query"] for case in cases)
    assert all(case["expected_sources"] for case in cases)
    assert all(case["expected_terms"] for case in cases)
