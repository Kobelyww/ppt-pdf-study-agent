from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class UserRecord(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="user", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    name: Mapped[Optional[str]] = mapped_column(String(255))
    display_name: Mapped[Optional[str]] = mapped_column(String(255))
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, default="demo-user", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    storage_uri: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    original_filename: Mapped[Optional[str]] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="uploaded")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    jobs: Mapped[List["ProcessingJob"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    sections: Mapped[List["ParsedSection"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    knowledge_points: Mapped[List["KnowledgePointRecord"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    outlines: Mapped[List["OutlineRecord"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    questions: Mapped[List["QuestionRecord"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    artifacts: Mapped[List["DocumentArtifactRecord"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    chunks: Mapped[List["DocumentChunkRecord"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    export_jobs: Mapped[List["ExportJobRecord"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'succeeded', 'failed', 'cancelled', 'canceled')",
            name="ck_processing_jobs_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, default="demo-user", index=True)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False, default="process_document")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    document: Mapped[Document] = relationship(back_populates="jobs")


class ParsedSection(Base):
    __tablename__ = "parsed_sections"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    document: Mapped[Document] = relationship(back_populates="sections")


class KnowledgePointRecord(Base):
    __tablename__ = "knowledge_points"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    category: Mapped[Optional[str]] = mapped_column(String(100))
    point_type: Mapped[Optional[str]] = mapped_column(String(100))
    importance: Mapped[Optional[int]] = mapped_column(Integer)

    document: Mapped[Document] = relationship(back_populates="knowledge_points")
    questions: Mapped[List["QuestionRecord"]] = relationship(back_populates="knowledge_point")


class OutlineRecord(Base):
    __tablename__ = "outlines"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    markdown: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    document: Mapped[Document] = relationship(back_populates="outlines")


class DocumentArtifactRecord(Base):
    __tablename__ = "document_artifacts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_metadata: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    document: Mapped[Document] = relationship(back_populates="artifacts")
    chunks: Mapped[List["DocumentChunkRecord"]] = relationship(back_populates="artifact")


class DocumentChunkRecord(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("artifact_id", "chunk_index", name="uq_document_chunks_artifact_index"),
        Index("ix_document_chunks_owner_document", "owner_id", "document_id"),
        Index("ix_document_chunks_document_artifact", "document_id", "artifact_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    artifact_id: Mapped[str] = mapped_column(
        ForeignKey("document_artifacts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(512), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_metadata: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    section_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("parsed_sections.id", ondelete="SET NULL"), nullable=True
    )
    page_number: Mapped[Optional[int]] = mapped_column(Integer)
    embedding: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    document: Mapped[Document] = relationship(back_populates="chunks")
    artifact: Mapped[DocumentArtifactRecord] = relationship(back_populates="chunks")


class ContentVersionRecord(Base):
    __tablename__ = "content_versions"
    __table_args__ = (
        UniqueConstraint(
            "target_type",
            "target_id",
            "version",
            name="uq_content_versions_target_version",
        ),
    )

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    document_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=True, index=True
    )
    target_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    target_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_metadata: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    change_summary: Mapped[str] = mapped_column(Text, nullable=False)


class QuestionRecord(Base):
    __tablename__ = "questions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stem: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[Optional[str]] = mapped_column(Text)
    difficulty: Mapped[Optional[str]] = mapped_column(String(50))
    question_type: Mapped[Optional[str]] = mapped_column(String(100))
    knowledge_point_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="SET NULL"), index=True
    )

    document: Mapped[Document] = relationship(back_populates="questions")
    knowledge_point: Mapped[Optional[KnowledgePointRecord]] = relationship(
        back_populates="questions"
    )


class ExportJobRecord(Base):
    __tablename__ = "export_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("content_versions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    format: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    storage_uri: Mapped[Optional[str]] = mapped_column(String(1024))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    document: Mapped[Document] = relationship(back_populates="export_jobs")


class FeedbackRecord(Base):
    __tablename__ = "feedback"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(128), nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class ReviewTaskRecord(Base):
    __tablename__ = "review_tasks"
    __table_args__ = (
        Index(
            "ix_review_tasks_owner_target_status",
            "owner_id",
            "target_type",
            "target_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    reason: Mapped[str] = mapped_column(String(128), nullable=False)
    assignee: Mapped[Optional[str]] = mapped_column(String(255))
    decision: Mapped[Optional[str]] = mapped_column(String(64))
    comment: Mapped[Optional[str]] = mapped_column(Text)
    task_metadata: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class AuditEventRecord(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_metadata: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class StudyAgentTraceRecord(Base):
    __tablename__ = "study_agent_traces"
    __table_args__ = (
        Index("ix_study_agent_traces_owner_created", "owner_id", "created_at"),
        Index("ix_study_agent_traces_owner_request", "owner_id", "request_id"),
        Index("ix_study_agent_traces_owner_query_hash", "owner_id", "query_hash"),
        Index(
            "ix_study_agent_traces_owner_mode_created",
            "owner_id",
            "selected_mode",
            "created_at",
        ),
        Index("ix_study_agent_traces_review_created", "needs_review", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    query_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    target: Mapped[str] = mapped_column(String(128), nullable=False)
    document_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    selected_mode: Mapped[str] = mapped_column(String(64), nullable=False)
    route_reason: Mapped[Optional[str]] = mapped_column(String(255))
    estimated_cost: Mapped[str] = mapped_column(String(32), nullable=False)
    fallback_chain: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    chunk_source: Mapped[Optional[str]] = mapped_column(String(128))
    fallback_reason: Mapped[Optional[str]] = mapped_column(String(255))
    source_count: Mapped[Optional[int]] = mapped_column(Integer)
    used_chunk_count: Mapped[Optional[int]] = mapped_column(Integer)
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    source_recall: Mapped[Optional[float]] = mapped_column(Float)
    answer_term_recall: Mapped[Optional[float]] = mapped_column(Float)
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    latency_ms: Mapped[Optional[float]] = mapped_column(Float)
    trace_metadata: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class RAGEvaluationRunRecord(Base):
    __tablename__ = "rag_evaluation_runs"
    __table_args__ = (
        Index("ix_rag_eval_runs_created_by_created", "created_by", "created_at"),
        Index("ix_rag_eval_runs_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    fixture_version: Mapped[str] = mapped_column(String(128), nullable=False)
    modes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    case_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    report_uri: Mapped[Optional[str]] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    scores: Mapped[List["RAGEvaluationCaseScoreRecord"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class RAGEvaluationCaseScoreRecord(Base):
    __tablename__ = "rag_evaluation_case_scores"
    __table_args__ = (
        Index("ix_rag_eval_scores_run_mode", "run_id", "mode"),
        Index("ix_rag_eval_scores_run_category", "run_id", "category"),
        Index("ix_rag_eval_scores_mode_category", "mode", "category"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("rag_evaluation_runs.id", ondelete="CASCADE"), nullable=False
    )
    case_id: Mapped[str] = mapped_column(String(128), nullable=False)
    mode: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(128), nullable=False)
    source_recall: Mapped[Optional[float]] = mapped_column(Float)
    answer_term_recall: Mapped[Optional[float]] = mapped_column(Float)
    answer_coverage: Mapped[Optional[float]] = mapped_column(Float)
    latency_ms: Mapped[Optional[float]] = mapped_column(Float)
    estimated_cost: Mapped[Optional[float]] = mapped_column(Float)
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fallback_reason: Mapped[Optional[str]] = mapped_column(String(255))
    error_code: Mapped[Optional[str]] = mapped_column(String(128))

    run: Mapped[RAGEvaluationRunRecord] = relationship(back_populates="scores")
