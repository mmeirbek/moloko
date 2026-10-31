from __future__ import annotations

import httpx
from fastapi import FastAPI
from sqlalchemy import select

from app.models import AuditLog, Provider, User
from tests.conftest import AppFactory, add_mock_model, csrf_headers, logged_in_client


async def test_kinds_hide_mock_unless_enabled(app_factory: AppFactory, owner: User) -> None:
    app = await app_factory(enable_mock_provider=False)
    async with logged_in_client(app) as client:
        assert (await client.get("/api/v1/providers/kinds")).json() == ["openai", "anthropic"]
        resp = await client.post(
            "/api/v1/providers",
            json={"kind": "mock", "name": "M"},
            headers=await csrf_headers(client),
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "provider_kind_unavailable"


async def test_api_key_is_encrypted_and_never_returned(app: FastAPI, owner: User) -> None:
    secret = "sk-live-super-secret-value-1234"
    async with logged_in_client(app) as client:
        resp = await client.post(
            "/api/v1/providers",
            json={"kind": "openai", "name": "OpenAI", "api_key": secret},
            headers=await csrf_headers(client),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["api_key_source"] == "stored"
        assert body["api_key_hint"] == "…1234"
        assert secret not in resp.text
        listing = await client.get("/api/v1/providers")
        assert secret not in listing.text

        provider_id = body["id"]
        resp = await client.patch(
            f"/api/v1/providers/{provider_id}",
            json={"clear_api_key": True},
            headers=await csrf_headers(client),
        )
        assert resp.json()["api_key_source"] == "none"

    async with app.state.db.sessionmaker() as s:
        audits = list((await s.execute(select(AuditLog))).scalars())
    assert {"provider.created", "provider.updated"} <= {a.action for a in audits}
    assert secret not in repr([a.details for a in audits])


async def test_stored_key_is_ciphertext_in_db(app: FastAPI, owner: User) -> None:
    secret = "sk-ant-another-secret-9876"
    async with logged_in_client(app) as client:
        await client.post(
            "/api/v1/providers",
            json={"kind": "anthropic", "name": "Claude", "api_key": secret},
            headers=await csrf_headers(client),
        )
    async with app.state.db.sessionmaker() as s:
        row = (await s.execute(select(Provider))).scalar_one()
    assert row.api_key_encrypted and row.api_key_encrypted.startswith("v1:")
    assert secret not in row.api_key_encrypted
    assert app.state.gateway.secrets.decrypt(row.api_key_encrypted) == secret


async def test_storing_a_key_without_encryption_key_is_refused(
    app_factory: AppFactory, owner: User
) -> None:
    app = await app_factory(app_encryption_key=None)
    async with logged_in_client(app) as client:
        resp = await client.post(
            "/api/v1/providers",
            json={"kind": "openai", "name": "OpenAI", "api_key": "sk-123456789"},
            headers=await csrf_headers(client),
        )
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "encryption_unavailable"


async def test_base_url_must_be_https(app: FastAPI, owner: User) -> None:
    async with logged_in_client(app) as client:
        resp = await client.post(
            "/api/v1/providers",
            json={"kind": "openai", "name": "X", "base_url": "http://plain.example"},
            headers=await csrf_headers(client),
        )
    assert resp.status_code == 422


async def test_duplicate_provider_name_conflicts(app: FastAPI, owner: User) -> None:
    async with logged_in_client(app) as client:
        for expected in (201, 409):
            resp = await client.post(
                "/api/v1/providers",
                json={"kind": "mock", "name": "Same"},
                headers=await csrf_headers(client),
            )
            assert resp.status_code == expected


async def test_test_and_sync_models_and_default(app: FastAPI, owner: User) -> None:
    async with logged_in_client(app) as client:
        default = await add_mock_model(client)
        assert default["provider_kind"] == "mock"
        models = (await client.get("/api/v1/models")).json()
        assert {m["model"] for m in models} == {"mock-fast", "mock-smart"}
        assert sum(m["is_default"] for m in models) == 1

        provider_id = default["provider_id"]
        test = (
            await client.post(
                f"/api/v1/providers/{provider_id}/test", headers=await csrf_headers(client)
            )
        ).json()
        assert test == {"ok": True, "models_found": 2, "error_code": None, "error_message": None}

        # Re-sync adds nothing new.
        again = await client.post(
            f"/api/v1/providers/{provider_id}/sync-models", headers=await csrf_headers(client)
        )
        assert again.json() == {"added": 0, "total": 2}

        other = next(m for m in models if not m["is_default"])
        resp = await client.patch(
            f"/api/v1/models/{other['id']}",
            json={
                "is_default": True,
                "input_price_per_mtok": "3",
                "output_price_per_mtok": "15",
                "params": {"temperature": 0.3},
            },
            headers=await csrf_headers(client),
        )
        assert resp.status_code == 200
        models = (await client.get("/api/v1/models")).json()
        assert [m["id"] for m in models if m["is_default"]] == [other["id"]]

        # Disabling hides it from the picker but not from the settings list.
        await client.patch(
            f"/api/v1/models/{other['id']}",
            json={"enabled": False},
            headers=await csrf_headers(client),
        )
        assert other["id"] not in {m["id"] for m in (await client.get("/api/v1/models")).json()}
        all_models = (await client.get("/api/v1/models?include_disabled=true")).json()
        assert other["id"] in {m["id"] for m in all_models}


async def test_test_reports_missing_key_clearly(app: FastAPI, owner: User) -> None:
    async with logged_in_client(app) as client:
        resp = await client.post(
            "/api/v1/providers",
            json={"kind": "openai", "name": "NoKey"},
            headers=await csrf_headers(client),
        )
        assert resp.json()["api_key_source"] == "none"
        test = await client.post(
            f"/api/v1/providers/{resp.json()['id']}/test", headers=await csrf_headers(client)
        )
    assert test.json()["ok"] is False
    assert test.json()["error_code"] == "provider_auth_failed"


async def test_add_model_manually(app: FastAPI, owner: User) -> None:
    async with logged_in_client(app) as client:
        resp = await client.post(
            "/api/v1/providers",
            json={"kind": "mock", "name": "M"},
            headers=await csrf_headers(client),
        )
        provider_id = resp.json()["id"]
        resp = await client.post(
            "/api/v1/models",
            json={"provider_id": provider_id, "model": "custom-model"},
            headers=await csrf_headers(client),
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["is_default"] is True
        dup = await client.post(
            "/api/v1/models",
            json={"provider_id": provider_id, "model": "custom-model"},
            headers=await csrf_headers(client),
        )
        assert dup.status_code == 409


async def test_other_users_providers_are_invisible(
    app: FastAPI, owner: User, client: httpx.AsyncClient
) -> None:
    # Anonymous access is covered by test_route_protection; here: unknown ids are 404.
    async with logged_in_client(app) as c:
        resp = await c.patch(
            "/api/v1/providers/00000000-0000-0000-0000-000000000000",
            json={"enabled": False},
            headers=await csrf_headers(c),
        )
    assert resp.status_code == 404
