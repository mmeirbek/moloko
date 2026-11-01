from __future__ import annotations

import pytest

from app.core.crypto import DecryptionFailed, EncryptionUnavailable, SecretBox, secret_hint


def test_roundtrip_and_ciphertext_hides_secret() -> None:
    box = SecretBox("k" * 40)
    token = box.encrypt("sk-test-123456789")
    assert token.startswith("v1:")
    assert "sk-test" not in token
    assert box.decrypt(token) == "sk-test-123456789"


def test_wrong_key_cannot_decrypt() -> None:
    token = SecretBox("a" * 40).encrypt("secret")
    with pytest.raises(DecryptionFailed):
        SecretBox("b" * 40).decrypt(token)


def test_missing_key_refuses_to_store_or_read() -> None:
    box = SecretBox(None)
    assert not box.available
    with pytest.raises(EncryptionUnavailable):
        box.encrypt("x")
    with pytest.raises(EncryptionUnavailable):
        box.decrypt("v1:abc")


def test_unversioned_ciphertext_is_rejected() -> None:
    with pytest.raises(DecryptionFailed):
        SecretBox("k" * 40).decrypt("plaintext")


def test_hint_shows_only_last_four() -> None:
    assert secret_hint("sk-abcdefgh1234") == "…1234"
    assert secret_hint("short") == "…"
