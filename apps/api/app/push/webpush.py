"""Web Push message encryption (RFC 8291, aes128gcm) and VAPID (RFC 8292), with the
``cryptography`` package only. The push service (Apple/Google/Mozilla/Microsoft) sees
only the encrypted payload, the endpoint and our VAPID public key."""

from __future__ import annotations

import base64
import json
import os
import struct
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx2
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

RECORD_SIZE = 4096
MAX_PAYLOAD = 3000  # well under the 4 KB push services accept

TRANSPORT: httpx2.AsyncBaseTransport | None = None  # tests


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64u_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def public_bytes(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )


def _hkdf(salt: bytes, info: bytes, length: int, ikm: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def encrypt(payload: bytes, p256dh: str, auth: str) -> bytes:
    """One aes128gcm record (RFC 8291 §3.4, RFC 8188)."""
    ua_public = b64u_decode(p256dh)
    auth_secret = b64u_decode(auth)
    ua_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    as_private = ec.generate_private_key(ec.SECP256R1())
    as_public = public_bytes(as_private.public_key())
    shared = as_private.exchange(ec.ECDH(), ua_key)
    ikm = _hkdf(auth_secret, b"WebPush: info\x00" + ua_public + as_public, 32, shared)
    salt = os.urandom(16)
    cek = _hkdf(salt, b"Content-Encoding: aes128gcm\x00", 16, ikm)
    nonce = _hkdf(salt, b"Content-Encoding: nonce\x00", 12, ikm)
    record = payload + b"\x02"  # last record, no padding
    ciphertext = AESGCM(cek).encrypt(nonce, record, None)
    return salt + struct.pack("!I", RECORD_SIZE) + bytes([len(as_public)]) + as_public + ciphertext


@dataclass(frozen=True)
class VapidKeys:
    private: ec.EllipticCurvePrivateKey

    @classmethod
    def generate(cls) -> VapidKeys:
        return cls(ec.generate_private_key(ec.SECP256R1()))

    @classmethod
    def from_pem(cls, pem: str) -> VapidKeys:
        key = serialization.load_pem_private_key(pem.encode(), password=None)
        assert isinstance(key, ec.EllipticCurvePrivateKey)
        return cls(key)

    def pem(self) -> str:
        return self.private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()

    @property
    def public_b64(self) -> str:
        """The ``applicationServerKey`` browsers subscribe with."""
        return b64u(public_bytes(self.private.public_key()))

    def authorization(self, endpoint: str, subject: str, ttl: int = 12 * 3600) -> str:
        parts = urlsplit(endpoint)
        header = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}).encode())
        claims = b64u(
            json.dumps(
                {
                    "aud": f"{parts.scheme}://{parts.netloc}",
                    "exp": int(time.time()) + ttl,
                    "sub": subject,
                }
            ).encode()
        )
        signing_input = f"{header}.{claims}".encode()
        r, s = decode_dss_signature(self.private.sign(signing_input, ec.ECDSA(hashes.SHA256())))
        signature = b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
        return f"vapid t={header}.{claims}.{signature}, k={self.public_b64}"


def host_allowed(endpoint: str, allowed: list[str]) -> bool:
    parts = urlsplit(endpoint)
    if parts.scheme != "https" or not parts.hostname:
        return False
    host = parts.hostname.lower()
    for pattern in allowed:
        pattern = pattern.lower().strip()
        if pattern.startswith("*.") and host.endswith(pattern[1:]):
            return True
        if host == pattern:
            return True
    return False


async def send(
    endpoint: str,
    p256dh: str,
    auth: str,
    payload: dict[str, object],
    keys: VapidKeys,
    *,
    subject: str,
    ttl: int,
    urgency: str = "normal",
    topic: str | None = None,
    http_timeout: float = 10.0,
) -> int:
    """POST one push message. Returns the push service's HTTP status."""
    body = json.dumps(payload, ensure_ascii=False).encode()[:MAX_PAYLOAD]
    headers = {
        "Authorization": keys.authorization(endpoint, subject),
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        "TTL": str(ttl),
        "Urgency": urgency,
    }
    if topic:
        headers["Topic"] = topic[:32]
    async with httpx2.AsyncClient(transport=TRANSPORT, timeout=http_timeout) as client:
        resp = await client.post(endpoint, content=encrypt(body, p256dh, auth), headers=headers)
    return resp.status_code
