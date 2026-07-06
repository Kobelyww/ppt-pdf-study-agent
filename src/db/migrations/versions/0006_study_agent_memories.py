"""Add study agent memory schema.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-06
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "study_agent_memories",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("scope_id", sa.String(length=128), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("privacy_level", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_study_agent_memories_owner_category",
        "study_agent_memories",
        ["owner_id", "category"],
    )
    op.create_index(
        "ix_study_agent_memories_owner_scope",
        "study_agent_memories",
        ["owner_id", "scope_type", "scope_id"],
    )
    op.create_index(
        "ix_study_agent_memories_owner_key",
        "study_agent_memories",
        ["owner_id", "category", "key"],
    )


def downgrade() -> None:
    op.drop_index("ix_study_agent_memories_owner_key", table_name="study_agent_memories")
    op.drop_index("ix_study_agent_memories_owner_scope", table_name="study_agent_memories")
    op.drop_index(
        "ix_study_agent_memories_owner_category",
        table_name="study_agent_memories",
    )
    op.drop_table("study_agent_memories")
