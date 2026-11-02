"""The STT HTTP API with a stand-in engine (no model download needed)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import BinaryIO

import pytest
from fastapi.testclient import TestClient

from stt_server.app import create_app
from stt_server.catalog import CATALOG, COMPLETE, is_complete
from stt_server.config import Config
from stt_server.engine import Transcription, pick_language


class FakeEngine:
    def __init__(self, config: Config) -> None:
        self.calls: list[tuple[bytes, str | None]] = []

    def transcribe(
        self, audio: BinaryIO, language: str | None, prompt: str | None
    ) -> Transcription:
        data = audio.read()
        if data == b"garbage":
            raise ValueError("invalid data")
        self.calls.append((data, language))
        return Transcription(" Привет, moloko ".strip(), language or "ru", 1.5)


def config(tmp_path: Path, **overrides: object) -> Config:
    values: dict[str, object] = {
        "model": "small",
        "models_dir": tmp_path,
        "compute_type": "int8",
        "cpu_threads": 0,
        "beam_size": 1,
        "vad": True,
        "languages": ("ru", "en"),
        "max_bytes": 1000,
        "concurrency": 1,
        "poll_seconds": 1.0,
    }
    values.update(overrides)
    return Config(**values)  # type: ignore[arg-type]


def mark_downloaded(models_dir: Path, name: str) -> None:
    folder = models_dir / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / COMPLETE).write_text(json.dumps({"revision": CATALOG[name].revision}))


def wait_for(client: TestClient, status: str) -> dict[str, object]:
    deadline = time.monotonic() + 5
    while True:
        body: dict[str, object] = client.get("/health").json()
        if body["status"] == status or time.monotonic() > deadline:
            return body
        time.sleep(0.05)


def test_transcribes_once_the_model_is_there(tmp_path: Path) -> None:
    with TestClient(create_app(config(tmp_path), FakeEngine)) as client:
        assert wait_for(client, "missing")["status"] == "missing"
        resp = client.post("/v1/audio/transcriptions", files={"file": ("a.webm", b"audio")})
        assert resp.status_code == 503 and resp.json()["error"]["type"] == "not_ready"
        mark_downloaded(tmp_path, "small")
        assert wait_for(client, "ready") == {"status": "ready", "model": "small", "detail": None}

        resp = client.post(
            "/v1/audio/transcriptions",
            files={"file": ("a.webm", b"audio", "audio/webm")},
            data={"model": "small", "language": "ru"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"text": "Привет, moloko", "language": "ru", "duration": 1.5}
        text = client.post(
            "/v1/audio/transcriptions",
            files={"file": ("a.webm", b"audio")},
            data={"language": "", "response_format": "text"},
        )
        assert text.text == "Привет, moloko"
        assert client.get("/v1/models").json()["data"][0]["id"] == "small"

        bad = client.post(
            "/v1/audio/transcriptions", files={"file": ("a", b"audio")}, data={"language": "r u"}
        )
        assert bad.status_code == 400
        garbage = client.post("/v1/audio/transcriptions", files={"file": ("a", b"garbage")})
        assert garbage.status_code == 400 and garbage.json()["error"]["type"] == "invalid_audio"
        big = client.post("/v1/audio/transcriptions", files={"file": ("a", b"x" * 1001)})
        assert big.status_code == 413
        engine = client.app.state.stt.engine  # type: ignore[attr-defined]
        assert engine.calls == [(b"audio", "ru"), (b"audio", None)]


def test_an_unknown_model_is_reported(tmp_path: Path) -> None:
    with TestClient(create_app(config(tmp_path, model="huge-v9"), FakeEngine)) as client:
        body = wait_for(client, "error")
        assert body["status"] == "error" and "huge-v9" in str(body["detail"])


def test_download_marker_must_match_the_pinned_revision(tmp_path: Path) -> None:
    assert not is_complete(tmp_path, "small")
    folder = tmp_path / "small"
    folder.mkdir()
    (folder / COMPLETE).write_text(json.dumps({"revision": "something-else"}))
    assert not is_complete(tmp_path, "small")
    mark_downloaded(tmp_path, "small")
    assert is_complete(tmp_path, "small")


@pytest.mark.parametrize(
    ("probs", "allowed", "expected"),
    [
        ([("uk", 0.6), ("ru", 0.3), ("en", 0.1)], ("ru", "en"), "ru"),
        ([("en", 0.9), ("ru", 0.1)], ("ru", "en"), "en"),
        ([("kk", 0.7), ("ru", 0.2)], (), "kk"),
        ([("kk", 1.0)], ("ru", "en"), "ru"),
    ],
)
def test_detection_keeps_to_the_allowed_languages(
    probs: list[tuple[str, float]], allowed: tuple[str, ...], expected: str
) -> None:
    assert pick_language(probs, allowed)[0] == expected
