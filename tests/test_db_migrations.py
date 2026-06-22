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
    question_fks = inspector.get_foreign_keys("questions")

    assert {"id", "owner_id", "title", "source_type", "storage_uri", "content_hash", "status", "updated_at"}.issubset(columns)
    assert {"owner_id", "job_type", "status", "progress", "error_message", "started_at", "completed_at", "created_at", "updated_at"}.issubset(job_columns)
    assert {"document_id", "metadata"}.issubset(content_version_columns)
    assert {"document_id", "metadata"}.issubset(artifact_columns)
    assert {"actor_id", "metadata"}.issubset(audit_event_columns)
    assert "embedding" in chunk_columns
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
