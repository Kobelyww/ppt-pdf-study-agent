"""Add persistent document chunk compatibility columns.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-26
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


TASK_COLUMNS = {
    "owner_id",
    "artifact_id",
    "chunk_count",
    "source",
    "metadata",
    "content_hash",
    "created_at",
    "updated_at",
}


class Vector(sa.types.UserDefinedType):
    cache_ok = True

    def __init__(self, dim: int | None = None):
        self.dim = dim

    def get_col_spec(self, **kw) -> str:
        if self.dim:
            return f"vector({self.dim})"
        return "vector"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "document_chunks" not in table_names:
        op.create_table(
            "document_chunks",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("owner_id", sa.String(length=64), nullable=False),
            sa.Column(
                "document_id",
                sa.String(length=64),
                sa.ForeignKey("documents.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "artifact_id",
                sa.String(length=64),
                sa.ForeignKey("document_artifacts.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("chunk_index", sa.Integer(), nullable=False),
            sa.Column("chunk_count", sa.Integer(), nullable=False),
            sa.Column("source", sa.String(length=512), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("metadata", sa.JSON(), nullable=False),
            sa.Column("content_hash", sa.String(length=128), nullable=False),
            sa.Column(
                "section_id",
                sa.String(length=64),
                sa.ForeignKey("parsed_sections.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("page_number", sa.Integer(), nullable=True),
            sa.Column("embedding", Vector(dim=768), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "artifact_id", "chunk_index", name="uq_document_chunks_artifact_index"
            ),
        )
    else:
        existing_columns = {column["name"] for column in inspector.get_columns("document_chunks")}
        with op.batch_alter_table("document_chunks") as batch_op:
            if "owner_id" not in existing_columns:
                batch_op.add_column(sa.Column("owner_id", sa.String(length=64), nullable=True))
            if "artifact_id" not in existing_columns:
                batch_op.add_column(sa.Column("artifact_id", sa.String(length=64), nullable=True))
            if "chunk_count" not in existing_columns:
                batch_op.add_column(sa.Column("chunk_count", sa.Integer(), nullable=True))
            if "source" not in existing_columns:
                batch_op.add_column(sa.Column("source", sa.String(length=512), nullable=True))
            if "metadata" not in existing_columns:
                batch_op.add_column(sa.Column("metadata", sa.JSON(), nullable=True))
            if "content_hash" not in existing_columns:
                batch_op.add_column(sa.Column("content_hash", sa.String(length=128), nullable=True))
            if "section_id" not in existing_columns:
                batch_op.add_column(sa.Column("section_id", sa.String(length=64), nullable=True))
            if "page_number" not in existing_columns:
                batch_op.add_column(sa.Column("page_number", sa.Integer(), nullable=True))
            if "created_at" not in existing_columns:
                batch_op.add_column(
                    sa.Column("created_at", sa.DateTime(timezone=True), nullable=True)
                )
            if "updated_at" not in existing_columns:
                batch_op.add_column(
                    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True)
                )
            if "embedding" not in existing_columns:
                batch_op.add_column(sa.Column("embedding", sa.Text(), nullable=True))

        _backfill_legacy_chunks()
        _enforce_required_chunk_columns()
        _deduplicate_legacy_artifact_indexes()
        _create_missing_legacy_artifacts()

    _create_missing_indexes_and_constraints()
    _create_missing_foreign_keys()


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "document_chunks" not in inspector.get_table_names():
        return

    existing_indexes = {index["name"] for index in inspector.get_indexes("document_chunks")}
    for index_name in [
        "uq_document_chunks_artifact_index",
        "ix_document_chunks_document_artifact",
        "ix_document_chunks_owner_document",
        "ix_document_chunks_content_hash",
        "ix_document_chunks_artifact_id",
        "ix_document_chunks_document_id",
        "ix_document_chunks_owner_id",
    ]:
        if index_name in existing_indexes:
            op.drop_index(index_name, table_name="document_chunks")

    existing_constraints = {
        constraint["name"] for constraint in inspector.get_unique_constraints("document_chunks")
    }
    if "uq_document_chunks_artifact_index" in existing_constraints:
        with _batch_document_chunks() as batch_op:
            batch_op.drop_constraint("uq_document_chunks_artifact_index", type_="unique")

    with _batch_document_chunks() as batch_op:
        existing_columns = {column["name"] for column in inspector.get_columns("document_chunks")}
        for column_name in TASK_COLUMNS:
            if column_name in existing_columns:
                batch_op.drop_column(column_name)


def _backfill_legacy_chunks() -> None:
    op.execute(
        sa.text(
            """
            UPDATE document_chunks
            SET
              owner_id = COALESCE(owner_id, 'legacy-owner'),
              artifact_id = COALESCE(artifact_id, 'legacy-artifact:' || substr(id, 1, 48)),
              chunk_count = COALESCE(chunk_count, 1),
              source = COALESCE(source, 'document:' || document_id || ':chunk:' || chunk_index),
              metadata = COALESCE(metadata, '{}'),
              content_hash = COALESCE(content_hash, 'legacy:' || id),
              created_at = COALESCE(created_at, CURRENT_TIMESTAMP),
              updated_at = COALESCE(updated_at, CURRENT_TIMESTAMP)
            """
        )
    )


def _deduplicate_legacy_artifact_indexes() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT artifact_id, chunk_index, id
            FROM document_chunks
            ORDER BY artifact_id, chunk_index, id
            """
        )
    ).mappings()
    seen: set[tuple[str, int]] = set()
    for row in rows:
        key = (row["artifact_id"], row["chunk_index"])
        if key in seen:
            bind.execute(
                sa.text(
                    """
                    UPDATE document_chunks
                    SET artifact_id = :artifact_id
                    WHERE id = :id
                    """
                ),
                {"artifact_id": f"legacy-artifact:{row['id'][:48]}", "id": row["id"]},
            )
        else:
            seen.add(key)


def _create_missing_legacy_artifacts() -> None:
    bind = op.get_bind()
    if "document_artifacts" not in sa.inspect(bind).get_table_names():
        return

    bind.execute(
        sa.text(
            """
            INSERT INTO document_artifacts (id, document_id, artifact_type, content, metadata, created_at)
            SELECT DISTINCT
              dc.artifact_id,
              dc.document_id,
              'legacy_document_chunk',
              '',
              '{}',
              CURRENT_TIMESTAMP
            FROM document_chunks dc
            LEFT JOIN document_artifacts da ON da.id = dc.artifact_id
            WHERE da.id IS NULL
              AND dc.artifact_id IS NOT NULL
              AND EXISTS (
                SELECT 1 FROM documents d WHERE d.id = dc.document_id
              )
            """
        )
    )


def _enforce_required_chunk_columns() -> None:
    bind = op.get_bind()
    existing_columns = {column["name"] for column in sa.inspect(bind).get_columns("document_chunks")}
    with _batch_document_chunks() as batch_op:
        for column_name, column_type in [
            ("owner_id", sa.String(length=64)),
            ("artifact_id", sa.String(length=64)),
            ("chunk_count", sa.Integer()),
            ("source", sa.String(length=512)),
            ("metadata", sa.JSON()),
            ("content_hash", sa.String(length=128)),
            ("created_at", sa.DateTime(timezone=True)),
            ("updated_at", sa.DateTime(timezone=True)),
        ]:
            if column_name in existing_columns:
                batch_op.alter_column(
                    column_name,
                    existing_type=column_type,
                    nullable=False,
                )


def _create_missing_indexes_and_constraints() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_indexes = {index["name"] for index in inspector.get_indexes("document_chunks")}
    for index_name, columns in [
        ("ix_document_chunks_owner_id", ["owner_id"]),
        ("ix_document_chunks_document_id", ["document_id"]),
        ("ix_document_chunks_artifact_id", ["artifact_id"]),
        ("ix_document_chunks_content_hash", ["content_hash"]),
        ("ix_document_chunks_owner_document", ["owner_id", "document_id"]),
        ("ix_document_chunks_document_artifact", ["document_id", "artifact_id"]),
    ]:
        if index_name not in existing_indexes:
            op.create_index(index_name, "document_chunks", columns)

    existing_constraints = {
        constraint["name"] for constraint in inspector.get_unique_constraints("document_chunks")
    }
    if "uq_document_chunks_artifact_index" not in existing_constraints:
        with _batch_document_chunks() as batch_op:
            batch_op.create_unique_constraint(
                "uq_document_chunks_artifact_index",
                ["artifact_id", "chunk_index"],
            )


def _create_missing_foreign_keys() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    foreign_keys = inspector.get_foreign_keys("document_chunks")
    has_artifact_fk = any(
        fk["referred_table"] == "document_artifacts"
        and fk["constrained_columns"] == ["artifact_id"]
        for fk in foreign_keys
    )
    if not has_artifact_fk:
        with _batch_document_chunks() as batch_op:
            batch_op.create_foreign_key(
                "fk_document_chunks_artifact_id_document_artifacts",
                "document_artifacts",
                ["artifact_id"],
                ["id"],
                ondelete="CASCADE",
            )


def _batch_document_chunks():
    return op.batch_alter_table(
        "document_chunks",
        reflect_args=[sa.Column("embedding", Vector(dim=768), nullable=True)],
    )
