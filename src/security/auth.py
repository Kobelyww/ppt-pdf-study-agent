from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


_PASSWORD_ALGORITHM = "pbkdf2_sha256"
_PASSWORD_ITERATIONS = 600_000
_LEGACY_PASSWORD_ITERATIONS = 120_000
_JWT_ALGORITHM = "HS256"
_INVALID_TOKEN_ERROR = "Invalid access token"


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    email: str
    role: str
    is_active: bool


def hash_password(password: str) -> str:
    salt = secrets.token_urlsafe(16)
    digest = _password_digest(password, salt, _PASSWORD_ITERATIONS)
    return f"{_PASSWORD_ALGORITHM}${_PASSWORD_ITERATIONS}${salt}${_base64url_encode(digest)}"


def verify_password(password: str, password_hash: str) -> bool:
    parts = password_hash.split("$")
    if len(parts) == 4:
        algorithm, iterations_value, salt, encoded_digest = parts
        try:
            iterations = int(iterations_value)
        except ValueError:
            return False
    elif len(parts) == 3:
        algorithm, salt, encoded_digest = parts
        iterations = _LEGACY_PASSWORD_ITERATIONS
    else:
        return False
    if algorithm != _PASSWORD_ALGORITHM or iterations <= 0 or not salt or not encoded_digest:
        return False
    try:
        expected_digest = _base64url_decode(encoded_digest)
    except ValueError:
        return False
    actual_digest = _password_digest(password, salt, iterations)
    return hmac.compare_digest(actual_digest, expected_digest)


def create_access_token(
    user: AuthenticatedUser,
    *,
    secret_key: str,
    expires_minutes: int = 30,
) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    header = {"alg": _JWT_ALGORITHM, "typ": "JWT"}
    payload = {
        "sub": user.id,
        "email": user.email,
        "role": user.role,
        "exp": int(expires_at.timestamp()),
    }
    signing_input = ".".join([_base64url_json(header), _base64url_json(payload)])
    signature = _sign(signing_input, secret_key)
    return f"{signing_input}.{_base64url_encode(signature)}"


def verify_access_token(token: str, *, secret_key: str) -> AuthenticatedUser:
    try:
        header_segment, payload_segment, signature_segment = token.split(".")
        signing_input = f"{header_segment}.{payload_segment}"
        header = _json_from_base64url(header_segment)
        payload = _json_from_base64url(payload_segment)
        signature = _base64url_decode(signature_segment)
        if header.get("alg") != _JWT_ALGORITHM:
            raise ValueError
        if not hmac.compare_digest(signature, _sign(signing_input, secret_key)):
            raise ValueError
        if int(payload["exp"]) < int(datetime.now(timezone.utc).timestamp()):
            raise ValueError
        user_id = _required_string_claim(payload, "sub")
        email = _required_string_claim(payload, "email")
        role = _required_string_claim(payload, "role")
    except (
        KeyError,
        TypeError,
        ValueError,
        binascii.Error,
        json.JSONDecodeError,
        UnicodeDecodeError,
    ):
        raise ValueError(_INVALID_TOKEN_ERROR) from None
    return AuthenticatedUser(id=user_id, email=email, role=role, is_active=False)


def _password_digest(password: str, salt: str, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    )


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    try:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))
    except (binascii.Error, ValueError):
        raise ValueError from None


def _base64url_json(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return _base64url_encode(encoded)


def _json_from_base64url(value: str) -> dict[str, Any]:
    decoded = _base64url_decode(value).decode("utf-8")
    loaded = json.loads(decoded)
    if not isinstance(loaded, dict):
        raise ValueError
    return loaded


def _sign(signing_input: str, secret_key: str) -> bytes:
    return hmac.new(
        secret_key.encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()


def _required_string_claim(payload: dict[str, Any], name: str) -> str:
    value = payload[name]
    if not isinstance(value, str) or not value:
        raise ValueError
    return value
