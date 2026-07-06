from __future__ import annotations

from dataclasses import dataclass

from src.services.rag_router import RetrievalMode
from src.services.study_agent import StudyBudget, StudyTarget


@dataclass(frozen=True)
class StudySkill:
    skill_name: str
    version: str
    supported_targets: tuple[StudyTarget, ...]
    allowed_retrieval_modes: tuple[RetrievalMode, ...]
    default_budget: StudyBudget
    review_gate_profile: str
    memory_inputs: tuple[str, ...]
    memory_outputs: tuple[str, ...]

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "skill_name": self.skill_name,
            "skill_version": self.version,
            "supported_targets": [target.value for target in self.supported_targets],
            "allowed_retrieval_modes": [
                mode.value for mode in self.allowed_retrieval_modes
            ],
            "default_budget": self.default_budget.value,
            "review_gate_profile": self.review_gate_profile,
            "memory_inputs": list(self.memory_inputs),
            "memory_outputs": list(self.memory_outputs),
        }


class StudySkillRegistry:
    def __init__(self, skills: tuple[StudySkill, ...] | None = None) -> None:
        self._skills = skills or _DEFAULT_SKILLS

    def list_skills(self) -> list[dict[str, object]]:
        return [skill.to_safe_dict() for skill in self._skills]

    def select_skill(
        self,
        *,
        target: StudyTarget,
        category: str | None,
        requested_skill: str | None = None,
        requested_version: str | None = None,
    ) -> StudySkill:
        if requested_skill:
            return self._select_requested(
                target=target,
                requested_skill=requested_skill,
                requested_version=requested_version,
            )

        if category == "multi_document_synthesis":
            return self._skill_for("multi_document_synthesis", target=target)
        if category == "concept_relation":
            return self._skill_for("concept_relation", target=target)
        if target == StudyTarget.QUESTION or category == "question_generation":
            return self._skill_for("practice_question", target=target)
        if target == StudyTarget.OUTLINE_FRAGMENT or category == "outline_fragment":
            return self._skill_for("outline_fragment", target=target)
        return self._skill_for("concept_explanation", target=target)

    def _select_requested(
        self,
        *,
        target: StudyTarget,
        requested_skill: str,
        requested_version: str | None,
    ) -> StudySkill:
        candidates = [skill for skill in self._skills if skill.skill_name == requested_skill]
        if not candidates:
            raise ValueError("unsupported study skill")

        version = requested_version or "v1"
        for skill in candidates:
            if skill.version == version:
                if target not in skill.supported_targets:
                    raise ValueError("study skill does not support target")
                return skill
        raise ValueError("unsupported skill version")

    def _skill_for(self, skill_name: str, *, target: StudyTarget) -> StudySkill:
        for skill in self._skills:
            if skill.skill_name == skill_name and target in skill.supported_targets:
                return skill
        raise ValueError("study skill does not support target")


_DEFAULT_SKILLS = (
    StudySkill(
        skill_name="concept_explanation",
        version="v1",
        supported_targets=(StudyTarget.ANSWER,),
        allowed_retrieval_modes=(RetrievalMode.SIMPLE, RetrievalMode.GRAPH),
        default_budget=StudyBudget.BALANCED,
        review_gate_profile="standard",
        memory_inputs=("user_preference", "study_state"),
        memory_outputs=("skill_performance",),
    ),
    StudySkill(
        skill_name="practice_question",
        version="v1",
        supported_targets=(StudyTarget.QUESTION,),
        allowed_retrieval_modes=(
            RetrievalMode.SIMPLE,
            RetrievalMode.GRAPH,
            RetrievalMode.AGENTIC,
        ),
        default_budget=StudyBudget.BALANCED,
        review_gate_profile="strict",
        memory_inputs=("user_preference", "study_state"),
        memory_outputs=("review_outcome", "skill_performance"),
    ),
    StudySkill(
        skill_name="outline_fragment",
        version="v1",
        supported_targets=(StudyTarget.OUTLINE_FRAGMENT,),
        allowed_retrieval_modes=(RetrievalMode.SIMPLE, RetrievalMode.GRAPH),
        default_budget=StudyBudget.BALANCED,
        review_gate_profile="strict",
        memory_inputs=("user_preference", "study_state"),
        memory_outputs=("review_outcome", "skill_performance"),
    ),
    StudySkill(
        skill_name="concept_relation",
        version="v1",
        supported_targets=(StudyTarget.ANSWER,),
        allowed_retrieval_modes=(RetrievalMode.GRAPH, RetrievalMode.SIMPLE),
        default_budget=StudyBudget.BALANCED,
        review_gate_profile="standard",
        memory_inputs=("study_state",),
        memory_outputs=("skill_performance",),
    ),
    StudySkill(
        skill_name="multi_document_synthesis",
        version="v1",
        supported_targets=(StudyTarget.ANSWER, StudyTarget.QUESTION),
        allowed_retrieval_modes=(
            RetrievalMode.AGENTIC,
            RetrievalMode.GRAPH,
            RetrievalMode.SIMPLE,
        ),
        default_budget=StudyBudget.HIGH,
        review_gate_profile="strict",
        memory_inputs=("user_preference", "study_state"),
        memory_outputs=("review_outcome", "skill_performance"),
    ),
)
