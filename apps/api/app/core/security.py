"""Password hashing, session tokens and CSRF tokens.

* Passwords: argon2id (argon2-cffi defaults follow RFC 9106's recommended profile).
* Session tokens: 256-bit random values. Only their SHA-256 hash is stored in the DB,
  so a database leak does not leak usable sessions.
* CSRF: signed double-submit tokens. A token is ``nonce.signature`` where the
  signature is an HMAC over the nonce and the *session binding* (the hash of the
  current session cookie, or ``"anon"``). A token minted for one session is
  therefore useless for another, and a token cannot be forged without SECRET_KEY.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()

# Used to spend the same time on unknown usernames as on known ones,
# so response timing does not reveal which usernames exist.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))

ANON_BINDING = "anon"
MIN_PASSWORD_LENGTH = 12


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def burn_password_check(password: str) -> None:
    """Run a full argon2 verification that always fails (timing equalisation)."""
    verify_password(_DUMMY_HASH, password)


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def csrf_binding(session_cookie: str | None) -> str:
    return hash_token(session_cookie) if session_cookie else ANON_BINDING


def _csrf_signature(secret_key: str, nonce: str, binding: str) -> str:
    msg = f"{nonce}|{binding}".encode()
    return hmac.new(secret_key.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def generate_csrf_token(secret_key: str, binding: str) -> str:
    nonce = secrets.token_urlsafe(18)
    return f"{nonce}.{_csrf_signature(secret_key, nonce, binding)}"


def verify_csrf_token(secret_key: str, token: str | None, binding: str) -> bool:
    if not token or "." not in token:
        return False
    nonce, _, signature = token.partition(".")
    if not nonce or not signature:
        return False
    expected = _csrf_signature(secret_key, nonce, binding)
    return hmac.compare_digest(expected, signature)
