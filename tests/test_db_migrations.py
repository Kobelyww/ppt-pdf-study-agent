from pathlib import Path
import sys
from datetime import datetime, timezone

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.config import RAGConfig
from src.db.models import ContentVersionRecord


ROOT = Path(__file__).resolve().parents[1]


def test_alembic_config_points_to_migration_package():
    config = (ROOT / "alembic.ini").read_text(encoding="utf-8")
    env = (ROOT / "src/db/migrations/env.py").read_text(encoding="utf-8")

    assert "script_location = src/db/migrations" in config
    assert (
        "sqlalchemy.url = "
        "postgresql+psycopg://study_agent:study_agent@localhost:5432/study_agent"
    ) in config
    assert "STUDY_AGENT_DATABASE_URL" in env


def test_initial_migration_defines_core_tables_and_pgvector_embedding():
    migration = next((ROOT / "src/db/migrations/versions").glob("*_initial_product_schema.py"))
    content = migration.read_text(encoding="utf-8")

    for table_name in [
        "users",
        "documents",
        "processing_jobs",
        "parsed_sections",
        "document_chunks",
        "document_assets",
        "source_spans",
        "knowledge_points",
        "knowledge_relations",
        "outlines",
        "questions",
        "qa_sessions",
        "qa_messages",
        "feedback",
        "content_versions",
        "export_jobs",
        "export_files",
        "quality_scores",
        "review_tasks",
        "audit_logs",
        "audit_events",
    ]:
        assert "op.create_table(" in content
        assert f'"{table_name}"' in content

    assert 'CREATE EXTENSION IF NOT EXISTS "vector"' in content
    assert '"embedding", Vector(dim=768)' in content
    assert 'sa.ForeignKey("documents.id", ondelete="CASCADE")' in content
    assert 'sa.ForeignKey("knowledge_points.id", ondelete="SET NULL")' in content
    assert RAGConfig().embedding_dim == 768


def test_docker_compose_defines_postgres_with_pgvector():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "postgres:" in compose
    assert "pgvector/pgvector" in compose
    assert "POSTGRES_DB: study_agent" in compose


def test_alembic_upgrade_creates_orm_compatible_sqlite_schema(tmp_path, monkeypatch):
    database_path = tmp_path / "migration.db"
    database_url = f"sqlite:///{database_path}"
    monkeypatch.setenv("STUDY_AGENT_DATABASE_URL", database_url)

    _run_alembic("upgrade", "head")

    engine = create_engine(database_url)
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("documents")}
    job_columns = {column["name"] for column in inspector.get_columns("processing_jobs")}
    content_version_columns = {
        column["name"] for column in inspector.get_columns("content_versions")
    }
    artifact_columns = {column["name"] for column in inspector.get_columns("document_artifacts")}
    audit_event_columns = {column["name"] for column in inspector.get_columns("audit_events")}
    chunk_columns = {column["name"]: column for column in inspector.get_columns("document_chunks")}
    review_task_columns = {
        column["name"] for column in inspector.get_columns("review_tasks")
    }
    trace_columns = {
        column["name"] for column in inspector.get_columns("study_agent_traces")
    }
    eval_run_columns = {
        column["name"] for column in inspector.get_columns("rag_evaluation_runs")
    }
    eval_score_columns = {
        column["name"] for column in inspector.get_columns("rag_evaluation_case_scores")
    }
    question_fks = inspector.get_foreign_keys("questions")

    assert {"id", "owner_id", "title", "source_type", "storage_uri", "content_hash", "status", "updated_at"}.issubset(columns)
    assert {"owner_id", "job_type", "status", "progress", "error_message", "started_at", "completed_at", "created_at", "updated_at"}.issubset(job_columns)
    assert {"document_id", "metadata"}.issubset(content_version_columns)
    assert {"document_id", "metadata"}.issubset(artifact_columns)
    assert {"actor_id", "metadata"}.issubset(audit_event_columns)
    assert {"owner_id", "target_type", "target_id", "status", "metadata"}.issubset(
        review_task_columns
    )
    assert {
        "id",
        "owner_id",
        "document_id",
        "artifact_id",
        "chunk_index",
        "chunk_count",
        "source",
        "content",
        "metadata",
        "content_hash",
        "created_at",
        "updated_at",
        "section_id",
        "page_number",
        "embedding",
    }.issubset(chunk_columns)
    chunk_indexes = {index["name"] for index in inspector.get_indexes("document_chunks")}
    assert "ix_document_chunks_owner_document" in chunk_indexes
    assert "ix_document_chunks_document_artifact" in chunk_indexes
    assert {
        "id",
        "owner_id",
        "request_id",
        "query_hash",
        "target",
        "document_ids",
        "selected_mode",
        "route_reason",
        "estimated_cost",
        "fallback_chain",
        "chunk_source",
        "fallback_reason",
        "source_count",
        "used_chunk_count",
        "confidence",
        "source_recall",
        "answer_term_recall",
        "needs_review",
        "latency_ms",
        "metadata",
        "created_at",
    }.issubset(trace_columns)
    assert {
        "id",
        "created_by",
        "fixture_version",
        "modes",
        "case_count",
        "status",
        "summary",
        "report_uri",
        "created_at",
        "completed_at",
    }.issubset(eval_run_columns)
    assert {
        "id",
        "run_id",
        "case_id",
        "mode",
        "category",
        "source_recall",
        "answer_term_recall",
        "answer_coverage",
        "latency_ms",
        "estimated_cost",
        "needs_review",
        "fallback_reason",
        "error_code",
    }.issubset(eval_score_columns)
    trace_indexes = {index["name"] for index in inspector.get_indexes("study_agent_traces")}
    review_task_indexes = {index["name"] for index in inspector.get_indexes("review_tasks")}
    eval_run_indexes = {index["name"] for index in inspector.get_indexes("rag_evaluation_runs")}
    eval_score_indexes = {
        index["name"] for index in inspector.get_indexes("rag_evaluation_case_scores")
    }
    assert {
        "ix_study_agent_traces_owner_created",
        "ix_study_agent_traces_owner_request",
        "ix_study_agent_traces_owner_query_hash",
        "ix_study_agent_traces_owner_mode_created",
        "ix_study_agent_traces_review_created",
    }.issubset(trace_indexes)
    assert "ix_review_tasks_owner_target_status" in review_task_indexes
    assert {
        "ix_rag_eval_runs_created_by_created",
        "ix_rag_eval_runs_status_created",
    }.issubset(eval_run_indexes)
    assert {
        "ix_rag_eval_scores_run_mode",
        "ix_rag_eval_scores_run_category",
        "ix_rag_eval_scores_mode_category",
    }.issubset(eval_score_indexes)
    chunk_unique_constraints = {
        constraint["name"] for constraint in inspector.get_unique_constraints("document_chunks")
    }
    assert "uq_document_chunks_artifact_index" in chunk_unique_constraints
    assert any(
        fk["referred_table"] == "knowledge_points" and fk["options"].get("ondelete") == "SET NULL"
        for fk in question_fks
    )

    with engine.connect() as connection:
        chunk_schema = (
            connection.execute(text("PRAGMA table_info(document_chunks)")).mappings().all()
        )

    embedding_column = next(row for row in chunk_schema if row["name"] == "embedding")
    assert embedding_column["type"].lower() == "vector(768)"

    with Session(engine) as session:
        session.add(
            ContentVersionRecord(
                id="outline:outline-1:v1",
                target_type="outline",
                target_id="outline-1",
                version=1,
                content="# Outline",
                created_by="system",
                created_at=datetime.now(timezone.utc),
                change_summary="initial",
            )
        )
        session.commit()

    with Session(engine) as session:
        record = session.get(ContentVersionRecord, "outline:outline-1:v1")
        assert record is not None
        assert record.created_at is not None

        session.add(
            ContentVersionRecord(
                id="duplicate-id",
                target_type="outline",
                target_id="outline-1",
                version=1,
                content="# Duplicate",
                created_by="system",
                created_at=datetime.now(timezone.utc),
                change_summary="duplicate",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()

    _run_alembic("downgrade", "base")

    inspector = inspect(engine)
    assert "documents" not in inspector.get_table_names()


def test_alembic_upgrade_reconciles_existing_document_chunks_table(tmp_path, monkeypatch):
    database_path = tmp_path / "legacy_chunks.db"
    database_url = f"sqlite:///{database_path}"
    monkeypatch.setenv("STUDY_AGENT_DATABASE_URL", database_url)
    legacy_document_id = "d" * 64

    _run_alembic("upgrade", "0002")

    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO documents (
                    id, owner_id, title, source_type, storage_uri, content_hash,
                    status, created_at, updated_at
                )
                VALUES (
                    :document_id, 'legacy-owner', 'Legacy Notes', 'pdf',
                    'local://legacy.pdf', 'sha256:legacy', 'uploaded',
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """
            ),
            {"document_id": legacy_document_id},
        )
        connection.execute(text("DROP TABLE document_chunks"))
        connection.execute(
            text(
                """
                CREATE TABLE document_chunks (
                    id VARCHAR(64) PRIMARY KEY,
                    document_id VARCHAR(64) NOT NULL,
                    content TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    embedding vector(768)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO document_chunks (id, document_id, content, chunk_index)
                VALUES ('chunk-legacy-1', :document_id, 'legacy content', 0)
                """
            ),
            {"document_id": legacy_document_id},
        )

    _run_alembic("upgrade", "0003")

    inspector = inspect(engine)
    chunk_columns = {column["name"]: column for column in inspector.get_columns("document_chunks")}
    assert {
        "id",
        "owner_id",
        "document_id",
        "artifact_id",
        "chunk_index",
        "chunk_count",
        "source",
        "content",
        "metadata",
        "content_hash",
        "created_at",
        "updated_at",
        "section_id",
        "page_number",
        "embedding",
    }.issubset(chunk_columns)

    chunk_indexes = {index["name"] for index in inspector.get_indexes("document_chunks")}
    assert "ix_document_chunks_owner_document" in chunk_indexes
    assert "ix_document_chunks_document_artifact" in chunk_indexes

    chunk_unique_constraints = {
        constraint["name"] for constraint in inspector.get_unique_constraints("document_chunks")
    }
    assert "uq_document_chunks_artifact_index" in chunk_unique_constraints
    chunk_foreign_keys = inspector.get_foreign_keys("document_chunks")
    assert any(
        fk["referred_table"] == "document_artifacts"
        and fk["constrained_columns"] == ["artifact_id"]
        for fk in chunk_foreign_keys
    )

    with engine.connect() as connection:
        legacy_row = (
            connection.execute(
                text(
                    """
                    SELECT owner_id, artifact_id, chunk_count, source, metadata,
                           content_hash, created_at, updated_at, section_id, page_number
                    FROM document_chunks
                    WHERE id = 'chunk-legacy-1'
                    """
                )
            )
            .mappings()
            .one()
        )
        embedding_column = (
            connection.execute(text("PRAGMA table_info(document_chunks)")).mappings().all()
        )

    assert legacy_row["owner_id"] == "legacy-owner"
    assert len(legacy_row["artifact_id"]) <= 64
    assert legacy_row["artifact_id"].startswith("legacy-artifact:")
    assert legacy_row["chunk_count"] == 1
    assert legacy_row["source"] == f"document:{legacy_document_id}:chunk:0"
    assert legacy_row["metadata"] == "{}"
    assert legacy_row["content_hash"] == "legacy:chunk-legacy-1"
    assert legacy_row["created_at"] is not None
    assert legacy_row["updated_at"] is not None
    assert legacy_row["section_id"] is None
    assert legacy_row["page_number"] is None
    assert next(row for row in embedding_column if row["name"] == "embedding")[
        "type"
    ].lower() == "vector(768)"


def test_database_url_fallback_is_used_when_study_agent_url_is_absent(tmp_path, monkeypatch):
    fallback_database = tmp_path / "fallback.db"
    fallback_url = f"sqlite:///{fallback_database}"
    monkeypatch.delenv("STUDY_AGENT_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", fallback_url)

    _run_alembic("upgrade", "head")

    engine = create_engine(fallback_url)
    assert "documents" in inspect(engine).get_table_names()


def test_study_agent_database_url_takes_precedence(tmp_path, monkeypatch):
    preferred_database = tmp_path / "preferred.db"
    fallback_database = tmp_path / "fallback.db"
    monkeypatch.setenv("STUDY_AGENT_DATABASE_URL", f"sqlite:///{preferred_database}")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{fallback_database}")

    _run_alembic("upgrade", "head")

    preferred_engine = create_engine(f"sqlite:///{preferred_database}")
    assert "documents" in inspect(preferred_engine).get_table_names()
    assert not fallback_database.exists()


def _run_alembic(action: str, revision: str) -> None:
    sys.dont_write_bytecode = True
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "src/db/migrations"))
    getattr(command, action)(config, revision)
