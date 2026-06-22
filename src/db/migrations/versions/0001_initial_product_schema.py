"""Initial product schema with pgvector-compatible chunks.

Revision ID: 0001
Revises:
Create Date: 2026-06-15
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


class Vector(sa.types.UserDefinedType):
    cache_ok = True

    def __init__(self, dim: int | None = None):
        self.dim = dim

    def get_col_spec(self, **kw) -> str:
        if self.dim:
            return f"vector({self.dim})"
        return "vector"


def _enable_pgvector() -> None:
    bind = op.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        op.execute('CREATE EXTENSION IF NOT EXISTS "vector"')


def upgrade() -> None:
    _enable_pgvector()

    op.create_table(
        "users",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False, unique=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "documents",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=64), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("storage_uri", sa.String(length=1024), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_documents_owner_id", "documents", ["owner_id"])
    op.create_index("ix_documents_content_hash", "documents", ["content_hash"])
    op.create_table(
        "processing_jobs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(length=64),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'succeeded', 'failed', 'cancelled', 'canceled')",
            name="ck_processing_jobs_status",
        ),
    )
    op.create_index("ix_processing_jobs_document_id", "processing_jobs", ["document_id"])
    op.create_index("ix_processing_jobs_owner_id", "processing_jobs", ["owner_id"])
    op.create_table(
        "parsed_sections",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(length=64),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
    )
    op.create_index("ix_parsed_sections_document_id", "parsed_sections", ["document_id"])
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(length=64),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "section_id",
            sa.String(length=64),
            sa.ForeignKey("parsed_sections.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(dim=768), nullable=True),
    )
    op.create_table(
        "document_assets",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(length=64),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("asset_type", sa.String(length=64), nullable=False),
        sa.Column("storage_uri", sa.String(length=1024), nullable=True),
        sa.Column("caption", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
    )
    op.create_table(
        "source_spans",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(length=64),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "section_id",
            sa.String(length=64),
            sa.ForeignKey("parsed_sections.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "chunk_id",
            sa.String(length=64),
            sa.ForeignKey("document_chunks.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("bbox", sa.JSON(), nullable=True),
        sa.Column("char_start", sa.Integer(), nullable=True),
        sa.Column("char_end", sa.Integer(), nullable=True),
    )
    op.create_table(
        "knowledge_points",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(length=64),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("point_type", sa.String(length=100), nullable=True),
        sa.Column("importance", sa.Integer(), nullable=True),
    )
    op.create_index("ix_knowledge_points_document_id", "knowledge_points", ["document_id"])
    op.create_table(
        "knowledge_relations",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "source_id",
            sa.String(length=64),
            sa.ForeignKey("knowledge_points.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_id",
            sa.String(length=64),
            sa.ForeignKey("knowledge_points.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relation_type", sa.String(length=100), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
    )
    op.create_table(
        "outlines",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(length=64),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_outlines_document_id", "outlines", ["document_id"])
    op.create_table(
        "questions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(length=64),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "knowledge_point_id",
            sa.String(length=64),
            sa.ForeignKey("knowledge_points.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("stem", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("difficulty", sa.String(length=50), nullable=True),
        sa.Column("question_type", sa.String(length=100), nullable=True),
    )
    op.create_index("ix_questions_document_id", "questions", ["document_id"])
    op.create_index("ix_questions_knowledge_point_id", "questions", ["knowledge_point_id"])
    op.create_table(
        "qa_sessions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(length=64),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "document_id",
            sa.String(length=64),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "qa_messages",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(length=64),
            sa.ForeignKey("qa_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "feedback",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(length=64),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=128), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "document_artifacts",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(length=64),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("artifact_type", sa.String(length=64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_document_artifacts_document_id", "document_artifacts", ["document_id"])
    op.create_table(
        "content_versions",
        sa.Column("id", sa.String(length=255), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(length=64),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("target_type", sa.String(length=100), nullable=False),
        sa.Column("target_id", sa.String(length=255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("change_summary", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "target_type",
            "target_id",
            "version",
            name="uq_content_versions_target_version",
        ),
    )
    op.create_index("ix_content_versions_document_id", "content_versions", ["document_id"])
    op.create_index("ix_content_versions_target_type", "content_versions", ["target_type"])
    op.create_index("ix_content_versions_target_id", "content_versions", ["target_id"])
    op.create_table(
        "export_jobs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(length=64),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column(
            "version_id",
            sa.String(length=64),
            sa.ForeignKey("content_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("format", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("storage_uri", sa.String(length=1024), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_export_jobs_document_id", "export_jobs", ["document_id"])
    op.create_index("ix_export_jobs_owner_id", "export_jobs", ["owner_id"])
    op.create_index("ix_export_jobs_version_id", "export_jobs", ["version_id"])
    op.create_table(
        "export_files",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "export_job_id",
            sa.String(length=64),
            sa.ForeignKey("export_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("storage_uri", sa.String(length=1024), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "quality_scores",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=False),
        sa.Column("metric", sa.String(length=100), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "review_tasks",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=128), nullable=False),
        sa.Column("assignee", sa.String(length=255), nullable=True),
        sa.Column("decision", sa.String(length=64), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("actor_id", sa.String(length=64), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_events_actor_id", "audit_events", ["actor_id"])


def downgrade() -> None:
    for index_name, table_name in [
        ("ix_audit_events_actor_id", "audit_events"),
        ("ix_export_jobs_version_id", "export_jobs"),
        ("ix_export_jobs_owner_id", "export_jobs"),
        ("ix_export_jobs_document_id", "export_jobs"),
        ("ix_questions_knowledge_point_id", "questions"),
        ("ix_questions_document_id", "questions"),
        ("ix_outlines_document_id", "outlines"),
        ("ix_content_versions_document_id", "content_versions"),
        ("ix_content_versions_target_id", "content_versions"),
        ("ix_content_versions_target_type", "content_versions"),
        ("ix_document_artifacts_document_id", "document_artifacts"),
        ("ix_knowledge_points_document_id", "knowledge_points"),
        ("ix_parsed_sections_document_id", "parsed_sections"),
        ("ix_processing_jobs_owner_id", "processing_jobs"),
        ("ix_processing_jobs_document_id", "processing_jobs"),
        ("ix_documents_content_hash", "documents"),
        ("ix_documents_owner_id", "documents"),
    ]:
        op.drop_index(index_name, table_name=table_name)

    for table_name in [
        "audit_events",
        "audit_logs",
        "review_tasks",
        "quality_scores",
        "export_files",
        "export_jobs",
        "content_versions",
        "document_artifacts",
        "feedback",
        "qa_messages",
        "qa_sessions",
        "questions",
        "outlines",
        "knowledge_relations",
        "knowledge_points",
        "source_spans",
        "document_assets",
        "document_chunks",
        "parsed_sections",
        "processing_jobs",
        "documents",
        "users",
    ]:
        op.drop_table(table_name)
