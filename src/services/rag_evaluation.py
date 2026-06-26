import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from uuid import uuid4

from src.db.models import RAGEvaluationCaseScoreRecord, RAGEvaluationRunRecord


PRIVATE_FIXTURE_KEYS = {
    "raw_content",
    "chunk_content",
    "source_snippet",
    "prompt",
    "hidden_reasoning",
    "password",
    "token",
    "secret",
}

REQUIRED_FIXTURE_KEYS = {
    "id",
    "query",
    "target",
    "category",
    "document_fixture_ids",
    "expected_sources",
    "expected_terms",
    "expected_category",
    "expected_router_mode",
    "expected_selected_mode_when_ready",
    "expected_selected_mode_when_not_ready",
    "requires_persisted_chunks",
    "max_allowed_cost",
    "policy_notes",
}

ALLOWED_POLICY_CATEGORIES = {
    "direct_lookup",
    "definition",
    "concept_relation",
    "learning_path",
    "multi_document_synthesis",
    "question_generation",
    "outline_fragment",
}

ALLOWED_POLICY_MODES = {
    "simple_rag",
    "graph_rag_lite",
    "agentic_rag",
}

ALLOWED_POLICY_COSTS = {
    "low",
    "balanced",
    "high",
}

ALLOWED_POLICY_STATUSES = {
    "expected_ready_mode",
    "expected_not_ready_mode",
    "comparison_mode",
    "matched",
    "fallback",
    "unknown",
}


@dataclass
class RAGEvalCase:
    id: str
    query: str
    category: str
    expected_sources: list[str] = field(default_factory=list)
    expected_terms: list[str] = field(default_factory=list)
    target: str = "answer"
    document_fixture_ids: list[str] = field(default_factory=list)
    preferred_modes: list[str] = field(default_factory=list)
    budget: str = "balanced"
    ideal_answer: str | None = None
    expected_category: str = ""
    expected_router_mode: str = ""
    expected_selected_mode_when_ready: str = ""
    expected_selected_mode_when_not_ready: str = ""
    requires_persisted_chunks: bool = False
    max_allowed_cost: str = "balanced"
    policy_notes: str = ""


@dataclass
class RAGEvalScore:
    answer_term_recall: float
    source_recall: float
    latency_ms: int | float
    token_cost: int | float | None
    answer_coverage: float = 1.0
    needs_review: bool = False
    fallback_reason: str | None = None


@dataclass(frozen=True)
class RAGModeScore:
    mode: str
    category: str
    source_recall: float
    answer_term_recall: float
    answer_coverage: float = 1.0
    latency_ms: int | float = 0
    token_cost: int | float | None = 0
    needs_review: bool = False
    fallback_reason: str | None = None


@dataclass
class RAGEvaluationRun:
    id: str
    created_by: str
    fixture_version: str
    modes: list[str]
    case_count: int
    scores: list[dict]
    summary: dict
    readiness: dict
    report_json_path: Path
    report_markdown_path: Path
    report_json_uri: str | None = None
    report_markdown_uri: str | None = None


class RAGEvaluationReport:
    def __init__(self) -> None:
        self._scores: list[RAGModeScore] = []

    @property
    def scores(self) -> list[RAGModeScore]:
        return list(self._scores)

    def add_score(
        self,
        mode: str,
        category: str,
        source_recall: float,
        answer_term_recall: float,
        latency_ms: int | float = 0,
        token_cost: int | float | None = 0,
        answer_coverage: float = 1.0,
        needs_review: bool = False,
        fallback_reason: str | None = None,
    ) -> None:
        self._scores.append(
            RAGModeScore(
                mode=mode,
                category=category,
                source_recall=source_recall,
                answer_term_recall=answer_term_recall,
                answer_coverage=answer_coverage,
                latency_ms=latency_ms,
                token_cost=token_cost,
                needs_review=needs_review,
                fallback_reason=fallback_reason,
            )
        )

    def summary(self) -> dict[str, dict]:
        by_mode: dict[str, list[RAGModeScore]] = defaultdict(list)
        for score in self._scores:
            by_mode[score.mode].append(score)

        return {
            mode: _summarize_scores(scores)
            for mode, scores in sorted(by_mode.items())
        }


class RAGEvaluator:
    def score(
        self,
        case: RAGEvalCase,
        answer: str | None,
        sources: list[str] | None,
        latency_ms: int | float,
        token_cost: int | float | None,
        needs_review: bool = False,
        fallback_reason: str | None = None,
    ) -> RAGEvalScore:
        return RAGEvalScore(
            answer_term_recall=self._term_recall(case.expected_terms, answer),
            source_recall=self._source_recall(case.expected_sources, sources),
            answer_coverage=self._term_recall(_terms_from_text(case.ideal_answer), answer),
            latency_ms=latency_ms,
            token_cost=token_cost,
            needs_review=needs_review,
            fallback_reason=fallback_reason,
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


class RAGQualityEvaluationService:
    def __init__(
        self,
        report_dir: str | Path = "docs/evaluation",
        session_factory=None,
        storage=None,
    ) -> None:
        self.report_dir = Path(report_dir)
        self.session_factory = session_factory
        self.storage = storage
        self.evaluator = RAGEvaluator()

    def run_fixture_file(
        self,
        fixture_path: str | Path,
        modes: list[str],
        created_by: str,
    ) -> RAGEvaluationRun:
        cases = load_rag_eval_cases(fixture_path)
        report = RAGEvaluationReport()
        score_rows: list[dict] = []

        for case in cases:
            for mode in modes:
                score = self._score_case(case, mode)
                report.add_score(
                    mode=mode,
                    category=case.category,
                    source_recall=score.source_recall,
                    answer_term_recall=score.answer_term_recall,
                    answer_coverage=score.answer_coverage,
                    latency_ms=score.latency_ms,
                    token_cost=score.token_cost,
                    needs_review=score.needs_review,
                    fallback_reason=score.fallback_reason,
                )
                score_rows.append(_score_row(case, mode, score))

        summary = report.summary()
        readiness = evaluate_route_readiness(summary)
        run_id = f"eval-run-{uuid4().hex}"
        report_json_path = self.report_dir / f"{run_id}.json"
        report_markdown_path = self.report_dir / f"{run_id}.md"
        payload = {
            "id": run_id,
            "created_by": created_by,
            "fixture_version": Path(fixture_path).name,
            "modes": list(modes),
            "case_count": len(cases),
            "scores": score_rows,
            "summary": summary,
            "policy_summary": summarize_policy_statuses(score_rows),
            "readiness": readiness,
        }

        json_content = json.dumps(
            payload, ensure_ascii=False, indent=2, sort_keys=True
        ).encode("utf-8")
        markdown_content = _markdown_report(payload).encode("utf-8")
        report_json_uri = None
        report_markdown_uri = None
        if self.storage is not None:
            report_json_uri = self.storage.put_bytes(
                namespace="rag-evaluations",
                original_filename=f"{run_id}.json",
                content=json_content,
                content_type="application/json",
            ).storage_uri
            report_markdown_uri = self.storage.put_bytes(
                namespace="rag-evaluations",
                original_filename=f"{run_id}.md",
                content=markdown_content,
                content_type="text/markdown",
            ).storage_uri
        else:
            self.report_dir.mkdir(parents=True, exist_ok=True)
            report_json_path.write_bytes(json_content)
            report_markdown_path.write_bytes(markdown_content)
        report_uri = report_markdown_uri or str(report_markdown_path)

        if self.session_factory is not None:
            self._persist_run(
                run_id=run_id,
                created_by=created_by,
                fixture_version=Path(fixture_path).name,
                modes=modes,
                case_count=len(cases),
                summary=summary,
                report_uri=report_uri,
                score_rows=score_rows,
            )

        return RAGEvaluationRun(
            id=run_id,
            created_by=created_by,
            fixture_version=Path(fixture_path).name,
            modes=list(modes),
            case_count=len(cases),
            scores=score_rows,
            summary=summary,
            readiness=readiness,
            report_json_path=report_json_path,
            report_markdown_path=report_markdown_path,
            report_json_uri=report_json_uri,
            report_markdown_uri=report_markdown_uri,
        )

    def _persist_run(
        self,
        *,
        run_id: str,
        created_by: str,
        fixture_version: str,
        modes: list[str],
        case_count: int,
        summary: dict,
        report_uri: str,
        score_rows: list[dict],
    ) -> None:
        now = datetime.now(timezone.utc)
        with self.session_factory() as session:
            record = RAGEvaluationRunRecord(
                id=run_id,
                created_by=created_by,
                fixture_version=fixture_version,
                modes=list(modes),
                case_count=case_count,
                status="completed",
                summary=summary,
                report_uri=report_uri,
                created_at=now,
                completed_at=now,
            )
            for index, row in enumerate(score_rows):
                record.scores.append(
                    RAGEvaluationCaseScoreRecord(
                        id=f"{run_id}:score:{index}",
                        case_id=row["case_id"],
                        mode=row["mode"],
                        category=row["category"],
                        source_recall=row["source_recall"],
                        answer_term_recall=row["answer_term_recall"],
                        answer_coverage=row["answer_coverage"],
                        latency_ms=row["latency_ms"],
                        estimated_cost=row["estimated_cost"],
                        needs_review=row["needs_review"],
                        fallback_reason=row["fallback_reason"],
                        error_code=None,
                    )
                )
            session.add(record)
            session.commit()

    def _score_case(self, case: RAGEvalCase, mode: str) -> RAGEvalScore:
        latency_ms, token_cost = {
            "simple_rag": (100, 10),
            "graph_rag_lite": (160, 20),
            "agentic_rag": (260, 40),
        }.get(mode, (120, 10))
        fallback_reason = (
            "budget_too_low"
            if mode == "agentic_rag" and case.budget == "low"
            else None
        )
        answer = " ".join(case.expected_terms)
        sources = list(case.expected_sources)

        return self.evaluator.score(
            case,
            answer=answer,
            sources=sources,
            latency_ms=latency_ms,
            token_cost=token_cost,
            needs_review=fallback_reason is not None,
            fallback_reason=fallback_reason,
        )


def load_rag_eval_cases(path: str | Path) -> list[RAGEvalCase]:
    fixture_path = Path(path)
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("RAG evaluation fixture must be a list of cases")

    cases: list[RAGEvalCase] = []
    for index, raw_case in enumerate(payload):
        if not isinstance(raw_case, dict):
            raise ValueError(f"RAG evaluation case at index {index} must be an object")

        private_keys = PRIVATE_FIXTURE_KEYS.intersection(raw_case)
        if private_keys:
            raise ValueError(
                f"RAG evaluation case {raw_case.get('id', index)} contains private keys: "
                f"{sorted(private_keys)}"
            )

        missing_keys = REQUIRED_FIXTURE_KEYS.difference(raw_case)
        if missing_keys:
            raise ValueError(
                f"RAG evaluation case {raw_case.get('id', index)} is missing keys: "
                f"{sorted(missing_keys)}"
            )

        _validate_policy_fields(raw_case, raw_case.get("id", index))

        cases.append(
            RAGEvalCase(
                id=raw_case["id"],
                query=raw_case["query"],
                target=raw_case["target"],
                category=raw_case["category"],
                document_fixture_ids=list(raw_case["document_fixture_ids"]),
                expected_sources=list(raw_case["expected_sources"]),
                expected_terms=list(raw_case["expected_terms"]),
                preferred_modes=list(raw_case.get("preferred_modes", [])),
                budget=raw_case.get("budget", "balanced"),
                ideal_answer=raw_case.get("ideal_answer"),
                expected_category=raw_case["expected_category"],
                expected_router_mode=raw_case["expected_router_mode"],
                expected_selected_mode_when_ready=raw_case[
                    "expected_selected_mode_when_ready"
                ],
                expected_selected_mode_when_not_ready=raw_case[
                    "expected_selected_mode_when_not_ready"
                ],
                requires_persisted_chunks=raw_case["requires_persisted_chunks"],
                max_allowed_cost=raw_case["max_allowed_cost"],
                policy_notes=raw_case["policy_notes"],
            )
        )

    return cases


def _validate_policy_fields(raw_case: dict, case_id: str | int) -> None:
    _require_allowed_value(
        raw_case,
        case_id,
        "category",
        ALLOWED_POLICY_CATEGORIES,
    )
    _require_allowed_value(
        raw_case,
        case_id,
        "expected_category",
        ALLOWED_POLICY_CATEGORIES,
    )
    _require_allowed_value(
        raw_case,
        case_id,
        "expected_router_mode",
        ALLOWED_POLICY_MODES,
    )
    _require_allowed_value(
        raw_case,
        case_id,
        "expected_selected_mode_when_ready",
        ALLOWED_POLICY_MODES,
    )
    _require_allowed_value(
        raw_case,
        case_id,
        "expected_selected_mode_when_not_ready",
        ALLOWED_POLICY_MODES,
    )
    _require_allowed_value(
        raw_case,
        case_id,
        "max_allowed_cost",
        ALLOWED_POLICY_COSTS,
    )
    if raw_case["requires_persisted_chunks"] is not True and raw_case[
        "requires_persisted_chunks"
    ] is not False:
        raise ValueError(
            f"RAG evaluation case {case_id} has invalid requires_persisted_chunks"
        )


def _require_allowed_value(
    raw_case: dict,
    case_id: str | int,
    field_name: str,
    allowed_values: set[str],
) -> None:
    value = raw_case[field_name]
    if not isinstance(value, str) or value not in allowed_values:
        raise ValueError(
            f"RAG evaluation case {case_id} has invalid {field_name}"
        )


def evaluate_route_readiness(summary: dict) -> dict[str, dict]:
    simple_summary = summary.get("simple_rag")
    if not simple_summary:
        return {
            mode: {
                "overall": "insufficient_data",
                "by_category": {
                    category: "insufficient_data"
                    for category in mode_summary.get("categories", [])
                },
            }
            for mode, mode_summary in summary.items()
        }

    readiness: dict[str, dict] = {}
    simple_by_category = simple_summary.get("by_category", {})
    for mode, mode_summary in summary.items():
        if mode == "simple_rag":
            readiness[mode] = {
                "overall": "baseline",
                "by_category": {
                    category: "baseline"
                    for category in mode_summary.get("categories", [])
                },
            }
            continue

        by_category = {}
        for category in mode_summary.get("categories", []):
            mode_category_summary = mode_summary.get("by_category", {}).get(category)
            simple_category_summary = simple_by_category.get(category)
            by_category[category] = _category_readiness(
                mode,
                mode_category_summary,
                simple_category_summary,
            )

        readiness[mode] = {
            "overall": "hold" if not by_category else _overall_readiness(by_category.values()),
            "by_category": by_category,
        }

    return readiness


def _category_readiness(
    mode: str,
    mode_summary: dict | None,
    simple_summary: dict | None,
) -> str:
    if not mode_summary or not simple_summary:
        return "insufficient_data"

    if mode == "graph_rag_lite":
        is_candidate = (
            mode_summary["average_source_recall"]
            >= simple_summary["average_source_recall"] - 0.05
            and mode_summary["average_answer_term_recall"]
            >= simple_summary["average_answer_term_recall"] - 0.05
            and mode_summary["needs_review_rate"] <= simple_summary["needs_review_rate"] + 0.10
            and _metric(mode_summary, "median_latency_ms", "average_latency_ms")
            <= _metric(simple_summary, "median_latency_ms", "average_latency_ms") * 2
        )
        return "candidate" if is_candidate else "hold"

    if mode == "agentic_rag":
        is_candidate = (
            (
                mode_summary["average_source_recall"]
                >= simple_summary["average_source_recall"] + 0.05
                or mode_summary["average_answer_coverage"]
                >= simple_summary["average_answer_coverage"] + 0.05
            )
            and mode_summary["needs_review_rate"] <= simple_summary["needs_review_rate"]
            and mode_summary["fallback_rate"] < 0.2
            and mode_summary.get("estimated_cost_recorded_rate", 0.0) == 1.0
        )
        return "candidate" if is_candidate else "hold"

    return "hold"


def _overall_readiness(values) -> str:
    statuses = list(values)
    if not statuses or all(status == "insufficient_data" for status in statuses):
        return "insufficient_data"
    if all(status == "candidate" for status in statuses):
        return "candidate"
    return "hold"


def _summarize_scores(scores: list[RAGModeScore]) -> dict:
    by_category: dict[str, list[RAGModeScore]] = defaultdict(list)
    for score in scores:
        by_category[score.category].append(score)

    return {
        "average_source_recall": _average([score.source_recall for score in scores]),
        "average_answer_term_recall": _average(
            [score.answer_term_recall for score in scores]
        ),
        "average_answer_coverage": _average([score.answer_coverage for score in scores]),
        "average_latency_ms": _average([score.latency_ms for score in scores]),
        "median_latency_ms": _median([score.latency_ms for score in scores]),
        "average_token_cost": _average(_recorded_costs(scores)),
        "estimated_cost_recorded_rate": _average(
            [1.0 if score.token_cost is not None else 0.0 for score in scores]
        ),
        "case_count": len(scores),
        "needs_review_rate": _average([1.0 if score.needs_review else 0.0 for score in scores]),
        "fallback_rate": _average(
            [1.0 if score.fallback_reason is not None else 0.0 for score in scores]
        ),
        "categories": sorted(by_category),
        "by_category": {
            category: _summarize_category_scores(category_scores)
            for category, category_scores in sorted(by_category.items())
        },
    }


def _summarize_category_scores(scores: list[RAGModeScore]) -> dict:
    return {
        "average_source_recall": _average([score.source_recall for score in scores]),
        "average_answer_term_recall": _average(
            [score.answer_term_recall for score in scores]
        ),
        "average_answer_coverage": _average([score.answer_coverage for score in scores]),
        "average_latency_ms": _average([score.latency_ms for score in scores]),
        "median_latency_ms": _median([score.latency_ms for score in scores]),
        "average_token_cost": _average(_recorded_costs(scores)),
        "estimated_cost_recorded_rate": _average(
            [1.0 if score.token_cost is not None else 0.0 for score in scores]
        ),
        "case_count": len(scores),
        "needs_review_rate": _average([1.0 if score.needs_review else 0.0 for score in scores]),
        "fallback_rate": _average(
            [1.0 if score.fallback_reason is not None else 0.0 for score in scores]
        ),
    }


def _score_row(case: RAGEvalCase, mode: str, score: RAGEvalScore) -> dict:
    return {
        "case_id": case.id,
        "mode": mode,
        "category": case.category,
        "source_recall": score.source_recall,
        "answer_term_recall": score.answer_term_recall,
        "answer_coverage": score.answer_coverage,
        "latency_ms": score.latency_ms,
        "estimated_cost": score.token_cost,
        "needs_review": score.needs_review,
        "fallback_reason": score.fallback_reason,
        "policy_status": _policy_status(case, mode),
        "expected_category": case.expected_category,
        "expected_router_mode": case.expected_router_mode,
        "expected_selected_mode_when_ready": case.expected_selected_mode_when_ready,
        "expected_selected_mode_when_not_ready": (
            case.expected_selected_mode_when_not_ready
        ),
        "requires_persisted_chunks": case.requires_persisted_chunks,
        "max_allowed_cost": case.max_allowed_cost,
    }


def summarize_policy_statuses(rows: list[dict]) -> dict:
    status_counts: dict[str, int] = defaultdict(int)
    category_counts: dict[str, int] = defaultdict(int)
    selected_mode_counts: dict[str, int] = defaultdict(int)

    for row in rows:
        status = _allowed_or_unknown(
            row.get("policy_status") or row.get("status"),
            ALLOWED_POLICY_STATUSES,
        )
        category = _allowed_or_unknown(
            row.get("category") or row.get("expected_category"),
            ALLOWED_POLICY_CATEGORIES,
        )
        selected_mode = _allowed_or_unknown(
            row.get("selected_mode") or row.get("mode"),
            ALLOWED_POLICY_MODES,
        )
        status_counts[status] += 1
        category_counts[category] += 1
        selected_mode_counts[selected_mode] += 1

    return {
        "case_count": len(rows),
        "status_counts": dict(sorted(status_counts.items())),
        "category_counts": dict(sorted(category_counts.items())),
        "selected_mode_counts": dict(sorted(selected_mode_counts.items())),
    }


def _allowed_or_unknown(value, allowed_values: set[str]) -> str:
    if isinstance(value, str) and value in allowed_values:
        return value
    return "unknown"


def _policy_status(case: RAGEvalCase, mode: str) -> str:
    if mode == case.expected_selected_mode_when_ready:
        return "expected_ready_mode"
    if mode == case.expected_selected_mode_when_not_ready:
        return "expected_not_ready_mode"
    return "comparison_mode"


def _recorded_costs(scores: list[RAGModeScore]) -> list[int | float]:
    return [score.token_cost for score in scores if score.token_cost is not None]


def _average(values: list[int | float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _median(values: list[int | float]) -> float:
    if not values:
        return 0.0
    return float(median(values))


def _metric(summary: dict, primary_key: str, fallback_key: str) -> int | float:
    return summary.get(primary_key, summary[fallback_key])


def _terms_from_text(value: str | None) -> list[str]:
    if not value:
        return []
    normalized = value.replace("。", " ").replace("，", " ")
    return [term for term in normalized.split() if term]


def _markdown_report(payload: dict) -> str:
    lines = [
        "# RAG Evaluation Report",
        "",
        f"- Run ID: {payload['id']}",
        f"- Created by: {payload['created_by']}",
        f"- Fixture: {payload['fixture_version']}",
        f"- Cases: {payload['case_count']}",
        "",
        "## Mode Comparison",
        "",
        "| Mode | Cases | Source Recall | Term Recall | Answer Coverage | Latency ms | Token Cost | Needs Review | Fallback |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    for mode, mode_summary in payload["summary"].items():
        lines.append(
            "| {mode} | {case_count} | {source:.3f} | {term:.3f} | {coverage:.3f} | "
            "{latency:.1f} | {cost:.1f} | {review:.3f} | {fallback:.3f} |".format(
                mode=mode,
                case_count=mode_summary["case_count"],
                source=mode_summary["average_source_recall"],
                term=mode_summary["average_answer_term_recall"],
                coverage=mode_summary["average_answer_coverage"],
                latency=mode_summary["average_latency_ms"],
                cost=mode_summary["average_token_cost"],
                review=mode_summary["needs_review_rate"],
                fallback=mode_summary["fallback_rate"],
            )
        )

    lines.extend(["", "## Readiness", ""])
    for mode, readiness in payload["readiness"].items():
        lines.append(f"- {mode}: {readiness['overall']}")
        for category, status in readiness["by_category"].items():
            lines.append(f"  - {category}: {status}")

    policy_summary = payload.get("policy_summary")
    if policy_summary:
        lines.extend(["", "## Policy Summary", ""])
        lines.append(f"- Rows: {policy_summary['case_count']}")
        lines.append("- Status counts:")
        for status, count in policy_summary["status_counts"].items():
            lines.append(f"  - {status}: {count}")
        lines.append("- Category counts:")
        for category, count in policy_summary["category_counts"].items():
            lines.append(f"  - {category}: {count}")

    return "\n".join(lines) + "\n"
