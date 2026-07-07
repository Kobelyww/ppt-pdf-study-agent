"""Add study agent run lifecycle schema.

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-07
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "study_agent_runs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("query_hash", sa.String(length=128), nullable=False),
        sa.Column("target", sa.String(length=128), nullable=False),
        sa.Column("document_ids", sa.JSON(), nullable=False),
        sa.Column("preferred_mode", sa.String(length=64), nullable=True),
        sa.Column("selected_mode", sa.String(length=64), nullable=True),
        sa.Column("budget", sa.String(length=32), nullable=True),
        sa.Column("skill_name", sa.String(length=128), nullable=True),
        sa.Column("skill_version", sa.String(length=64), nullable=True),
        sa.Column("expected_term_count", sa.Integer(), nullable=False),
        sa.Column("workflow_id", sa.String(length=128), nullable=True),
        sa.Column("trace_id", sa.String(length=128), nullable=True),
        sa.Column("review_task_id", sa.String(length=128), nullable=True),
        sa.Column("retry_of_run_id", sa.String(length=64), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("result_summary", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.String(length=255), nullable=True),
        sa.Column("lifecycle_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'paused', 'completed', 'needs_review', "
            "'failed', 'cancelled', 'timed_out', 'archived')",
            name="ck_study_agent_runs_status",
        ),
    )
    op.create_index(
        "ix_study_agent_runs_owner_created",
        "study_agent_runs",
        ["owner_id", "created_at"],
    )
    op.create_index(
        "ix_study_agent_runs_owner_status_created",
        "study_agent_runs",
        ["owner_id", "status", "created_at"],
    )
    op.create_index(
        "ix_study_agent_runs_owner_request",
        "study_agent_runs",
        ["owner_id", "request_id"],
    )
    op.create_index(
        "ix_study_agent_runs_owner_retry",
        "study_agent_runs",
        ["owner_id", "retry_of_run_id"],
    )
    op.create_index("ix_study_agent_runs_workflow", "study_agent_runs", ["workflow_id"])
    op.create_index("ix_study_agent_runs_trace", "study_agent_runs", ["trace_id"])


def downgrade() -> None:
    op.drop_index("ix_study_agent_runs_trace", table_name="study_agent_runs")
    op.drop_index("ix_study_agent_runs_workflow", table_name="study_agent_runs")
    op.drop_index("ix_study_agent_runs_owner_retry", table_name="study_agent_runs")
    op.drop_index("ix_study_agent_runs_owner_request", table_name="study_agent_runs")
    op.drop_index(
        "ix_study_agent_runs_owner_status_created",
        table_name="study_agent_runs",
    )
    op.drop_index("ix_study_agent_runs_owner_created", table_name="study_agent_runs")
    op.drop_table("study_agent_runs")
