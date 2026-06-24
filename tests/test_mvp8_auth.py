import pytest

from src.security.auth import (
    AuthenticatedUser,
    create_access_token,
    hash_password,
    verify_access_token,
    verify_password,
)


def test_password_hash_round_trip():
    hashed = hash_password("correct horse battery staple")

    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong", hashed)


def test_access_token_round_trip():
    token = create_access_token(
        AuthenticatedUser(
            id="user-1",
            email="one@example.com",
            role="admin",
            is_active=True,
        ),
        secret_key="secret",
    )

    user = verify_access_token(token, secret_key="secret")

    assert user.id == "user-1"
    assert user.email == "one@example.com"
    assert user.role == "admin"


def test_access_token_rejects_tampered_signature():
    token = create_access_token(
        AuthenticatedUser(
            id="user-1",
            email="one@example.com",
            role="user",
            is_active=True,
        ),
        secret_key="secret",
    )
    header, payload, signature = token.split(".")
    replacement = "x" if signature[0] != "x" else "y"
    tampered = f"{header}.{payload}.{replacement}{signature[1:]}"

    with pytest.raises(ValueError):
        verify_access_token(tampered, secret_key="secret")


def test_access_token_rejects_expired_token(monkeypatch):
    token = create_access_token(
        AuthenticatedUser(
            id="user-1",
            email="one@example.com",
            role="user",
            is_active=True,
        ),
        secret_key="secret",
        expires_minutes=-1,
    )

    with pytest.raises(ValueError):
        verify_access_token(token, secret_key="secret")
