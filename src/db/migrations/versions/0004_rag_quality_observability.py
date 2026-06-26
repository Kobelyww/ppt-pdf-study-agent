"""Add RAG quality observability schema.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-26
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "study_agent_traces",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("document_ids", sa.JSON(), nullable=False),
        sa.Column("selected_mode", sa.String(length=64), nullable=False),
        sa.Column("query_hash", sa.String(length=128), nullable=False),
        sa.Column("fallback_chain", sa.JSON(), nullable=False),
        sa.Column("retrieval_latency_ms", sa.Float(), nullable=True),
        sa.Column("generation_latency_ms", sa.Float(), nullable=True),
        sa.Column("total_latency_ms", sa.Float(), nullable=True),
        sa.Column("retrieved_chunk_count", sa.Integer(), nullable=True),
        sa.Column("selected_chunk_count", sa.Integer(), nullable=True),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_study_agent_traces_owner_created",
        "study_agent_traces",
        ["owner_id", "created_at"],
    )
    op.create_index(
        "ix_study_agent_traces_owner_request",
        "study_agent_traces",
        ["owner_id", "request_id"],
    )
    op.create_index(
        "ix_study_agent_traces_owner_query_hash",
        "study_agent_traces",
        ["owner_id", "query_hash"],
    )
    op.create_index(
        "ix_study_agent_traces_owner_mode_created",
        "study_agent_traces",
        ["owner_id", "selected_mode", "created_at"],
    )
    op.create_index(
        "ix_study_agent_traces_review_created",
        "study_agent_traces",
        ["needs_review", "created_at"],
    )

    op.create_table(
        "rag_evaluation_runs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("document_ids", sa.JSON(), nullable=False),
        sa.Column("modes", sa.JSON(), nullable=False),
        sa.Column("case_count", sa.Integer(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("average_relevance", sa.Float(), nullable=True),
        sa.Column("average_groundedness", sa.Float(), nullable=True),
        sa.Column("average_completeness", sa.Float(), nullable=True),
        sa.Column("average_latency_ms", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_rag_eval_runs_created_by_created",
        "rag_evaluation_runs",
        ["created_by", "created_at"],
    )
    op.create_index(
        "ix_rag_eval_runs_status_created",
        "rag_evaluation_runs",
        ["status", "created_at"],
    )

    op.create_table(
        "rag_evaluation_case_scores",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(length=64),
            sa.ForeignKey("rag_evaluation_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("case_id", sa.String(length=128), nullable=False),
        sa.Column("mode", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=128), nullable=False),
        sa.Column("relevance", sa.Float(), nullable=True),
        sa.Column("groundedness", sa.Float(), nullable=True),
        sa.Column("completeness", sa.Float(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("retrieved_chunk_count", sa.Integer(), nullable=True),
        sa.Column("selected_chunk_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_rag_eval_scores_run_mode",
        "rag_evaluation_case_scores",
        ["run_id", "mode"],
    )
    op.create_index(
        "ix_rag_eval_scores_run_category",
        "rag_evaluation_case_scores",
        ["run_id", "category"],
    )
    op.create_index(
        "ix_rag_eval_scores_mode_category",
        "rag_evaluation_case_scores",
        ["mode", "category"],
    )


def downgrade() -> None:
    op.drop_index("ix_rag_eval_scores_mode_category", table_name="rag_evaluation_case_scores")
    op.drop_index("ix_rag_eval_scores_run_category", table_name="rag_evaluation_case_scores")
    op.drop_index("ix_rag_eval_scores_run_mode", table_name="rag_evaluation_case_scores")
    op.drop_table("rag_evaluation_case_scores")

    op.drop_index("ix_rag_eval_runs_status_created", table_name="rag_evaluation_runs")
    op.drop_index("ix_rag_eval_runs_created_by_created", table_name="rag_evaluation_runs")
    op.drop_table("rag_evaluation_runs")

    op.drop_index("ix_study_agent_traces_review_created", table_name="study_agent_traces")
    op.drop_index("ix_study_agent_traces_owner_mode_created", table_name="study_agent_traces")
    op.drop_index("ix_study_agent_traces_owner_query_hash", table_name="study_agent_traces")
    op.drop_index("ix_study_agent_traces_owner_request", table_name="study_agent_traces")
    op.drop_index("ix_study_agent_traces_owner_created", table_name="study_agent_traces")
    op.drop_table("study_agent_traces")
