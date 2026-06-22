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
    ReviewTaskRecord,
    ContentVersionRecord,
    create_session_factory,
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
        session.add_all([document, artifact, version, export, feedback, review, audit])
        session.commit()

    with Session(engine) as session:
        version = session.get(ContentVersionRecord, "outline:doc-1:v1")
        artifact = session.get(DocumentArtifactRecord, "artifact-1")
        audit = session.get(AuditEventRecord, "audit-1")

        assert version.content_metadata == {"generator": "test"}
        assert artifact.artifact_metadata == {"source": "test"}
        assert audit.event_metadata == {"filename": "Lecture Notes.pdf"}
