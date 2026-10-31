"""WebSocket protocol (spec 11). Uses Starlette's TestClient (own event loop, own app)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import create_app
from tests.conftest import OWNER_PASSWORD, OWNER_USERNAME, make_settings

# Secure cookies are only sent over TLS, exactly like a browser behind Tailscale Serve.
WS_URL = "wss://testserver/ws/v1/events"


@pytest.fixture
def ws_client(owner: Any) -> Iterator[TestClient]:
    app = create_app(make_settings())
    with TestClient(app, base_url="https://testserver") as client:
        client.get("/api/v1/auth/csrf")
        resp = client.post(
            "/api/v1/auth/login",
            json={"username": OWNER_USERNAME, "password": OWNER_PASSWORD},
            headers={"X-CSRF-Token": client.cookies["moloko_csrf"]},
        )
        assert resp.status_code == 200
        yield client


def csrf(client: TestClient) -> str:
    return client.cookies["moloko_csrf"]


def create_agent(client: TestClient, name: str) -> dict[str, Any]:
    resp = client.post(
        "/api/v1/agents", json={"name": name}, headers={"X-CSRF-Token": csrf(client)}
    )
    assert resp.status_code == 201
    return resp.json()


def test_unauthenticated_socket_is_rejected(owner: Any) -> None:
    app = create_app(make_settings())
    with (
        TestClient(app, base_url="https://testserver") as client,
        pytest.raises(WebSocketDisconnect) as info,
        client.websocket_connect(WS_URL) as ws,
    ):
        ws.receive_json()
    assert info.value.code == 4401


def test_hello_without_valid_csrf_is_rejected(ws_client: TestClient) -> None:
    with ws_client.websocket_connect(WS_URL) as ws:
        ws.send_json({"type": "hello", "last_seq": None, "csrf": "forged.token"})
        with pytest.raises(WebSocketDisconnect) as info:
            ws.receive_json()
    assert info.value.code == 4403


def test_snapshot_then_live_events(ws_client: TestClient) -> None:
    create_agent(ws_client, "Before")
    with ws_client.websocket_connect(WS_URL) as ws:
        ws.send_json({"type": "hello", "last_seq": None, "csrf": csrf(ws_client)})
        snapshot = ws.receive_json()
        assert snapshot["type"] == "snapshot"
        assert [a["name"] for a in snapshot["agents"]] == ["Before"]
        assert snapshot["seq"] > 0 and snapshot["approvals"] == []

        create_agent(ws_client, "Live")
        frame = ws.receive_json()
        assert frame["type"] == "event"
        event = frame["event"]
        assert event["type"] == "agent.created"
        assert event["seq"] > snapshot["seq"]
        assert event["payload"]["agent"]["name"] == "Live"

        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}


def test_reconnect_replays_only_missed_events_in_order(ws_client: TestClient) -> None:
    with ws_client.websocket_connect(WS_URL) as ws:
        ws.send_json({"type": "hello", "last_seq": None, "csrf": csrf(ws_client)})
        last_seq = ws.receive_json()["seq"]
    # Offline: things happen.
    for name in ("A", "B", "C"):
        create_agent(ws_client, name)
    with ws_client.websocket_connect(WS_URL) as ws:
        ws.send_json({"type": "hello", "last_seq": last_seq, "csrf": csrf(ws_client)})
        frames = [ws.receive_json() for _ in range(3)]
        resumed = ws.receive_json()
    assert [f["type"] for f in frames] == ["event"] * 3
    assert resumed == {"type": "resumed", "seq": frames[-1]["event"]["seq"]}
    replayed = [f["event"] for f in frames]
    assert [e["payload"]["agent"]["name"] for e in replayed] == ["A", "B", "C"]
    seqs = [e["seq"] for e in replayed]
    assert seqs == sorted(seqs) and seqs[0] > last_seq


def test_too_old_or_invalid_last_seq_gets_a_fresh_snapshot(owner: Any) -> None:
    app = create_app(make_settings(realtime_max_replay=10))
    with TestClient(app, base_url="https://testserver") as client:
        client.get("/api/v1/auth/csrf")
        client.post(
            "/api/v1/auth/login",
            json={"username": OWNER_USERNAME, "password": OWNER_PASSWORD},
            headers={"X-CSRF-Token": client.cookies["moloko_csrf"]},
        )
        for i in range(12):
            create_agent(client, f"agent-{i}")
        for last_seq in (0, 10**9, "garbage", True, -5):
            with client.websocket_connect(WS_URL) as ws:
                ws.send_json({"type": "hello", "last_seq": last_seq, "csrf": csrf(client)})
                first = ws.receive_json()
            assert first["type"] == "snapshot", last_seq
            assert len(first["agents"]) == 12


def test_logout_closes_the_socket_on_next_session_check(
    ws_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.events import ws as ws_module

    monkeypatch.setattr(ws_module, "SESSION_RECHECK_SECONDS", 0.1)
    monkeypatch.setattr(ws_module, "DB_POLL_SECONDS", 0.1)
    with ws_client.websocket_connect(WS_URL) as ws:
        ws.send_json({"type": "hello", "last_seq": None, "csrf": csrf(ws_client)})
        ws.receive_json()
        ws_client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf(ws_client)})
        with pytest.raises(WebSocketDisconnect) as info:
            while True:
                ws.receive_json()
    assert info.value.code == 4401


def test_events_arrive_even_when_redis_is_down(owner: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.events import ws as ws_module

    monkeypatch.setattr(ws_module, "DB_POLL_SECONDS", 0.2)
    app = create_app(make_settings(redis_url="redis://127.0.0.1:1/0"))
    with TestClient(app, base_url="https://testserver") as client:
        client.get("/api/v1/auth/csrf")
        client.post(
            "/api/v1/auth/login",
            json={"username": OWNER_USERNAME, "password": OWNER_PASSWORD},
            headers={"X-CSRF-Token": client.cookies["moloko_csrf"]},
        )
        with client.websocket_connect(WS_URL) as ws:
            ws.send_json({"type": "hello", "last_seq": None, "csrf": csrf(client)})
            ws.receive_json()
            create_agent(client, "Polled")
            event = ws.receive_json()["event"]
    assert event["payload"]["agent"]["name"] == "Polled"


def test_resume_with_nothing_missed_is_confirmed(ws_client: TestClient) -> None:
    """Regression: a client that missed nothing must still hear that it is caught up."""
    create_agent(ws_client, "Seen")
    with ws_client.websocket_connect(WS_URL) as ws:
        ws.send_json({"type": "hello", "last_seq": None, "csrf": csrf(ws_client)})
        seq = ws.receive_json()["seq"]
    with ws_client.websocket_connect(WS_URL) as ws:
        ws.send_json({"type": "hello", "last_seq": seq, "csrf": csrf(ws_client)})
        assert ws.receive_json() == {"type": "resumed", "seq": seq}


def test_far_behind_is_measured_in_missed_events_not_seq_distance(owner: Any) -> None:
    """Regression: seq is global (and has gaps) — a big seq jump with few missed events replays."""
    from sqlalchemy import text

    app = create_app(make_settings(realtime_max_replay=10))
    with TestClient(app, base_url="https://testserver") as client:
        client.get("/api/v1/auth/csrf")
        client.post(
            "/api/v1/auth/login",
            json={"username": OWNER_USERNAME, "password": OWNER_PASSWORD},
            headers={"X-CSRF-Token": client.cookies["moloko_csrf"]},
        )
        with client.websocket_connect(WS_URL) as ws:
            ws.send_json({"type": "hello", "last_seq": None, "csrf": csrf(client)})
            last_seq = ws.receive_json()["seq"]

        async def burn_sequence() -> None:  # other users / rolled-back writes consume seq values
            async with app.state.db.engine.begin() as conn:
                seq = "pg_get_serial_sequence('agent_events', 'seq')"
                await conn.execute(text(f"SELECT setval({seq}, nextval({seq}) + 5000)"))

        assert client.portal is not None
        client.portal.call(burn_sequence)
        create_agent(client, "After the jump")
        with client.websocket_connect(WS_URL) as ws:
            ws.send_json({"type": "hello", "last_seq": last_seq, "csrf": csrf(client)})
            first = ws.receive_json()
    assert first["type"] == "event"
    assert first["event"]["payload"]["agent"]["name"] == "After the jump"
