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
        "average_token_cost": 20,
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
                "average_token_cost": 10,
                "case_count": 1,
                "needs_review_rate": 0.0,
                "fallback_rate": 0.0,
            },
            "formula_lookup": {
                "average_source_recall": 0.5,
                "average_answer_term_recall": 0.75,
                "average_answer_coverage": 1.0,
                "average_latency_ms": 300,
                "average_token_cost": 30,
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
        "average_token_cost": 50,
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
                "average_token_cost": 50,
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
