"""HTTP API: ``POST /v1/audio/transcriptions`` (the OpenAI shape) and ``GET /health``.

The service is reachable only on moloko's internal Docker network (no published port, no
route to the internet). It never logs what was said — only timings.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from typing import Annotated, Any

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from stt_server.catalog import UnknownModel, is_complete, spec
from stt_server.config import Config
from stt_server.engine import Engine, WhisperEngine

log = logging.getLogger("stt")

_LANG = re.compile(r"^[a-z]{2,3}$")


class State:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.status = "starting"  # starting | missing | loading | ready | error
        self.detail: str | None = None
        self.engine: Engine | None = None
        self.gate = asyncio.Semaphore(config.concurrency)


def _error(status: int, message: str, kind: str) -> JSONResponse:
    return JSONResponse({"error": {"message": message, "type": kind}}, status_code=status)


async def _load(state: State, make_engine: Callable[[Config], Engine]) -> None:
    """Wait for the downloader to finish (it may still be running), then load the model."""
    config = state.config
    try:
        spec(config.model)
    except UnknownModel as exc:
        state.status, state.detail = "error", str(exc)
        log.error("%s", exc)
        return
    while not is_complete(config.models_dir, config.model):
        if state.status != "missing":
            log.warning("model %s is not downloaded yet; waiting for it", config.model)
        state.status = "missing"
        await asyncio.sleep(config.poll_seconds)
    state.status = "loading"
    started = time.monotonic()
    try:
        state.engine = await asyncio.to_thread(make_engine, config)
    except Exception as exc:
        state.status, state.detail = "error", f"{type(exc).__name__}: {exc}"[:300]
        log.exception("could not load model %s", config.model)
        return
    state.status = "ready"
    log.info("model %s loaded in %.1fs", config.model, time.monotonic() - started)


def create_app(
    config: Config | None = None, make_engine: Callable[[Config], Engine] = WhisperEngine
) -> FastAPI:
    state = State(config or Config.from_env())

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(_load(state, make_engine))
        yield
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    app = FastAPI(title="moloko STT", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.stt = state

    @app.get("/health")
    async def health() -> dict[str, Any]:
        """Always 200 while the process runs; `status` says whether it can transcribe."""
        return {"status": state.status, "model": state.config.model, "detail": state.detail}

    @app.get("/v1/models")
    async def models() -> dict[str, Any]:
        ready = state.status == "ready"
        data = [{"id": state.config.model, "object": "model", "owned_by": "moloko"}]
        return {"object": "list", "data": data if ready else []}

    @app.post("/v1/audio/transcriptions", response_model=None)
    async def transcriptions(
        file: Annotated[UploadFile, File()],
        model: Annotated[str | None, Form()] = None,
        language: Annotated[str | None, Form()] = None,
        prompt: Annotated[str | None, Form(max_length=2000)] = None,
        response_format: Annotated[str, Form()] = "json",
        temperature: Annotated[float | None, Form()] = None,
    ) -> Response | dict[str, Any]:
        del model, temperature  # one model per service; decoding is deterministic
        if state.engine is None:
            return _error(503, f"The speech model is not ready ({state.status}).", "not_ready")
        if file.size is not None and file.size > state.config.max_bytes:
            return _error(413, "The recording is too large.", "too_large")
        lang = (language or "").strip().lower() or None
        if lang is not None and not _LANG.match(lang):
            return _error(400, "language must be an ISO-639-1 code such as ru or en.", "invalid")
        if response_format not in ("json", "text", "verbose_json"):
            return _error(400, "response_format must be json, text or verbose_json.", "invalid")
        engine = state.engine
        async with state.gate:
            started = time.monotonic()
            try:
                result = await asyncio.to_thread(engine.transcribe, file.file, lang, prompt)
            except ValueError as exc:
                return _error(400, f"The audio cannot be read: {exc}"[:300], "invalid_audio")
            except Exception as exc:
                log.exception("transcription failed")
                return _error(500, f"Transcription failed: {type(exc).__name__}", "server_error")
        log.info(
            "transcribed %.1fs of audio (%s) in %.2fs",
            result.duration,
            result.language,
            time.monotonic() - started,
        )
        if response_format == "text":
            return PlainTextResponse(result.text)
        return {"text": result.text, "language": result.language, "duration": result.duration}

    return app
