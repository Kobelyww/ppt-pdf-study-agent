from src.security.audit import AuditLogger
from src.security.permissions import PermissionService, Resource


def test_permission_service_allows_owner_export():
    resource = Resource(
        resource_type="document",
        resource_id="doc-1",
        owner_id="user-1",
    )

    assert PermissionService().can(
        actor_id="user-1",
        action="export",
        resource=resource,
    )
    assert not PermissionService().can(
        actor_id="user-2",
        action="export",
        resource=resource,
    )
    assert not PermissionService().can(
        actor_id="user-1",
        action="unknown_action",
        resource=resource,
    )


def test_audit_logger_records_key_event_without_sensitive_content():
    logger = AuditLogger()

    event = logger.record(
        actor_id="user-1",
        action="export",
        resource_type="document",
        resource_id="doc-1",
        request_id="req-1",
        metadata={"filename": "notes.pdf", "api_key": "secret"},
    )

    assert event.action == "export"
    assert "api_key" not in event.metadata


def test_audit_logger_recursively_removes_sensitive_metadata_variants():
    logger = AuditLogger()

    event = logger.record(
        actor_id="user-1",
        action="export",
        resource_type="document",
        resource_id="doc-1",
        request_id="req-1",
        metadata={
            "apiKey": "secret",
            "access_token": "secret",
            "refresh-token": "secret",
            "client_secret_value": "secret",
            "password": "secret",
            "filename": "notes.pdf",
            "headers": {
                "Authorization": "Bearer secret",
                "Accept": "application/json",
            },
            "items": [
                {"content": "sensitive"},
                {"page": 1},
            ],
        },
    )

    assert event.metadata == {
        "filename": "notes.pdf",
        "headers": {"Accept": "application/json"},
        "items": [{"page": 1}],
    }


def test_audit_logger_keeps_metadata_dict_when_all_keys_are_sensitive():
    logger = AuditLogger()

    event = logger.record(
        actor_id="user-1",
        action="export",
        resource_type="document",
        resource_id="doc-1",
        request_id="req-1",
        metadata={"apiKey": "secret", "token": "secret"},
    )

    assert event.metadata == {}
