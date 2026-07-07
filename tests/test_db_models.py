import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.db import (
    AuditEventRecord,
    Base,
    Document,
    DocumentArtifactRecord,
    ExportJobRecord,
    FeedbackRecord,
    KnowledgePointRecord,
    OutlineRecord,
    ParsedSection,
    ProcessingJob,
    QuestionRecord,
    RAGEvaluationCaseScoreRecord,
    RAGEvaluationRunRecord,
    ReviewTaskRecord,
    StudyAgentRunRecord,
    StudyAgentMemoryRecord,
    StudyAgentTraceRecord,
    ContentVersionRecord,
    create_session_factory,
    DocumentChunkRecord,
)


def test_db_models_create_and_query_relationships(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'study_agent.db'}")
    Base.metadata.create_all(engine)
    SessionFactory = create_session_factory(engine)

    with SessionFactory() as session:
        document = Document(
            id="doc-1",
            owner_id="user-1",
            title="Lecture Notes",
            source_type="pdf",
            storage_uri="file:///safe/uuid.pdf",
            content_hash="sha256:abc",
            original_filename="Lecture Notes.pdf",
            status="uploaded",
        )
        job = ProcessingJob(
            id="job-1",
            document=document,
            owner_id="user-1",
            job_type="process_document",
            status="queued",
            progress=0,
        )
        section = ParsedSection(
            id="section-1",
            document=document,
            title="Introduction",
            content="content",
            level=1,
            order_index=0,
        )
        point = KnowledgePointRecord(
            id="kp-1",
            document=document,
            name="Regression",
            description="Fit a relationship",
            category="statistics",
            point_type="concept",
            importance=5,
        )
        outline = OutlineRecord(id="outline-1", document=document, markdown="# Outline")
        question = QuestionRecord(
            id="question-1",
            document=document,
            knowledge_point=point,
            stem="What is regression?",
            answer="A modeling method",
            explanation="It estimates relationships between variables.",
            difficulty="medium",
            question_type="short_answer",
        )
        session.add_all([document, job, section, point, outline, question])
        session.commit()

    with Session(engine) as session:
        document = session.get(Document, "doc-1")
        assert document is not None
        assert document.jobs[0].status == "queued"
        assert document.jobs[0].owner_id == "user-1"
        assert document.sections[0].title == "Introduction"
        assert document.knowledge_points[0].importance == 5
        assert document.outlines[0].markdown == "# Outline"
        assert document.questions[0].knowledge_point.name == "Regression"


def test_processing_job_status_accepts_expected_lifecycle_values(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'jobs.db'}")
    Base.metadata.create_all(engine)
    SessionFactory = create_session_factory(engine)

    statuses = ["queued", "running", "completed", "succeeded", "failed", "cancelled", "canceled"]
    with SessionFactory() as session:
        document = Document(
            id="doc-1",
            owner_id="user-1",
            title="Lecture Notes",
            source_type="pdf",
            storage_uri="file:///safe/uuid.pdf",
            content_hash="sha256:abc",
            original_filename="Lecture Notes.pdf",
            status="uploaded",
        )
        session.add(document)
        for status in statuses:
            session.add(
                ProcessingJob(
                    id=f"job-{status}",
                    document=document,
                    owner_id="user-1",
                    job_type="process_document",
                    status=status,
                )
            )
        session.commit()

    with Session(engine) as session:
        stored_statuses = {
            row.status for row in session.query(ProcessingJob).order_by(ProcessingJob.id)
        }

    assert stored_statuses == set(statuses)


def test_processing_job_rejects_unknown_status(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'jobs.db'}")
    Base.metadata.create_all(engine)
    SessionFactory = create_session_factory(engine)

    with SessionFactory() as session:
        document = Document(
            id="doc-1",
            owner_id="user-1",
            title="Lecture Notes",
            source_type="pdf",
            storage_uri="file:///safe/uuid.pdf",
            content_hash="sha256:abc",
            original_filename="Lecture Notes.pdf",
            status="uploaded",
        )
        session.add(document)
        session.add(
            ProcessingJob(
                id="job-bad",
                document=document,
                owner_id="user-1",
                job_type="process_document",
                status="typoed_status",
            )
        )

        with pytest.raises(IntegrityError):
            session.commit()


def test_study_agent_run_record_accepts_product_lifecycle_statuses(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'runs.db'}")
    Base.metadata.create_all(engine)
    SessionFactory = create_session_factory(engine)
    statuses = [
        "queued",
        "running",
        "paused",
        "completed",
        "needs_review",
        "failed",
        "cancelled",
        "timed_out",
        "archived",
    ]

    with SessionFactory() as session:
        for status in statuses:
            session.add(
                StudyAgentRunRecord(
                    id=f"run-{status}",
                    owner_id="user-1",
                    request_id=f"req-{status}",
                    status=status,
                    query_hash="sha256:" + "a" * 64,
                    target="answer",
                    document_ids=["doc-1"],
                    expected_term_count=0,
                    attempt=1,
                    result_summary={},
                    lifecycle_metadata={},
                )
            )
        session.commit()

    with SessionFactory() as session:
        stored = {row.status for row in session.query(StudyAgentRunRecord).all()}
    assert stored == set(statuses)


def test_mvp7_product_records_create_and_preserve_metadata_columns(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'mvp7.db'}")
    Base.metadata.create_all(engine)
    SessionFactory = create_session_factory(engine)

    with SessionFactory() as session:
        document = Document(
            id="doc-1",
            owner_id="user-1",
            title="Lecture Notes",
            source_type="pdf",
            storage_uri="local://uploads/doc.pdf",
            content_hash="sha256:abc",
            original_filename="Lecture Notes.pdf",
            status="uploaded",
        )
        artifact = DocumentArtifactRecord(
            id="artifact-1",
            document=document,
            artifact_type="normalized_document",
            content="normalized",
            artifact_metadata={"source": "test"},
        )
        chunk = DocumentChunkRecord(
            id="chunk-1",
            document=document,
            owner_id="user-1",
            artifact_id="artifact-1",
            chunk_index=0,
            chunk_count=1,
            source="document:doc-1:chunk:0",
            content="normalized",
            chunk_metadata={
                "owner_id": "user-1",
                "document_id": "doc-1",
                "document_title": "Lecture Notes",
                "artifact_id": "artifact-1",
                "artifact_type": "normalized_document",
                "chunk_index": 0,
                "chunk_count": 1,
                "source_kind": "persisted_document_chunk",
            },
            content_hash="hash-normalized",
        )
        version = ContentVersionRecord(
            id="outline:doc-1:v1",
            document_id="doc-1",
            target_type="outline",
            target_id="doc-1",
            version=1,
            content="# Outline",
            created_by="worker",
            change_summary="initial",
            content_metadata={"generator": "test"},
        )
        export = ExportJobRecord(
            id="export-1",
            document=document,
            owner_id="user-1",
            version_id="outline:doc-1:v1",
            format="markdown",
            status="queued",
        )
        feedback = FeedbackRecord(
            id="feedback-1",
            owner_id="user-1",
            target_type="outline",
            target_id="doc-1",
            rating=1,
            reason="incorrect",
            comment="Needs review",
        )
        review = ReviewTaskRecord(
            id="review-1",
            owner_id="user-1",
            target_type="outline",
            target_id="doc-1",
            status="open",
            reason="incorrect",
        )
        audit = AuditEventRecord(
            id="audit-1",
            actor_id="user-1",
            action="document.uploaded",
            resource_type="document",
            resource_id="doc-1",
            request_id="req-1",
            event_metadata={"filename": "Lecture Notes.pdf"},
        )
        session.add_all([document, artifact, chunk, version, export, feedback, review, audit])
        session.commit()

    with Session(engine) as session:
        version = session.get(ContentVersionRecord, "outline:doc-1:v1")
        artifact = session.get(DocumentArtifactRecord, "artifact-1")
        chunk = session.get(DocumentChunkRecord, "chunk-1")
        audit = session.get(AuditEventRecord, "audit-1")

        assert version.content_metadata == {"generator": "test"}
        assert artifact.artifact_metadata == {"source": "test"}
        assert chunk is not None
        assert chunk.owner_id == "user-1"
        assert chunk.artifact_id == "artifact-1"
        assert chunk.chunk_metadata["source_kind"] == "persisted_document_chunk"
        assert chunk.document.title == "Lecture Notes"
        assert chunk.created_at is not None
        assert chunk.updated_at is not None
        assert audit.event_metadata == {"filename": "Lecture Notes.pdf"}


def test_review_task_record_accepts_safe_metadata(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'review_tasks.db'}")
    Base.metadata.create_all(engine)
    SessionFactory = create_session_factory(engine)

    safe_metadata = {
        "workflow_id": "workflow-0123456789abcdef0123456789abcdef",
        "trace_id": "trace-1",
        "selected_mode": "hybrid",
        "review_reasons": ["low_confidence", "citation_gap"],
        "confidence": 0.61,
        "source_count": 5,
        "chunk_count": 7,
        "citation_count": 3,
        "issue_count": 2,
    }

    with SessionFactory() as session:
        session.add(
            ReviewTaskRecord(
                id="review-safe-metadata-1",
                owner_id="user-1",
                target_type="study_agent_workflow",
                target_id="workflow-0123456789abcdef0123456789abcdef",
                status="open",
                reason="low_confidence",
                task_metadata=safe_metadata,
            )
        )
        session.commit()

    with Session(engine) as session:
        review = session.get(ReviewTaskRecord, "review-safe-metadata-1")

        assert review is not None
        assert review.task_metadata == safe_metadata
        assert (
            review.task_metadata["workflow_id"]
            == "workflow-0123456789abcdef0123456789abcdef"
        )
        assert review.task_metadata["trace_id"] == "trace-1"
        assert review.task_metadata["selected_mode"] == "hybrid"
        assert review.task_metadata["review_reasons"] == ["low_confidence", "citation_gap"]
        assert review.task_metadata["confidence"] == 0.61
        assert review.task_metadata["source_count"] == 5
        assert review.task_metadata["chunk_count"] == 7
        assert review.task_metadata["citation_count"] == 3
        assert review.task_metadata["issue_count"] == 2
        assert "raw_query" not in review.task_metadata


def test_rag_quality_observability_records_create_and_preserve_safe_metadata(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'rag_quality.db'}")
    Base.metadata.create_all(engine)
    SessionFactory = create_session_factory(engine)

    with SessionFactory() as session:
        trace = StudyAgentTraceRecord(
            id="trace-1",
            owner_id="user-1",
            request_id="req-1",
            query_hash="sha256:query",
            target="exam_prep",
            document_ids=["doc-1", "doc-2"],
            selected_mode="hybrid",
            route_reason="semantic_and_keyword_match",
            estimated_cost="low",
            fallback_chain=["hybrid", "keyword"],
            chunk_source="document_chunks",
            fallback_reason="semantic_low_confidence",
            source_count=8,
            used_chunk_count=4,
            confidence=0.86,
            source_recall=0.75,
            answer_term_recall=0.67,
            needs_review=True,
            latency_ms=47.25,
            trace_metadata={"experiment": "rag-quality"},
        )
        run = RAGEvaluationRunRecord(
            id="eval-run-1",
            created_by="user-1",
            fixture_version="fixture-v1",
            modes=["semantic", "hybrid"],
            case_count=2,
            status="completed",
            summary={"best_mode": "hybrid"},
            report_uri="local://reports/eval-run-1.json",
        )
        score = RAGEvaluationCaseScoreRecord(
            id="eval-score-1",
            run=run,
            case_id="case-1",
            mode="hybrid",
            category="definition",
            source_recall=0.95,
            answer_term_recall=0.85,
            answer_coverage=0.75,
            latency_ms=44.25,
            estimated_cost=0.008,
            needs_review=False,
            fallback_reason="",
            error_code="",
        )
        session.add_all([trace, run, score])
        session.commit()

    with Session(engine) as session:
        trace = session.get(StudyAgentTraceRecord, "trace-1")
        run = session.get(RAGEvaluationRunRecord, "eval-run-1")
        score = session.get(RAGEvaluationCaseScoreRecord, "eval-score-1")

        assert trace is not None
        assert trace.target == "exam_prep"
        assert trace.document_ids == ["doc-1", "doc-2"]
        assert trace.route_reason == "semantic_and_keyword_match"
        assert trace.estimated_cost == "low"
        assert trace.fallback_chain == ["hybrid", "keyword"]
        assert trace.chunk_source == "document_chunks"
        assert trace.fallback_reason == "semantic_low_confidence"
        assert trace.source_count == 8
        assert trace.used_chunk_count == 4
        assert trace.confidence == 0.86
        assert trace.source_recall == 0.75
        assert trace.answer_term_recall == 0.67
        assert trace.trace_metadata == {"experiment": "rag-quality"}
        assert trace.needs_review is True
        assert trace.latency_ms == 47.25

        assert run is not None
        assert run.fixture_version == "fixture-v1"
        assert run.modes == ["semantic", "hybrid"]
        assert run.summary == {"best_mode": "hybrid"}
        assert run.report_uri == "local://reports/eval-run-1.json"
        assert run.scores[0].id == "eval-score-1"

        assert score is not None
        assert score.run_id == "eval-run-1"
        assert score.run.summary == {"best_mode": "hybrid"}
        assert score.source_recall == 0.95
        assert score.answer_term_recall == 0.85
        assert score.answer_coverage == 0.75
        assert score.estimated_cost == 0.008
        assert score.needs_review is False


def test_study_agent_memory_record_persists_safe_metadata_fields(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'study_agent_memory.db'}")
    Base.metadata.create_all(engine)
    SessionFactory = create_session_factory(engine)

    safe_value = {
        "decision": "resolved",
        "reasons": ["low_confidence"],
        "metrics": {"confidence": 0.31, "source_count": 2, "chunk_count": 4},
    }

    with SessionFactory() as session:
        session.add(
            StudyAgentMemoryRecord(
                id="memory-1",
                owner_id="user-1",
                scope_type="workflow",
                scope_id="workflow-1",
                category="review_outcome",
                key="review-1",
                value_json=safe_value,
                confidence=0.31,
                source_type="review_task",
                source_id="review-1",
                privacy_level="safe_metadata",
            )
        )
        session.commit()

    with Session(engine) as session:
        memory = session.get(StudyAgentMemoryRecord, "memory-1")

        assert memory is not None
        assert memory.owner_id == "user-1"
        assert memory.scope_type == "workflow"
        assert memory.scope_id == "workflow-1"
        assert memory.category == "review_outcome"
        assert memory.key == "review-1"
        assert memory.value_json == safe_value
        assert memory.confidence == 0.31
        assert memory.source_type == "review_task"
        assert memory.source_id == "review-1"
        assert memory.privacy_level == "safe_metadata"
        assert memory.created_at is not None
        assert memory.updated_at is not None
        assert memory.expires_at is None
        assert "raw_query" not in memory.value_json
