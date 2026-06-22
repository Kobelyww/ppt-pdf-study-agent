from fastapi.testclient import TestClient

from src.api.app import create_app
from src.observability.health import HealthCheckService
from src.observability.request_context import RequestContext


def test_request_context_generates_request_id():
    context = RequestContext.from_headers({})

    assert context.request_id.startswith("req_")


def test_request_context_uses_forwarded_headers():
    context = RequestContext.from_headers({"x-request-id": "req-existing", "x-user-id": "user-1"})

    assert context.request_id == "req-existing"
    assert context.user_id == "user-1"


def test_health_check_reports_component_statuses():
    service = HealthCheckService()
    report = service.check({"database": True, "queue": False, "object_storage": True})

    assert report["status"] == "degraded"
    assert report["components"]["queue"] == "unavailable"


def test_health_route_reports_api_components_available():
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "components": {
            "api": "available",
            "database": "available",
            "queue": "available",
        },
    }
