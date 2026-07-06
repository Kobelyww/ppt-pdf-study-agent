"""Add review task metadata schema.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-06
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("review_tasks") as batch_op:
        batch_op.add_column(
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )

    op.create_index(
        "ix_review_tasks_owner_target_status",
        "review_tasks",
        ["owner_id", "target_type", "target_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_review_tasks_owner_target_status", table_name="review_tasks")

    with op.batch_alter_table("review_tasks") as batch_op:
        batch_op.drop_column("metadata")
