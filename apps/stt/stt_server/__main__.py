"""Commands:

python -m stt_server serve       the HTTP API (port STT_PORT, default 8000)
python -m stt_server download    fetch STT_MODEL once (needs the internet), then exit
python -m stt_server bench F...  transcribe audio files with STT_MODEL and print timings
"""

from __future__ import annotations

import io
import logging
import os
import sys
import time

from stt_server.config import Config


def _download(config: Config) -> int:
    from stt_server.catalog import download

    try:
        download(config.models_dir, config.model)
    except Exception as exc:  # noqa: BLE001
        # Never block the rest of moloko: voice falls back to the provider (if any) and the
        # next `docker compose up` tries again. STT_DOWNLOAD_STRICT=1 makes this an error.
        logging.getLogger("stt").error("model download failed: %s", exc)
        return 1 if os.environ.get("STT_DOWNLOAD_STRICT") == "1" else 0
    return 0


def _bench(config: Config, files: list[str]) -> int:
    from stt_server.engine import WhisperEngine

    started = time.monotonic()
    engine = WhisperEngine(config)
    print(f"model {config.model} loaded in {time.monotonic() - started:.1f}s", flush=True)
    language = os.environ.get("BENCH_LANGUAGE") or None
    for path in files:
        # "-" = the recording on stdin: docker compose exec -T stt … bench - < voice.webm
        source = io.BytesIO(sys.stdin.buffer.read()) if path == "-" else open(path, "rb")  # noqa: SIM115
        with source as fh:
            started = time.monotonic()
            result = engine.transcribe(fh, language, None)
        took = time.monotonic() - started
        print(
            f"{path}\t{result.duration:.1f}s audio\t{took:.2f}s\t{result.language}\t{result.text}"
        )
    print(f"encoder runs saved by reuse: {engine.encoder.hits}")
    return 0


def main(argv: list[str]) -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"), format="%(levelname)s %(message)s"
    )
    command = argv[1] if len(argv) > 1 else "serve"
    config = Config.from_env()
    if command == "download":
        return _download(config)
    if command == "bench":
        return _bench(config, argv[2:])
    if command == "serve":
        import uvicorn

        from stt_server.app import create_app

        uvicorn.run(
            create_app(config),
            host=os.environ.get("STT_HOST", "0.0.0.0"),  # noqa: S104 — container network only
            port=int(os.environ.get("STT_PORT", "8000")),
            server_header=False,
            log_level=os.environ.get("LOG_LEVEL", "info").lower(),
        )
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
