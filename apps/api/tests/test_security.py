from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core import security
from app.core.config import Settings

SECRET = "s" * 40


def test_password_hash_roundtrip() -> None:
    hashed = security.hash_password("a long enough password")
    assert hashed.startswith("$argon2id$")
    assert security.verify_password(hashed, "a long enough password")
    assert not security.verify_password(hashed, "wrong password")


def test_verify_password_rejects_garbage_hash() -> None:
    assert not security.verify_password("not-a-hash", "whatever")
    assert security.password_needs_rehash("not-a-hash")


def test_token_hash_is_sha256_hex() -> None:
    token = security.generate_session_token()
    assert len(token) >= 43
    digest = security.hash_token(token)
    assert len(digest) == 64
    assert digest == security.hash_token(token)
    assert digest != token


def test_csrf_token_bound_to_session() -> None:
    binding = security.csrf_binding("session-a")
    token = security.generate_csrf_token(SECRET, binding)
    assert security.verify_csrf_token(SECRET, token, binding)
    assert not security.verify_csrf_token(SECRET, token, security.csrf_binding("session-b"))
    assert not security.verify_csrf_token(SECRET, token, security.ANON_BINDING)
    assert not security.verify_csrf_token("other-secret" * 4, token, binding)


@pytest.mark.parametrize("token", [None, "", "nodot", ".sig", "nonce.", "nonce.deadbeef"])
def test_csrf_rejects_malformed(token: str | None) -> None:
    assert not security.verify_csrf_token(SECRET, token, security.ANON_BINDING)


def test_csrf_rejects_tampered_nonce() -> None:
    token = security.generate_csrf_token(SECRET, security.ANON_BINDING)
    nonce, _, sig = token.partition(".")
    assert not security.verify_csrf_token(SECRET, f"{nonce}x.{sig}", security.ANON_BINDING)


def _settings(**kw: object) -> Settings:
    base: dict[str, object] = {
        "database_url": "postgresql+asyncpg://u:p@h/db",
        "redis_url": "redis://h:6379/0",
        "secret_key": "k" * 32,
    }
    base.update(kw)
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


def test_settings_reject_short_secret_key() -> None:
    with pytest.raises(ValidationError):
        _settings(secret_key="short")


def test_settings_split_cors_origins() -> None:
    s = _settings(cors_allowed_origins="https://a.example, https://b.example ,")
    assert s.cors_allowed_origins == ["https://a.example", "https://b.example"]


def test_settings_defaults_are_secure() -> None:
    s = _settings()
    assert s.cookie_secure is True
    assert s.environment == "production"
    assert s.session_ttl_hours == 168
