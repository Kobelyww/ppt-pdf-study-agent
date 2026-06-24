"""Add MVP-8 auth fields and product query indexes.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("name", existing_type=sa.String(length=255), nullable=True)
        batch_op.add_column(sa.Column("password_hash", sa.String(length=255), nullable=True))
        batch_op.add_column(
            sa.Column("role", sa.String(length=32), nullable=False, server_default="user")
        )
        batch_op.add_column(
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch_op.add_column(sa.Column("display_name", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            )
        )

    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_role", "users", ["role"])
    op.create_index("ix_documents_owner_created", "documents", ["owner_id", "created_at"])
    op.create_index(
        "ix_processing_jobs_owner_status_document",
        "processing_jobs",
        ["owner_id", "status", "document_id"],
    )
    op.create_index(
        "ix_content_versions_document_target_version",
        "content_versions",
        ["document_id", "target_type", "version"],
    )
    op.create_index("ix_review_tasks_owner_status", "review_tasks", ["owner_id", "status"])
    op.create_index("ix_review_tasks_assignee_status", "review_tasks", ["assignee", "status"])
    op.create_index(
        "ix_audit_events_resource_created",
        "audit_events",
        ["resource_type", "resource_id", "created_at"],
    )


def downgrade() -> None:
    for index_name, table_name in [
        ("ix_audit_events_resource_created", "audit_events"),
        ("ix_review_tasks_assignee_status", "review_tasks"),
        ("ix_review_tasks_owner_status", "review_tasks"),
        ("ix_content_versions_document_target_version", "content_versions"),
        ("ix_processing_jobs_owner_status_document", "processing_jobs"),
        ("ix_documents_owner_created", "documents"),
        ("ix_users_role", "users"),
        ("ix_users_email", "users"),
    ]:
        op.drop_index(index_name, table_name=table_name)

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("updated_at")
        batch_op.drop_column("last_login_at")
        batch_op.drop_column("display_name")
        batch_op.drop_column("is_active")
        batch_op.drop_column("role")
        batch_op.drop_column("password_hash")
        batch_op.alter_column("name", existing_type=sa.String(length=255), nullable=False)
