"""Passkeys (WebAuthn): adding one with the password, signing in with it, and the refusals.

A software authenticator (an ES256 key + the same CBOR/authenticator-data layout a phone or
laptop produces, "none" attestation like Apple/Google passkeys) answers the server's real,
random challenges, so every check of py_webauthn and of our policy runs for real.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import secrets
import struct
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy import select
from webauthn.helpers import encode_cbor

from app.core.security import hash_token
from app.models import AuditLog, Session, User, WebAuthnCredential
from app.services.auth import login_subject_key
from app.services.passkeys import UNKNOWN_PASSKEY_SUBJECT
from tests.conftest import (
    OWNER_PASSWORD,
    OWNER_USERNAME,
    AppFactory,
    csrf_headers,
    logged_in_client,
    login,
    make_client,
    make_settings,
)

RP_ID = "moloko.tail1234.ts.net"
ORIGIN = f"https://{RP_ID}"
BASE = "/api/v1/auth/passkeys"
PASSKEY_SETTINGS: dict[str, Any] = {"webauthn_rp_id": RP_ID, "webauthn_origins": ORIGIN}

# Authenticator data flags (WebAuthn §6.1).
UP, UV, BE, BS, AT = 0x01, 0x04, 0x08, 0x10, 0x40


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


@dataclass
class SoftAuthenticator:
    """A passkey on a pretend device. ``counter`` > 0 = a security key with a real counter;
    synced passkeys (iCloud Keychain, Google Password Manager) keep it at 0."""

    rp_id: str = RP_ID
    counter: int = 0
    synced: bool = True
    credential_id: bytes = field(default_factory=lambda: secrets.token_bytes(32))
    key: ec.EllipticCurvePrivateKey = field(
        default_factory=lambda: ec.generate_private_key(ec.SECP256R1())
    )
    user_handle: bytes | None = None

    def _cose_public_key(self) -> bytes:
        numbers = self.key.public_key().public_numbers()
        return encode_cbor(
            {
                1: 2,  # kty: EC2
                3: -7,  # alg: ES256
                -1: 1,  # crv: P-256
                -2: numbers.x.to_bytes(32, "big"),
                -3: numbers.y.to_bytes(32, "big"),
            }
        )

    def _flags(self, *, uv: bool) -> int:
        flags = UP | (UV if uv else 0)
        if self.synced:
            flags |= BE | BS
        return flags

    def _auth_data(self, flags: int, rp_id: str | None = None) -> bytes:
        rp_hash = hashlib.sha256((rp_id or self.rp_id).encode()).digest()
        return rp_hash + bytes([flags]) + struct.pack(">I", self.counter)

    @staticmethod
    def _client_data(kind: str, options: dict[str, Any], origin: str) -> bytes:
        return json.dumps(
            {
                "type": kind,
                "challenge": options["challenge"],
                "origin": origin,
                "crossOrigin": False,
            }
        ).encode()

    def create(
        self, options: dict[str, Any], *, origin: str = ORIGIN, uv: bool = True
    ) -> dict[str, Any]:
        """navigator.credentials.create() → RegistrationResponseJSON."""
        assert options["rp"]["id"] == self.rp_id
        self.user_handle = unb64url(options["user"]["id"])
        attested = (
            bytes(16)  # AAGUID: none given (like most synced passkeys)
            + struct.pack(">H", len(self.credential_id))
            + self.credential_id
            + self._cose_public_key()
        )
        auth_data = self._auth_data(self._flags(uv=uv) | AT) + attested
        attestation = encode_cbor({"fmt": "none", "attStmt": {}, "authData": auth_data})
        return {
            "id": b64url(self.credential_id),
            "rawId": b64url(self.credential_id),
            "type": "public-key",
            "authenticatorAttachment": "platform",
            "clientExtensionResults": {},
            "response": {
                "clientDataJSON": b64url(self._client_data("webauthn.create", options, origin)),
                "attestationObject": b64url(attestation),
                "transports": ["internal", "hybrid"],
            },
        }

    def get(
        self,
        options: dict[str, Any],
        *,
        origin: str = ORIGIN,
        uv: bool = True,
        rp_id: str | None = None,
        user_handle: bytes | None = None,
    ) -> dict[str, Any]:
        """navigator.credentials.get() → AuthenticationResponseJSON."""
        if self.counter:
            self.counter += 1
        auth_data = self._auth_data(self._flags(uv=uv), rp_id)
        client_data = self._client_data("webauthn.get", options, origin)
        signature = self.key.sign(
            auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256())
        )
        handle = user_handle if user_handle is not None else self.user_handle
        return {
            "id": b64url(self.credential_id),
            "rawId": b64url(self.credential_id),
            "type": "public-key",
            "authenticatorAttachment": "platform",
            "clientExtensionResults": {},
            "response": {
                "clientDataJSON": b64url(client_data),
                "authenticatorData": b64url(auth_data),
                "signature": b64url(signature),
                "userHandle": b64url(handle) if handle is not None else None,
            },
        }


# --- helpers ----------------------------------------------------------------------------------


async def passkey_app(app_factory: AppFactory, **overrides: Any) -> FastAPI:
    return await app_factory(**{**PASSKEY_SETTINGS, **overrides})


async def _post(client: httpx.AsyncClient, path: str, body: Any = None) -> httpx.Response:
    return await client.post(BASE + path, json=body, headers=await csrf_headers(client))


async def add_passkey(
    client: httpx.AsyncClient, device: SoftAuthenticator, name: str = "iPhone"
) -> httpx.Response:
    resp = await _post(client, "/register/options", {"password": OWNER_PASSWORD})
    assert resp.status_code == 200, resp.text
    credential = device.create(resp.json()["options"])
    return await _post(client, "/register/verify", {"credential": credential, "name": name})


async def login_options(client: httpx.AsyncClient) -> dict[str, Any]:
    resp = await _post(client, "/login/options")
    assert resp.status_code == 200, resp.text
    options: dict[str, Any] = resp.json()["options"]
    return options


async def passkey_login(
    client: httpx.AsyncClient, device: SoftAuthenticator, **get_kwargs: Any
) -> httpx.Response:
    options = await login_options(client)
    return await _post(client, "/login/verify", {"credential": device.get(options, **get_kwargs)})


async def _audit(app: FastAPI, action: str) -> list[AuditLog]:
    async with app.state.db.sessionmaker() as s:
        rows = await s.execute(
            select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.created_at)
        )
        return list(rows.scalars())


async def _passkeys(app: FastAPI) -> list[WebAuthnCredential]:
    async with app.state.db.sessionmaker() as s:
        return list((await s.execute(select(WebAuthnCredential))).scalars())


async def _registered(app: FastAPI, device: SoftAuthenticator) -> None:
    async with logged_in_client(app) as client:
        resp = await add_passkey(client, device)
        assert resp.status_code == 201, resp.text


# --- configuration ----------------------------------------------------------------------------


def test_settings_need_both_rp_id_and_origins() -> None:
    assert not make_settings().passkeys_enabled
    with pytest.raises(ValidationError, match="WEBAUTHN_RP_ID and WEBAUTHN_ORIGINS"):
        make_settings(webauthn_rp_id=RP_ID)
    with pytest.raises(ValidationError, match="WEBAUTHN_RP_ID and WEBAUTHN_ORIGINS"):
        make_settings(webauthn_origins=ORIGIN)
    s = make_settings(webauthn_rp_id=" Moloko.Tail1234.TS.net ", webauthn_origins=ORIGIN + "/")
    assert s.passkeys_enabled
    assert (s.webauthn_rp_id, s.webauthn_origins) == (RP_ID, [ORIGIN])
    # Empty values (as compose passes them) mean "off".
    assert not make_settings(webauthn_rp_id="", webauthn_origins="").passkeys_enabled


@pytest.mark.parametrize(
    ("rp_id", "origins"),
    [
        ("https://moloko.tail1234.ts.net", ORIGIN),  # scheme in the RP ID
        ("127.0.0.1", "https://127.0.0.1"),  # WebAuthn needs a domain name
        (RP_ID, f"http://{RP_ID}"),  # not HTTPS
        (RP_ID, "https://evil.example"),  # another site
        (RP_ID, "https://xmoloko.tail1234.ts.net"),  # not a subdomain, just a suffix
        (RP_ID, f"{ORIGIN}/login"),  # a path is not an origin
    ],
)
def test_settings_refuse_wrong_values(rp_id: str, origins: str) -> None:
    with pytest.raises(ValidationError):
        make_settings(webauthn_rp_id=rp_id, webauthn_origins=origins)


def test_settings_allow_localhost_and_subdomains() -> None:
    assert make_settings(
        webauthn_rp_id="localhost", webauthn_origins="http://localhost:3000"
    ).passkeys_enabled
    s = make_settings(webauthn_rp_id="tail1234.ts.net", webauthn_origins=f"{ORIGIN},{ORIGIN}:8443")
    assert s.webauthn_origins == [ORIGIN, f"{ORIGIN}:8443"]


async def test_passkeys_are_off_without_settings(app: FastAPI, owner: User) -> None:
    async with logged_in_client(app) as client:
        listed = await client.get(BASE)
        assert listed.status_code == 200
        assert listed.json() == {
            "enabled": False,
            "rp_id": None,
            "max_passkeys": 20,
            "passkeys": [],
        }
        resp = await _post(client, "/register/options", {"password": OWNER_PASSWORD})
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "passkeys_disabled"
    async with make_client(app) as anon:
        resp = await _post(anon, "/login/options")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "passkeys_disabled"
        # The password keeps working, of course.
        assert (await login(anon)).status_code == 200


# --- adding a passkey -------------------------------------------------------------------------


async def test_add_passkey_with_password(app_factory: AppFactory, owner: User) -> None:
    app = await passkey_app(app_factory)
    device = SoftAuthenticator()
    async with logged_in_client(app) as client:
        resp = await _post(client, "/register/options", {"password": OWNER_PASSWORD})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        options = body["options"]
        assert body["expires_in_seconds"] == 300
        assert options["rp"] == {"name": "moloko", "id": RP_ID}
        assert unb64url(options["user"]["id"]) == owner.id.bytes  # opaque handle, no name
        assert options["user"]["name"] == OWNER_USERNAME
        assert options["authenticatorSelection"]["residentKey"] == "required"
        assert options["authenticatorSelection"]["userVerification"] == "required"
        assert options["attestation"] == "none"
        assert options["excludeCredentials"] == []
        assert options["timeout"] == 300_000

        verify = await _post(
            client,
            "/register/verify",
            {"credential": device.create(options), "name": "  iPhone   Meir "},
        )
        assert verify.status_code == 201, verify.text
        added = verify.json()
        assert added["name"] == "iPhone Meir"
        assert added["backed_up"] is True
        assert added["transports"] == ["internal", "hybrid"]
        assert added["last_used_at"] is None

        listed = (await client.get(BASE)).json()
        assert listed["enabled"] is True and listed["rp_id"] == RP_ID
        assert [p["id"] for p in listed["passkeys"]] == [added["id"]]

        # A second passkey is offered the first one to exclude (no duplicates on one device).
        again = await _post(client, "/register/options", {"password": OWNER_PASSWORD})
        excluded = again.json()["options"]["excludeCredentials"]
        assert excluded == [
            {
                "id": b64url(device.credential_id),
                "type": "public-key",
                "transports": ["internal", "hybrid"],
            }
        ]

    (row,) = await _passkeys(app)
    assert row.user_id == owner.id and row.credential_id == device.credential_id
    assert row.sign_count == 0 and row.aaguid == "00000000-0000-0000-0000-000000000000"
    (entry,) = await _audit(app, "auth.passkey_added")
    assert entry.user_id == owner.id and entry.resource_id == str(row.id)
    assert entry.details["name"] == "iPhone Meir"
    assert entry.details["subject_key"] == login_subject_key(OWNER_USERNAME)


async def test_adding_needs_the_password_and_counts_toward_lockout(
    app_factory: AppFactory, owner: User
) -> None:
    app = await passkey_app(app_factory, login_max_failures=3, login_lockout_seconds=60)
    async with logged_in_client(app) as client, make_client(app) as other:
        for _ in range(2):
            resp = await _post(client, "/register/options", {"password": "not-my-password"})
            assert resp.status_code == 403
            assert resp.json()["error"]["code"] == "invalid_password"
        assert (await login(other, password="wrong")).status_code == 401
        # 3 failures in total: even the right password is refused now, and so is signing in.
        blocked = await _post(client, "/register/options", {"password": OWNER_PASSWORD})
        assert blocked.status_code == 429
        assert (await login(other)).status_code == 429
        assert (await client.get("/api/v1/auth/me")).status_code == 200  # still signed in
    failed = await _audit(app, "auth.password_confirm_failed")
    assert [f.details["purpose"] for f in failed] == ["passkey_register"] * 2
    assert await _passkeys(app) == []


async def test_adding_needs_a_session(app_factory: AppFactory, owner: User) -> None:
    app = await passkey_app(app_factory)
    async with make_client(app) as anon:
        resp = await _post(anon, "/register/options", {"password": OWNER_PASSWORD})
        assert resp.status_code == 401


async def test_registration_challenge_is_bound_to_its_session(
    app_factory: AppFactory, owner: User
) -> None:
    app = await passkey_app(app_factory)
    device = SoftAuthenticator()
    async with logged_in_client(app) as first, logged_in_client(app) as second:
        resp = await _post(first, "/register/options", {"password": OWNER_PASSWORD})
        credential = device.create(resp.json()["options"])
        stolen = await _post(second, "/register/verify", {"credential": credential, "name": "x"})
        assert stolen.status_code == 400
        assert stolen.json()["error"]["code"] == "passkey_expired"
        # ...and it was used up by that attempt: not even the right session can use it now.
        late = await _post(first, "/register/verify", {"credential": credential, "name": "x"})
        assert late.status_code == 400
        assert late.json()["error"]["code"] == "passkey_expired"
    assert await _passkeys(app) == []
    assert [e.details["reason"] for e in await _audit(app, "auth.passkey_add_failed")] == [
        "challenge_invalid",
        "challenge_invalid",
    ]


async def test_registration_from_another_site_or_without_verification_is_refused(
    app_factory: AppFactory, owner: User
) -> None:
    app = await passkey_app(app_factory)
    async with logged_in_client(app) as client:
        for kwargs in ({"origin": "https://evil.example"}, {"uv": False}):
            resp = await _post(client, "/register/options", {"password": OWNER_PASSWORD})
            credential = SoftAuthenticator().create(resp.json()["options"], **kwargs)
            bad = await _post(client, "/register/verify", {"credential": credential, "name": "x"})
            assert bad.status_code == 400, kwargs
            assert bad.json()["error"]["code"] == "passkey_invalid"
        garbage = await _post(client, "/register/verify", {"credential": {"id": "x"}, "name": "x"})
        assert garbage.status_code == 400
    assert await _passkeys(app) == []


async def test_passkey_limit(app_factory: AppFactory, owner: User) -> None:
    app = await passkey_app(app_factory, webauthn_max_credentials=1)
    await _registered(app, SoftAuthenticator())
    async with logged_in_client(app) as client:
        resp = await _post(client, "/register/options", {"password": OWNER_PASSWORD})
        assert resp.status_code == 409
        assert resp.json()["error"] == {
            "id": resp.json()["error"]["id"],
            "code": "passkey_limit_reached",
            "message": resp.json()["error"]["message"],
            "details": {"max": 1},
        }


# --- signing in -------------------------------------------------------------------------------


async def test_sign_in_with_passkey_creates_a_normal_session(
    app_factory: AppFactory, owner: User
) -> None:
    app = await passkey_app(app_factory)
    device = SoftAuthenticator()
    await _registered(app, device)
    async with make_client(app) as client:
        await client.get("/api/v1/auth/csrf")
        anon_csrf = client.cookies.get("moloko_csrf")

        opt = await _post(client, "/login/options")
        assert opt.status_code == 200
        options = opt.json()["options"]
        assert options["rpId"] == RP_ID
        assert options["userVerification"] == "required"
        assert options["allowCredentials"] == []  # the device offers its own passkeys
        flow = next(
            c for c in opt.headers.get_list("set-cookie") if c.startswith("moloko_passkey=")
        )
        assert "HttpOnly" in flow and "Secure" in flow and "samesite=strict" in flow.lower()
        assert "Path=/api/v1/auth/passkeys/login" in flow
        assert re.search(r"max-age=300", flow, re.IGNORECASE)

        resp = await _post(client, "/login/verify", {"credential": device.get(options)})
        assert resp.status_code == 200, resp.text
        assert resp.json()["user"]["username"] == OWNER_USERNAME

        cookies = resp.headers.get_list("set-cookie")
        session_cookie = next(c for c in cookies if c.startswith("moloko_session="))
        assert "HttpOnly" in session_cookie and "Secure" in session_cookie
        assert re.search(r"max-age=604800", session_cookie, re.IGNORECASE)  # 168 h default
        # CSRF rotated to the new session, exactly like the password login.
        assert client.cookies.get("moloko_csrf") != anon_csrf
        assert (await client.get("/api/v1/auth/me")).status_code == 200
        raw_session = client.cookies.get("moloko_session")
        assert raw_session
        # The flow cookie is done with.
        assert client.cookies.get("moloko_passkey", path="/api/v1/auth/passkeys/login") is None

    (row,) = await _passkeys(app)
    (entry,) = [e for e in await _audit(app, "auth.login") if e.details["method"] == "passkey"]
    assert entry.outcome == "success" and entry.user_id == owner.id
    assert entry.details == {
        "subject_key": login_subject_key(OWNER_USERNAME),
        "method": "passkey",
        "passkey_id": str(row.id),
    }
    assert row.last_used_at is not None
    async with app.state.db.sessionmaker() as s:
        session = (
            await s.execute(select(Session).where(Session.token_hash == hash_token(raw_session)))
        ).scalar_one()
    assert str(session.id) == entry.resource_id and session.user_id == owner.id


async def test_session_lifetime_follows_the_owners_choice(
    app_factory: AppFactory, owner: User
) -> None:
    app = await passkey_app(app_factory)
    device = SoftAuthenticator()
    await _registered(app, device)
    async with logged_in_client(app) as client:
        resp = await client.put(
            "/api/v1/auth/session-settings",
            json={"ttl_hours": 12, "password": OWNER_PASSWORD},
            headers=await csrf_headers(client),
        )
        assert resp.status_code == 200
    async with make_client(app) as client:
        resp = await passkey_login(client, device)
        assert resp.status_code == 200
        session_cookie = next(
            c for c in resp.headers.get_list("set-cookie") if c.startswith("moloko_session=")
        )
        assert re.search(r"max-age=43200", session_cookie, re.IGNORECASE)


async def test_a_challenge_works_only_once(app_factory: AppFactory, owner: User) -> None:
    app = await passkey_app(app_factory)
    device = SoftAuthenticator()
    await _registered(app, device)
    async with make_client(app) as client:
        options = await login_options(client)
        credential = device.get(options)
        assert (await _post(client, "/login/verify", {"credential": credential})).status_code == 200
    async with make_client(app) as replay:
        await login_options(replay)  # a flow cookie of its own does not help
        # The same signed response again (e.g. captured): its challenge is gone.
        resp = await _post(replay, "/login/verify", {"credential": credential})
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "passkey_expired"
        assert "moloko_session" not in replay.cookies


async def test_a_challenge_belongs_to_the_browser_that_asked(
    app_factory: AppFactory, owner: User
) -> None:
    app = await passkey_app(app_factory)
    device = SoftAuthenticator()
    await _registered(app, device)
    async with make_client(app) as asked, make_client(app) as other:
        options = await login_options(asked)
        resp = await _post(other, "/login/verify", {"credential": device.get(options)})
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "passkey_expired"


async def test_a_newer_prompt_does_not_cancel_an_older_one(
    app_factory: AppFactory, owner: User
) -> None:
    app = await passkey_app(app_factory)
    device = SoftAuthenticator()
    await _registered(app, device)
    async with make_client(app) as client:
        first = await login_options(client)
        second = await login_options(client)  # e.g. a second tab: same flow cookie
        assert first["challenge"] != second["challenge"]
        resp = await _post(client, "/login/verify", {"credential": device.get(first)})
        assert resp.status_code == 200


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"origin": "https://evil.example"}, "verification_failed"),  # phishing site
        ({"origin": "http://moloko.tail1234.ts.net"}, "verification_failed"),  # not HTTPS
        ({"rp_id": "evil.example"}, "verification_failed"),  # another RP's key use
        ({"uv": False}, "verification_failed"),  # no Face ID / Touch ID / PIN
        ({"user_handle": b"someone-else"}, "user_handle_mismatch"),
    ],
)
async def test_bad_assertions_are_rejected_and_counted(
    app_factory: AppFactory, owner: User, kwargs: dict[str, Any], reason: str
) -> None:
    app = await passkey_app(app_factory)
    device = SoftAuthenticator()
    await _registered(app, device)
    async with make_client(app) as client:
        resp = await passkey_login(client, device, **kwargs)
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "passkey_rejected"
        assert "moloko_session" not in client.cookies
    (failed,) = await _audit(app, "auth.login_failed")
    assert failed.user_id == owner.id
    assert failed.details == {
        "subject_key": login_subject_key(OWNER_USERNAME),
        "reason": reason,
        "method": "passkey",
    }


async def test_a_wrong_signature_is_rejected(app_factory: AppFactory, owner: User) -> None:
    app = await passkey_app(app_factory)
    device = SoftAuthenticator()
    await _registered(app, device)
    impostor = SoftAuthenticator(credential_id=device.credential_id, user_handle=owner.id.bytes)
    async with make_client(app) as client:
        resp = await passkey_login(client, impostor)  # same id, another private key
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "passkey_rejected"


async def test_a_cloned_counter_is_rejected(app_factory: AppFactory, owner: User) -> None:
    app = await passkey_app(app_factory)
    device = SoftAuthenticator(counter=10, synced=False)
    await _registered(app, device)
    async with make_client(app) as client:
        assert (await passkey_login(client, device)).status_code == 200
    (row,) = await _passkeys(app)
    assert row.sign_count == 11 and row.backed_up is False
    device.counter = 5  # a copy of the key that is behind the real one
    async with make_client(app) as client:
        assert (await passkey_login(client, device)).status_code == 401


async def test_unknown_passkey_is_rejected_without_locking_the_owner(
    app_factory: AppFactory, owner: User
) -> None:
    app = await passkey_app(app_factory, login_max_failures=2, login_lockout_seconds=60)
    stranger = SoftAuthenticator(user_handle=b"nobody")
    async with make_client(app) as client:
        for _ in range(3):
            resp = await passkey_login(client, stranger)
            assert resp.status_code == 401
            assert resp.json()["error"]["code"] == "passkey_rejected"
        garbage = await _post(client, "/login/verify", {"credential": {"type": "public-key"}})
        assert garbage.status_code == 401
        assert (await login(client)).status_code == 200  # the owner is not locked out
    failed = await _audit(app, "auth.login_failed")
    assert {f.details["subject_key"] for f in failed} == {UNKNOWN_PASSKEY_SUBJECT}
    assert {f.details["reason"] for f in failed} == {"unknown_or_inactive", "malformed"}
    assert all(f.actor_type == "anonymous" and f.user_id is None for f in failed)


async def test_passkey_failures_share_the_login_lockout(
    app_factory: AppFactory, owner: User
) -> None:
    app = await passkey_app(app_factory, login_max_failures=3, login_lockout_seconds=60)
    device = SoftAuthenticator()
    await _registered(app, device)
    async with make_client(app) as client:
        assert (await login(client, password="wrong")).status_code == 401
        for _ in range(2):
            bad = await passkey_login(client, device, origin="https://evil.example")
            assert bad.status_code == 401
        # 1 wrong password + 2 bad passkey answers: the account is locked for both ways in.
        locked = await passkey_login(client, device)
        assert locked.status_code == 429
        assert locked.json()["error"]["code"] == "too_many_attempts"
        assert locked.headers["retry-after"] == "60"
        assert (await login(client)).status_code == 429
        assert "moloko_session" not in client.cookies
    assert len(await _audit(app, "auth.login_blocked")) == 2


async def test_a_passkey_sign_in_restarts_the_failure_count(
    app_factory: AppFactory, owner: User
) -> None:
    app = await passkey_app(app_factory, login_max_failures=3, login_lockout_seconds=60)
    device = SoftAuthenticator()
    await _registered(app, device)
    async with make_client(app) as client:
        for _ in range(2):
            assert (await login(client, password="wrong")).status_code == 401
        assert (await passkey_login(client, device)).status_code == 200
    async with make_client(app) as client:
        for _ in range(2):
            assert (await login(client, password="wrong")).status_code == 401
        assert (await login(client)).status_code == 200


async def test_inactive_owner_cannot_sign_in_with_a_passkey(
    app_factory: AppFactory, owner: User
) -> None:
    app = await passkey_app(app_factory)
    device = SoftAuthenticator()
    await _registered(app, device)
    async with app.state.db.sessionmaker() as s:
        user = (await s.execute(select(User))).scalar_one()
        user.is_active = False
        await s.commit()
    async with make_client(app) as client:
        assert (await passkey_login(client, device)).status_code == 401


# --- list / rename / delete -------------------------------------------------------------------


async def test_rename_and_delete(app_factory: AppFactory, owner: User) -> None:
    app = await passkey_app(app_factory)
    device = SoftAuthenticator()
    async with logged_in_client(app) as client:
        added = (await add_passkey(client, device, name="Mac")).json()
        url = f"{BASE}/{added['id']}"
        renamed = await client.patch(
            url, json={"name": "MacBook Air"}, headers=await csrf_headers(client)
        )
        assert renamed.status_code == 200
        assert renamed.json()["name"] == "MacBook Air"
        blank = await client.patch(url, json={"name": "   "}, headers=await csrf_headers(client))
        assert blank.status_code == 422
        hidden = await client.patch(url, json={"name": "a‮b"}, headers=await csrf_headers(client))
        assert hidden.status_code == 422

        wrong = await client.request(
            "DELETE", url, json={"password": "nope"}, headers=await csrf_headers(client)
        )
        assert wrong.status_code == 403
        assert wrong.json()["error"]["code"] == "invalid_password"
        assert len(await _passkeys(app)) == 1

        missing = await client.request(
            "DELETE",
            f"{BASE}/00000000-0000-0000-0000-000000000000",
            json={"password": OWNER_PASSWORD},
            headers=await csrf_headers(client),
        )
        assert missing.status_code == 404

        gone = await client.request(
            "DELETE", url, json={"password": OWNER_PASSWORD}, headers=await csrf_headers(client)
        )
        assert gone.status_code == 204
        assert (await client.get(BASE)).json()["passkeys"] == []

    async with make_client(app) as client:
        resp = await passkey_login(client, device)  # a deleted passkey no longer opens anything
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "passkey_rejected"

    (rename,) = await _audit(app, "auth.passkey_renamed")
    assert rename.details == {"name": "MacBook Air", "renamed_from": "Mac"}
    (deleted,) = await _audit(app, "auth.passkey_deleted")
    assert deleted.resource_id == added["id"] and deleted.details["name"] == "MacBook Air"
    (confirm,) = await _audit(app, "auth.password_confirm_failed")
    assert confirm.details["purpose"] == "passkey_delete"


async def test_management_needs_a_session(app_factory: AppFactory, owner: User) -> None:
    app = await passkey_app(app_factory)
    async with make_client(app) as anon:
        headers = await csrf_headers(anon)
        assert (await anon.get(BASE)).status_code == 401
        url = f"{BASE}/00000000-0000-0000-0000-000000000000"
        assert (await anon.patch(url, json={"name": "x"}, headers=headers)).status_code == 401
        assert (
            await anon.request("DELETE", url, json={"password": OWNER_PASSWORD}, headers=headers)
        ).status_code == 401


async def test_sign_in_endpoints_need_csrf(app_factory: AppFactory, owner: User) -> None:
    app = await passkey_app(app_factory)
    async with make_client(app) as client:
        assert (await client.post(f"{BASE}/login/options")).status_code == 403
        assert (
            await client.post(f"{BASE}/login/verify", json={"credential": {}})
        ).status_code == 403


# --- nothing secret in logs or the audit log --------------------------------------------------


class _Records(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


async def test_no_credential_ids_challenges_or_signatures_in_logs_or_audit(
    app_factory: AppFactory, owner: User
) -> None:
    app = await passkey_app(app_factory)
    root = logging.getLogger()
    captured, old_level = _Records(), root.level
    root.addHandler(captured)
    root.setLevel(logging.DEBUG)
    try:
        seen = await _sign_in_and_fail(app)
    finally:
        root.removeHandler(captured)
        root.setLevel(old_level)

    async with app.state.db.sessionmaker() as s:
        entries = (await s.execute(select(AuditLog))).scalars()
        audit = repr([(e.action, e.details, e.resource_id) for e in entries])
    logs = "\n".join(f"{r.getMessage()} {r.__dict__}" for r in captured.records)
    assert "passkey_added" in logs and "login_ok" in logs  # the log did run
    stored = [k async for k in app.state.redis.scan_iter("webauthn:*")]
    stored += [str(await app.state.redis.get(k)) for k in list(stored)]
    assert stored  # one sign-in prompt is still pending
    for secret in seen:
        assert secret not in audit
        assert secret not in logs
        # Valkey holds only hashes of challenges and of the flow cookie.
        assert not any(secret in item for item in stored)


async def _sign_in_and_fail(app: FastAPI) -> list[str]:
    """Add a passkey, sign in with it, fail once, leave one prompt open; return every
    secret-ish value that went over the wire."""
    device = SoftAuthenticator()
    seen = [b64url(device.credential_id)]
    async with logged_in_client(app) as client:
        resp = await _post(client, "/register/options", {"password": OWNER_PASSWORD})
        options = resp.json()["options"]
        credential = device.create(options)
        seen += [options["challenge"], credential["response"]["attestationObject"]]
        verify = await _post(client, "/register/verify", {"credential": credential, "name": "a"})
        assert verify.status_code == 201
    async with make_client(app) as client:
        options = await login_options(client)
        assertion = device.get(options)
        seen += [options["challenge"], assertion["response"]["signature"]]
        assert (await _post(client, "/login/verify", {"credential": assertion})).status_code == 200
        bad = device.get(await login_options(client), origin="https://evil.example")
        seen += [bad["response"]["signature"], bad["response"]["clientDataJSON"]]
        assert (await _post(client, "/login/verify", {"credential": bad})).status_code == 401
        pending = await login_options(client)
        flow = client.cookies.get("moloko_passkey", path="/api/v1/auth/passkeys/login")
        assert flow
        seen += [pending["challenge"], flow]
    return seen
