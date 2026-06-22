from datetime import datetime, timezone

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.services.export_service import ExportFormat, ExportService
from src.services.version_service import ContentVersion


def test_export_service_creates_markdown_export_job():
    version = ContentVersion(
        id="outline:outline-1:v1",
        target_type="outline",
        target_id="outline-1",
        version=1,
        content="# Outline\n\nSource: p.1",
        created_by="system",
        created_at=datetime.now(timezone.utc),
        change_summary="initial",
    )

    job = ExportService().create_export(
        document_id="doc-1",
        version=version,
        export_format=ExportFormat.MARKDOWN,
    )

    assert job.status == "queued"
    assert job.format == ExportFormat.MARKDOWN
    assert job.version_id == version.id


def test_post_export_creates_export_job():
    client = TestClient(create_app())

    response = client.post(
        "/api/exports/doc-1",
        json={
            "version_id": "outline:outline-1:v1",
            "format": "markdown",
            "content": "# Outline",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": "export:doc-1:outline:outline-1:v1:markdown",
        "status": "queued",
        "format": "markdown",
    }
