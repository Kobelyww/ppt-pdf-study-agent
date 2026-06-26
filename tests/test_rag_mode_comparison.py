from src.services.rag_evaluation import RAGEvaluationReport, evaluate_route_readiness


def test_rag_evaluation_report_tracks_modes():
    report = RAGEvaluationReport()
    report.add_score(
        mode="simple_rag",
        category="definition",
        source_recall=1.0,
        answer_term_recall=1.0,
        latency_ms=100,
        token_cost=10,
    )
    report.add_score(
        mode="simple_rag",
        category="formula_lookup",
        source_recall=0.5,
        answer_term_recall=0.75,
        latency_ms=300,
        token_cost=30,
    )
    report.add_score(
        mode="graph_rag_lite",
        category="concept_relation",
        source_recall=1.0,
        answer_term_recall=0.8,
        latency_ms=500,
        token_cost=50,
    )

    summary = report.summary()

    assert "simple_rag" in summary
    assert "graph_rag_lite" in summary
    assert summary["simple_rag"] == {
        "average_source_recall": 0.75,
        "average_answer_term_recall": 0.875,
        "average_answer_coverage": 1.0,
        "average_latency_ms": 200,
        "median_latency_ms": 200.0,
        "average_token_cost": 20,
        "estimated_cost_recorded_rate": 1.0,
        "case_count": 2,
        "needs_review_rate": 0.0,
        "fallback_rate": 0.0,
        "categories": ["definition", "formula_lookup"],
        "by_category": {
            "definition": {
                "average_source_recall": 1.0,
                "average_answer_term_recall": 1.0,
                "average_answer_coverage": 1.0,
                "average_latency_ms": 100,
                "median_latency_ms": 100.0,
                "average_token_cost": 10,
                "estimated_cost_recorded_rate": 1.0,
                "case_count": 1,
                "needs_review_rate": 0.0,
                "fallback_rate": 0.0,
            },
            "formula_lookup": {
                "average_source_recall": 0.5,
                "average_answer_term_recall": 0.75,
                "average_answer_coverage": 1.0,
                "average_latency_ms": 300,
                "median_latency_ms": 300.0,
                "average_token_cost": 30,
                "estimated_cost_recorded_rate": 1.0,
                "case_count": 1,
                "needs_review_rate": 0.0,
                "fallback_rate": 0.0,
            },
        },
    }
    assert summary["graph_rag_lite"] == {
        "average_source_recall": 1.0,
        "average_answer_term_recall": 0.8,
        "average_answer_coverage": 1.0,
        "average_latency_ms": 500,
        "median_latency_ms": 500.0,
        "average_token_cost": 50,
        "estimated_cost_recorded_rate": 1.0,
        "case_count": 1,
        "needs_review_rate": 0.0,
        "fallback_rate": 0.0,
        "categories": ["concept_relation"],
        "by_category": {
            "concept_relation": {
                "average_source_recall": 1.0,
                "average_answer_term_recall": 0.8,
                "average_answer_coverage": 1.0,
                "average_latency_ms": 500,
                "median_latency_ms": 500.0,
                "average_token_cost": 50,
                "estimated_cost_recorded_rate": 1.0,
                "case_count": 1,
                "needs_review_rate": 0.0,
                "fallback_rate": 0.0,
            }
        },
    }


def test_route_readiness_marks_candidate_hold_and_insufficient_data():
    summary = {
        "simple_rag": {
            "average_source_recall": 0.8,
            "average_answer_term_recall": 0.8,
            "average_latency_ms": 100,
            "average_token_cost": 10,
            "needs_review_rate": 0.1,
            "fallback_rate": 0.0,
            "categories": ["definition"],
            "by_category": {
                "definition": {
                    "average_source_recall": 0.8,
                    "average_answer_term_recall": 0.8,
                    "average_answer_coverage": 0.8,
                    "average_latency_ms": 100,
                    "median_latency_ms": 100,
                    "needs_review_rate": 0.1,
                    "fallback_rate": 0.0,
                }
            },
        },
        "graph_rag_lite": {
            "average_source_recall": 0.78,
            "average_answer_term_recall": 0.78,
            "average_latency_ms": 150,
            "average_token_cost": 20,
            "needs_review_rate": 0.15,
            "fallback_rate": 0.0,
            "categories": ["definition"],
            "by_category": {
                "definition": {
                    "average_source_recall": 0.78,
                    "average_answer_term_recall": 0.78,
                    "average_answer_coverage": 0.78,
                    "average_latency_ms": 150,
                    "median_latency_ms": 150,
                    "needs_review_rate": 0.15,
                    "fallback_rate": 0.0,
                }
            },
        },
        "agentic_rag": {
            "average_source_recall": 0.7,
            "average_answer_term_recall": 0.7,
            "average_latency_ms": 500,
            "average_token_cost": 50,
            "needs_review_rate": 0.3,
            "fallback_rate": 0.4,
            "categories": ["definition"],
            "by_category": {
                "definition": {
                    "average_source_recall": 0.7,
                    "average_answer_term_recall": 0.7,
                    "average_answer_coverage": 0.7,
                    "average_latency_ms": 500,
                    "median_latency_ms": 500,
                    "estimated_cost_recorded_rate": 1.0,
                    "needs_review_rate": 0.3,
                    "fallback_rate": 0.4,
                }
            },
        },
    }

    readiness = evaluate_route_readiness(summary)

    assert readiness["graph_rag_lite"]["overall"] == "candidate"
    assert readiness["agentic_rag"]["overall"] == "hold"
    assert readiness["simple_rag"]["overall"] == "baseline"


def test_graph_route_readiness_uses_median_latency_not_average():
    report = RAGEvaluationReport()
    for latency_ms in [100, 100, 100]:
        report.add_score(
            mode="simple_rag",
            category="concept_relation",
            source_recall=0.8,
            answer_term_recall=0.8,
            answer_coverage=0.8,
            latency_ms=latency_ms,
            token_cost=10,
        )
    for latency_ms in [150, 150, 1000]:
        report.add_score(
            mode="graph_rag_lite",
            category="concept_relation",
            source_recall=0.78,
            answer_term_recall=0.78,
            answer_coverage=0.78,
            latency_ms=latency_ms,
            token_cost=20,
        )

    summary = report.summary()
    readiness = evaluate_route_readiness(summary)

    assert summary["graph_rag_lite"]["by_category"]["concept_relation"][
        "average_latency_ms"
    ] > 200
    assert summary["graph_rag_lite"]["by_category"]["concept_relation"][
        "median_latency_ms"
    ] == 150
    assert readiness["graph_rag_lite"]["by_category"]["concept_relation"] == "candidate"


def test_agentic_route_readiness_requires_complete_cost_recording():
    report = RAGEvaluationReport()
    report.add_score(
        mode="simple_rag",
        category="question_generation",
        source_recall=0.7,
        answer_term_recall=0.7,
        answer_coverage=0.7,
        latency_ms=100,
        token_cost=10,
    )
    report.add_score(
        mode="agentic_rag",
        category="question_generation",
        source_recall=0.8,
        answer_term_recall=0.7,
        answer_coverage=0.8,
        latency_ms=250,
        token_cost=None,
    )

    missing_cost_summary = report.summary()
    missing_cost_readiness = evaluate_route_readiness(missing_cost_summary)

    assert missing_cost_summary["agentic_rag"]["by_category"]["question_generation"][
        "estimated_cost_recorded_rate"
    ] == 0.0
    assert (
        missing_cost_readiness["agentic_rag"]["by_category"]["question_generation"]
        == "hold"
    )

    complete_cost_report = RAGEvaluationReport()
    complete_cost_report.add_score(
        mode="simple_rag",
        category="question_generation",
        source_recall=0.7,
        answer_term_recall=0.7,
        answer_coverage=0.7,
        latency_ms=100,
        token_cost=10,
    )
    complete_cost_report.add_score(
        mode="agentic_rag",
        category="question_generation",
        source_recall=0.8,
        answer_term_recall=0.7,
        answer_coverage=0.8,
        latency_ms=250,
        token_cost=35,
    )

    complete_cost_summary = complete_cost_report.summary()
    complete_cost_readiness = evaluate_route_readiness(complete_cost_summary)

    assert complete_cost_summary["agentic_rag"]["by_category"]["question_generation"][
        "estimated_cost_recorded_rate"
    ] == 1.0
    assert (
        complete_cost_readiness["agentic_rag"]["by_category"]["question_generation"]
        == "candidate"
    )
