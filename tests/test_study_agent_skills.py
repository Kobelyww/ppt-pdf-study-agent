from __future__ import annotations

import pytest

from src.services.rag_router import RetrievalMode
from src.services.study_agent import StudyBudget, StudyTarget
from src.services.study_agent_skills import StudySkillRegistry


def test_default_answer_definition_selects_concept_explanation_v1():
    skill = StudySkillRegistry().select_skill(
        target=StudyTarget.ANSWER,
        category="definition",
    )

    assert skill.skill_name == "concept_explanation"
    assert skill.version == "v1"
    assert skill.supported_targets == (StudyTarget.ANSWER,)


def test_question_generation_selects_practice_question_v1():
    skill = StudySkillRegistry().select_skill(
        target=StudyTarget.QUESTION,
        category="question_generation",
    )

    assert skill.skill_name == "practice_question"
    assert skill.version == "v1"
    assert skill.supported_targets == (StudyTarget.QUESTION,)


def test_outline_fragment_selects_outline_fragment_v1():
    skill = StudySkillRegistry().select_skill(
        target=StudyTarget.OUTLINE_FRAGMENT,
        category="outline_fragment",
    )

    assert skill.skill_name == "outline_fragment"
    assert skill.version == "v1"
    assert skill.supported_targets == (StudyTarget.OUTLINE_FRAGMENT,)


def test_concept_relation_category_selects_concept_relation_v1():
    skill = StudySkillRegistry().select_skill(
        target=StudyTarget.ANSWER,
        category="concept_relation",
    )

    assert skill.skill_name == "concept_relation"
    assert skill.version == "v1"


def test_multi_document_synthesis_category_selects_multi_document_synthesis_v1():
    skill = StudySkillRegistry().select_skill(
        target=StudyTarget.ANSWER,
        category="multi_document_synthesis",
    )

    assert skill.skill_name == "multi_document_synthesis"
    assert skill.version == "v1"
    assert skill.supported_targets == (StudyTarget.ANSWER, StudyTarget.QUESTION)


def test_unsupported_requested_version_raises_value_error():
    with pytest.raises(ValueError, match="unsupported skill version"):
        StudySkillRegistry().select_skill(
            target=StudyTarget.ANSWER,
            category="definition",
            requested_skill="concept_explanation",
            requested_version="v2",
        )


def test_requested_skill_that_does_not_support_target_raises_value_error():
    with pytest.raises(ValueError, match="does not support target"):
        StudySkillRegistry().select_skill(
            target=StudyTarget.QUESTION,
            category="question_generation",
            requested_skill="concept_explanation",
            requested_version="v1",
        )


def test_skill_to_safe_dict_returns_only_safe_labels_and_lists():
    skill = StudySkillRegistry().select_skill(
        target=StudyTarget.ANSWER,
        category="definition",
    )

    assert skill.to_safe_dict() == {
        "skill_name": "concept_explanation",
        "skill_version": "v1",
        "supported_targets": [StudyTarget.ANSWER.value],
        "allowed_retrieval_modes": [
            RetrievalMode.SIMPLE.value,
            RetrievalMode.GRAPH.value,
        ],
        "default_budget": StudyBudget.BALANCED.value,
        "review_gate_profile": "standard",
        "memory_inputs": ["user_preference", "study_state"],
        "memory_outputs": ["skill_performance"],
    }
