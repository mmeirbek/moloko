"""Encryption of secrets at rest (provider API keys, integration tokens).

Uses Fernet (AES-128-CBC + HMAC-SHA256) from ``cryptography`` with a key derived
from APP_ENCRYPTION_KEY. Ciphertexts are versioned (``v1:``) so the scheme can be
rotated later without guessing.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.errors import AppError

_PREFIX = "v1:"


class EncryptionUnavailable(AppError):
    status_code = 503
    code = "encryption_unavailable"
    message = "APP_ENCRYPTION_KEY is not configured on the server, so secrets cannot be stored."


class DecryptionFailed(AppError):
    status_code = 500
    code = "decryption_failed"
    message = "A stored secret could not be decrypted (was APP_ENCRYPTION_KEY changed?)."


class SecretBox:
    def __init__(self, key_material: str | None) -> None:
        self._fernet: Fernet | None = None
        if key_material:
            digest = hashlib.sha256(b"moloko/secrets/v1:" + key_material.encode()).digest()
            self._fernet = Fernet(base64.urlsafe_b64encode(digest))

    @property
    def available(self) -> bool:
        return self._fernet is not None

    def encrypt(self, plaintext: str) -> str:
        if self._fernet is None:
            raise EncryptionUnavailable()
        return _PREFIX + self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        if self._fernet is None:
            raise EncryptionUnavailable()
        if not ciphertext.startswith(_PREFIX):
            raise DecryptionFailed()
        try:
            return self._fernet.decrypt(ciphertext[len(_PREFIX) :].encode()).decode()
        except InvalidToken:
            raise DecryptionFailed() from None


def secret_hint(secret: str) -> str:
    """What the UI may show about a stored secret: its last 4 characters."""
    return f"…{secret[-4:]}" if len(secret) >= 8 else "…"
