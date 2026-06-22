from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QualityScore:
    target_type: str
    target_id: str
    metric: str
    score: float
    evidence: str


class QualityService:
    def score_outline(
        self,
        outline_markdown: str,
        required_terms: list[str],
        source_count: int,
    ) -> QualityScore:
        normalized_outline = outline_markdown.lower()
        matched_terms = [term for term in required_terms if term.lower() in normalized_outline]
        term_score = len(matched_terms) / max(1, len(required_terms))
        reference_score = 1.0 if source_count > 0 and "[p." in outline_markdown else 0.0
        score = min(1.0, (term_score + reference_score) / 2)

        return QualityScore(
            target_type="outline",
            target_id="inline",
            metric="outline_reference_coverage",
            score=score,
            evidence=f"matched_terms={matched_terms}; source_count={source_count}",
        )
