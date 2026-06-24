from src.services.rag_router import RetrievalMode
from src.services.rag_service import Chunk
from src.services.study_agent import (
    EvidenceBundle,
    StudyContentGenerator,
    StudyRequest,
    StudyTarget,
    StudyVerifier,
)


def _bundle() -> EvidenceBundle:
    return EvidenceBundle(
        mode=RetrievalMode.SIMPLE,
        chunks=(
            Chunk(
                content="导数描述函数的变化率。",
                source="calculus:derivative",
                score=0.9,
            ),
        ),
        sources=("calculus:derivative",),
        concept_ids=("kp-derivative",),
        confidence=0.9,
        reason="simple token-overlap retrieval",
    )


def test_generator_creates_answer_with_citation():
    draft = StudyContentGenerator().generate(
        StudyRequest(query="什么是导数？", target=StudyTarget.ANSWER),
        _bundle(),
    )

    assert draft.target == StudyTarget.ANSWER
    assert "导数描述函数的变化率" in draft.content
    assert "calculus:derivative" in draft.content
    assert draft.citations == ("calculus:derivative",)


def test_generator_creates_question_answer_explanation_and_rubric():
    draft = StudyContentGenerator().generate(
        StudyRequest(query="基于第2章出一道题", target=StudyTarget.QUESTION),
        _bundle(),
    )

    assert "### Practice Question" in draft.content
    assert "### Answer" in draft.content
    assert "### Explanation" in draft.content
    assert "### Scoring Rubric" in draft.content
    assert draft.metadata["target"] == "question"


def test_generator_creates_outline_fragment():
    draft = StudyContentGenerator().generate(
        StudyRequest(query="整理导数复习提纲", target=StudyTarget.OUTLINE_FRAGMENT),
        _bundle(),
    )

    assert draft.content.startswith("## Study Notes")
    assert "- 导数描述函数的变化率。" in draft.content


def test_verifier_passes_grounded_draft():
    request = StudyRequest(query="什么是导数？", expected_terms=("变化率",))
    draft = StudyContentGenerator().generate(request, _bundle())

    verification = StudyVerifier().verify(request, _bundle(), draft)

    assert verification.passed is True
    assert verification.needs_review is False
    assert verification.source_recall == 1.0
    assert verification.answer_term_recall == 1.0
    assert verification.issues == ()


def test_verifier_flags_missing_citations_and_low_confidence():
    request = StudyRequest(query="什么是矩阵分解？", expected_terms=("矩阵",))
    empty_bundle = EvidenceBundle(
        mode=RetrievalMode.SIMPLE,
        chunks=(),
        sources=(),
        concept_ids=(),
        confidence=0.0,
        reason="simple token-overlap retrieval",
    )
    draft = StudyContentGenerator().generate(request, empty_bundle)

    verification = StudyVerifier(min_confidence=0.5).verify(request, empty_bundle, draft)

    assert verification.passed is False
    assert verification.needs_review is True
    assert "missing citations" in verification.issues
    assert "low evidence confidence" in verification.issues


def test_verifier_flags_partial_source_recall():
    request = StudyRequest(query="什么是导数？", expected_terms=("变化率",))
    evidence = EvidenceBundle(
        mode=RetrievalMode.SIMPLE,
        chunks=(
            Chunk(
                content="导数描述函数的变化率。",
                source="s1",
                score=0.9,
            ),
            Chunk(
                content="导数也可以用于切线斜率。",
                source="s2",
                score=0.8,
            ),
        ),
        sources=("s1", "s2"),
        concept_ids=("kp-derivative",),
        confidence=0.9,
        reason="simple token-overlap retrieval",
    )
    draft = StudyContentGenerator().generate(request, evidence)
    partial_draft = draft.__class__(
        target=draft.target,
        content=draft.content,
        citations=("s1",),
        used_chunk_count=draft.used_chunk_count,
        metadata=draft.metadata,
    )

    verification = StudyVerifier().verify(request, evidence, partial_draft)

    assert verification.passed is False
    assert verification.needs_review is True
    assert verification.source_recall == 0.5
    assert "missing expected sources" in verification.issues
