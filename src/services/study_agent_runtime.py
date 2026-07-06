from __future__ import annotations

from collections.abc import Callable
from time import perf_counter
from typing import Any

from src.knowledge.knowledge_graph import KnowledgeGraph
from src.services.agentic_rag import AgenticRAGPlanner
from src.services.rag_route_policy import (
    RAGReadinessSnapshot,
    RAGRoutePolicyConfig,
    RAGRoutePolicyService,
)
from src.services.rag_router import RAGStrategyRouter
from src.services.rag_service import RAGService
from src.services.study_agent import (
    EvidenceCollector,
    StudyAgentOrchestrator,
    StudyContentGenerator,
    StudyVerifier,
    normalize_study_request,
)
from src.services.study_agent_documents import (
    StudyAgentDocumentError,
    StudyDocumentChunker,
    StudyDocumentEvidence,
    StudyDocumentEvidenceSource,
)
from src.services.study_agent_index import (
    StudyDocumentIndexService,
    persisted_chunk_set_is_complete,
)
from src.services.study_agent_skills import StudySkillRegistry
from src.services.study_agent_workflow import (
    ReviewGate,
    WorkflowStageName,
    WorkflowStageResult,
    WorkflowStageStatus,
    build_workflow_payload,
    new_workflow_id,
)


class StudyAgentRuntimeService:
    def __init__(
        self,
        *,
        session_factory,
        evidence_source: StudyDocumentEvidenceSource | None = None,
        chunker: StudyDocumentChunker | None = None,
        index_service: StudyDocumentIndexService | None = None,
        graph: KnowledgeGraph | None = None,
        graph_factory: Callable[[tuple[StudyDocumentEvidence, ...]], KnowledgeGraph | None]
        | None = None,
        agentic_planner: AgenticRAGPlanner | None = None,
        generator: StudyContentGenerator | None = None,
        verifier: StudyVerifier | None = None,
        router: RAGStrategyRouter | None = None,
        route_policy: RAGRoutePolicyService | None = None,
        skill_registry: StudySkillRegistry | None = None,
        readiness_provider: Callable[[], RAGReadinessSnapshot | None] | None = None,
        top_k: int = 5,
    ) -> None:
        self.session_factory = session_factory
        self.evidence_source = evidence_source or StudyDocumentEvidenceSource(session_factory)
        self.chunker = chunker or StudyDocumentChunker()
        self.index_service = index_service or StudyDocumentIndexService(
            session_factory=session_factory,
            chunker=self.chunker,
        )
        self.graph = graph
        self.graph_factory = graph_factory
        self.agentic_planner = agentic_planner
        self.generator = generator
        self.verifier = verifier
        self.router = router or RAGStrategyRouter()
        self.route_policy = route_policy or RAGRoutePolicyService(RAGRoutePolicyConfig())
        self.skill_registry = skill_registry or StudySkillRegistry()
        self.readiness_provider = readiness_provider or (lambda: None)
        self.top_k = top_k

    async def run(self, payload: dict[str, Any]):
        request = normalize_study_request(payload)
        started_at = perf_counter()
        workflow_id = new_workflow_id()
        stages: list[WorkflowStageResult] = []

        def add_stage(
            name: WorkflowStageName,
            *,
            status: WorkflowStageStatus = WorkflowStageStatus.PASSED,
            input_summary: dict[str, Any] | None = None,
            output_summary: dict[str, Any] | None = None,
            error_code: str | None = None,
            review_reason: str | None = None,
        ) -> None:
            stages.append(
                WorkflowStageResult(
                    stage_name=name,
                    status=status,
                    input_summary=input_summary or {},
                    output_summary=output_summary or {},
                    duration_ms=0.0,
                    error_code=error_code,
                    review_reason=review_reason,
                )
            )

        if not request.authenticated_user_id:
            raise StudyAgentDocumentError(
                status_code=422,
                code="authentication_required",
                detail="Study Agent requires an authenticated user.",
            )
        add_stage(
            WorkflowStageName.INTAKE,
            output_summary={
                "document_count": len(request.document_ids),
                "target": request.target.value,
                "estimated_cost": request.budget.value,
            },
        )

        try:
            evidence = self.evidence_source.load(
                owner_id=request.authenticated_user_id,
                document_ids=request.document_ids,
            )
            persisted_chunks = self.index_service.load_chunks(
                owner_id=request.authenticated_user_id,
                document_ids=request.document_ids,
            )
            requested_artifact_by_document_id = {
                item.document_id: item.artifact_id for item in evidence
            }
            index_statuses = {
                document_id: self.index_service.status(
                    owner_id=request.authenticated_user_id,
                    document_id=document_id,
                ).to_dict()
                for document_id in requested_artifact_by_document_id
            }
            requested_document_ids = set(requested_artifact_by_document_id)
            persisted_chunks_by_document_id: dict[str, list[dict[str, Any]]] = {}
            for chunk in persisted_chunks:
                document_id = str(chunk.get("metadata", {}).get("document_id") or "")
                if document_id:
                    persisted_chunks_by_document_id.setdefault(document_id, []).append(chunk)
            persisted_document_ids = set(persisted_chunks_by_document_id)
            stale_document_ids = {
                document_id
                for document_id, artifact_id in requested_artifact_by_document_id.items()
                if document_id in persisted_chunks_by_document_id
                and any(
                    str(chunk.get("metadata", {}).get("artifact_id")) != artifact_id
                    for chunk in persisted_chunks_by_document_id[document_id]
                )
            }
            incomplete_document_ids = {
                document_id
                for document_id, artifact_id in requested_artifact_by_document_id.items()
                if document_id in persisted_chunks_by_document_id
                and document_id not in stale_document_ids
                and not persisted_chunk_set_is_complete(
                    persisted_chunks_by_document_id[document_id],
                    document_id=document_id,
                    artifact_id=artifact_id,
                )
            }
            if (
                requested_document_ids
                and requested_document_ids <= persisted_document_ids
                and not stale_document_ids
                and not incomplete_document_ids
            ):
                chunks = list(persisted_chunks)
                chunk_source = "persisted"
                fallback_reason = None
            else:
                chunks = self.chunker.chunk(evidence)
                chunk_source = "fallback"
                if not persisted_document_ids:
                    fallback_reason = "persisted_chunks_missing"
                elif stale_document_ids:
                    fallback_reason = "persisted_chunks_stale"
                else:
                    fallback_reason = "persisted_chunks_incomplete"
            if not chunks:
                raise StudyAgentDocumentError(
                    status_code=422,
                    code="document_evidence_missing",
                    detail="Processed document evidence is unavailable.",
                )
        except StudyAgentDocumentError as exc:
            workflow_error_code = (
                exc.code
                if exc.code
                in {
                    "authentication_required",
                    "document_evidence_missing",
                    "forbidden_document",
                    "bad_study_request",
                }
                else "document_evidence_missing"
            )
            add_stage(
                WorkflowStageName.RETRIEVE,
                status=WorkflowStageStatus.FAILED,
                error_code=workflow_error_code,
            )
            add_stage(
                WorkflowStageName.TRACE,
                output_summary={
                    "latency_ms": round((perf_counter() - started_at) * 1000, 3),
                    "stage_count": len(stages) + 1,
                },
            )
            setattr(
                exc,
                "workflow",
                build_workflow_payload(
                    workflow_id=workflow_id,
                    stages=stages,
                    needs_review=False,
                ),
            )
            raise

        router_decision = self.router.route(request.query, target=request.target.value)
        policy_decision = self.route_policy.decide(
            router_decision=router_decision,
            readiness=self.readiness_provider(),
            index_statuses=index_statuses,
            budget=request.budget.value,
            preferred_mode=request.preferred_mode,
        )
        add_stage(
            WorkflowStageName.PLAN,
            output_summary={
                "selected_mode": policy_decision.selected_mode.value,
                "router_mode": policy_decision.router_mode.value,
                "category": policy_decision.category,
                "policy_status": policy_decision.status,
                "readiness_status": policy_decision.readiness_status,
                "estimated_cost": policy_decision.estimated_cost,
            },
        )
        safe_policy = policy_decision.to_safe_dict()
        skill = self.skill_registry.select_skill(
            target=request.target,
            category=policy_decision.category,
            requested_skill=request.skill_name,
            requested_version=request.skill_version,
        )
        safe_skill = skill.to_safe_dict()
        add_stage(
            WorkflowStageName.SKILL_SELECT,
            output_summary={
                "skill_name": skill.skill_name,
                "skill_version": skill.version,
                "review_gate_profile": skill.review_gate_profile,
            },
        )
        orchestrator_payload = {
            **payload,
            "preferred_mode": policy_decision.selected_mode.value,
            "policy_decision": safe_policy,
            "skill": safe_skill,
        }

        rag_service = RAGService()
        rag_service.index_chunks(chunks)
        collector = EvidenceCollector(
            rag_service=rag_service,
            graph=self._graph_for(evidence),
            agentic_planner=self.agentic_planner,
            top_k=self.top_k,
        )
        orchestrator = StudyAgentOrchestrator(
            evidence_collector=collector,
            generator=self.generator,
            verifier=self.verifier,
            router=self.router,
        )
        result = await orchestrator.run(orchestrator_payload)
        add_stage(
            WorkflowStageName.RETRIEVE,
            output_summary={
                "chunk_count": len(result.evidence.chunks),
                "source_count": len(result.evidence.sources),
                "concept_count": len(result.evidence.concept_ids),
                "chunk_source": chunk_source,
                "fallback_reason": result.evidence.fallback_reason or fallback_reason,
                "mode": result.evidence.mode.value,
            },
        )
        add_stage(
            WorkflowStageName.GENERATE,
            output_summary={
                "target": result.draft.target.value,
                "citation_count": len(result.draft.citations),
                "used_chunk_count": result.draft.used_chunk_count,
                "mode": result.evidence.mode.value,
            },
        )
        add_stage(
            WorkflowStageName.VERIFY,
            status=(
                WorkflowStageStatus.PASSED
                if not result.verification.needs_review
                else WorkflowStageStatus.NEEDS_REVIEW
            ),
            output_summary={
                "needs_review": result.verification.needs_review,
                "confidence": result.verification.confidence,
                "source_recall": result.verification.source_recall,
                "answer_term_recall": result.verification.answer_term_recall,
                "issue_count": len(result.verification.issues),
            },
            review_reason=("verification_failed" if result.verification.needs_review else None),
        )
        review_decision = ReviewGate().evaluate(
            target=result.request.target,
            evidence=result.evidence,
            draft=result.draft,
            verification=result.verification,
            policy_status=safe_policy.get("status"),
        )
        add_stage(
            WorkflowStageName.REVIEW_GATE,
            status=review_decision.status,
            output_summary={
                "needs_review": review_decision.status == WorkflowStageStatus.NEEDS_REVIEW,
                "review_reason": (
                    review_decision.review_reasons[0]
                    if review_decision.review_reasons
                    else None
                ),
            },
            review_reason=(
                review_decision.review_reasons[0]
                if review_decision.review_reasons
                else None
            ),
        )
        add_stage(
            WorkflowStageName.TRACE,
            output_summary={
                "latency_ms": round((perf_counter() - started_at) * 1000, 3),
                "stage_count": len(stages) + 1,
            },
        )
        workflow = build_workflow_payload(
            workflow_id=workflow_id,
            stages=stages,
            needs_review=result.verification.needs_review
            or review_decision.status == WorkflowStageStatus.NEEDS_REVIEW,
        )
        result.audit_metadata["chunk_source"] = chunk_source
        result.audit_metadata["fallback_reason"] = fallback_reason
        result.audit_metadata["index_statuses"] = index_statuses
        result.audit_metadata["policy"] = safe_policy
        result.audit_metadata["skill"] = safe_skill
        result.audit_metadata["latency_ms"] = round((perf_counter() - started_at) * 1000, 3)
        result.audit_metadata["workflow"] = workflow
        return result

    def _graph_for(self, evidence: tuple[StudyDocumentEvidence, ...]) -> KnowledgeGraph | None:
        if self.graph_factory is not None:
            return self.graph_factory(evidence)
        return self.graph
