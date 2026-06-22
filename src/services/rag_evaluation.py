from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class RAGEvalCase:
    id: str
    query: str
    category: str
    expected_sources: list[str] = field(default_factory=list)
    expected_terms: list[str] = field(default_factory=list)


@dataclass
class RAGEvalScore:
    answer_term_recall: float
    source_recall: float
    latency_ms: int | float
    token_cost: int | float


@dataclass(frozen=True)
class RAGModeScore:
    mode: str
    category: str
    source_recall: float
    answer_term_recall: float
    latency_ms: int | float = 0
    token_cost: int | float = 0


class RAGEvaluationReport:
    def __init__(self) -> None:
        self._scores: list[RAGModeScore] = []

    def add_score(
        self,
        mode: str,
        category: str,
        source_recall: float,
        answer_term_recall: float,
        latency_ms: int | float = 0,
        token_cost: int | float = 0,
    ) -> None:
        self._scores.append(
            RAGModeScore(
                mode=mode,
                category=category,
                source_recall=source_recall,
                answer_term_recall=answer_term_recall,
                latency_ms=latency_ms,
                token_cost=token_cost,
            )
        )

    def summary(self) -> dict[str, dict[str, float | list[str]]]:
        by_mode: dict[str, list[RAGModeScore]] = defaultdict(list)
        for score in self._scores:
            by_mode[score.mode].append(score)

        return {
            mode: {
                "average_source_recall": sum(item.source_recall for item in scores) / len(scores),
                "average_answer_term_recall": sum(item.answer_term_recall for item in scores)
                / len(scores),
                "average_latency_ms": sum(item.latency_ms for item in scores) / len(scores),
                "average_token_cost": sum(item.token_cost for item in scores) / len(scores),
                "categories": sorted({item.category for item in scores}),
            }
            for mode, scores in by_mode.items()
        }


class RAGEvaluator:
    def score(
        self,
        case: RAGEvalCase,
        answer: str | None,
        sources: list[str] | None,
        latency_ms: int | float,
        token_cost: int | float,
    ) -> RAGEvalScore:
        return RAGEvalScore(
            answer_term_recall=self._term_recall(case.expected_terms, answer),
            source_recall=self._source_recall(case.expected_sources, sources),
            latency_ms=latency_ms,
            token_cost=token_cost,
        )

    def _term_recall(self, expected_terms: list[str], answer: str | None) -> float:
        unique_expected_terms = self._unique(expected_terms)
        if not unique_expected_terms:
            return 1.0

        answer_text = answer or ""
        matched_terms = sum(1 for term in unique_expected_terms if term in answer_text)
        return matched_terms / len(unique_expected_terms)

    def _source_recall(
        self,
        expected_sources: list[str],
        sources: list[str] | None,
    ) -> float:
        unique_expected_sources = self._unique(expected_sources)
        if not unique_expected_sources:
            return 1.0

        source_set = set(sources or [])
        matched_sources = sum(1 for source in unique_expected_sources if source in source_set)
        return matched_sources / len(unique_expected_sources)

    def _unique(self, values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))
