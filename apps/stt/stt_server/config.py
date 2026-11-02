"""Settings from the environment (nothing hardcoded: compose and .env set them)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else default


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    return float(raw) if raw else default


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    return default if not raw else raw in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Config:
    model: str
    models_dir: Path
    compute_type: str
    cpu_threads: int
    beam_size: int
    vad: bool
    # Auto-detection picks only among these (Whisper alone sometimes hears Russian as
    # Ukrainian or Kazakh). Empty = any language Whisper knows.
    languages: tuple[str, ...]
    max_bytes: int
    concurrency: int
    poll_seconds: float

    @classmethod
    def from_env(cls) -> Config:
        langs = os.environ.get("STT_LANGUAGES", "ru,en")
        return cls(
            model=os.environ.get("STT_MODEL", "").strip() or "large-v3-turbo",
            models_dir=Path(os.environ.get("STT_MODELS_DIR", "/models")),
            compute_type=os.environ.get("STT_COMPUTE_TYPE", "").strip() or "int8",
            cpu_threads=_int("STT_CPU_THREADS", 0),
            beam_size=max(1, _int("STT_BEAM_SIZE", 1)),
            vad=_bool("STT_VAD", True),
            languages=tuple(x.strip().lower() for x in langs.split(",") if x.strip()),
            max_bytes=_int("STT_MAX_BYTES", 300_000_000),
            concurrency=max(1, _int("STT_CONCURRENCY", 1)),
            poll_seconds=max(1.0, _float("STT_MODEL_POLL_SECONDS", 15.0)),
        )
