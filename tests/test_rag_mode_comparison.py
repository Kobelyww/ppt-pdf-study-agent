from src.services.rag_evaluation import RAGEvaluationReport


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
        "average_latency_ms": 200,
        "average_token_cost": 20,
        "categories": ["definition", "formula_lookup"],
    }
    assert summary["graph_rag_lite"] == {
        "average_source_recall": 1.0,
        "average_answer_term_recall": 0.8,
        "average_latency_ms": 500,
        "average_token_cost": 50,
        "categories": ["concept_relation"],
    }
