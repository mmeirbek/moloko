"""Whisper on the CPU (faster-whisper / CTranslate2). One loaded model; calls are blocking
and run in a worker thread (the API limits how many run at once)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, BinaryIO, Protocol

from stt_server.catalog import model_dir
from stt_server.config import Config

log = logging.getLogger("stt")


@dataclass(frozen=True)
class Transcription:
    text: str
    language: str | None
    duration: float


class Engine(Protocol):
    def transcribe(
        self, audio: BinaryIO, language: str | None, prompt: str | None
    ) -> Transcription: ...


SAMPLE_RATE = 16000


def decode_audio(audio: BinaryIO) -> Any:
    """Any recording FFmpeg can read (webm/opus, mp4/aac, ogg, wav, mp3…) → 16 kHz mono
    float32 samples. Our own version of faster-whisper's helper, which passes an option
    the pinned PyAV no longer has. Raises ValueError for a file that is not audio."""
    import av
    import numpy as np

    resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
    chunks: list[Any] = []
    try:
        with av.open(audio, mode="r") as container:
            if not container.streams.audio:
                raise ValueError("no audio stream")
            try:
                for frame in container.decode(audio=0):
                    chunks.extend(o.to_ndarray().reshape(-1) for o in resampler.resample(frame))
            except av.FFmpegError:
                if not chunks:  # a cut-off recording keeps what was decoded before
                    raise
            chunks.extend(o.to_ndarray().reshape(-1) for o in resampler.resample(None))
    except av.FFmpegError as exc:
        raise ValueError(str(exc)) from exc
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks).astype(np.float32) / 32768.0


def pick_language(
    probs: list[tuple[str, float]], allowed: tuple[str, ...]
) -> tuple[str | None, float]:
    """The most likely language among `allowed` (all of them if `allowed` is empty)."""
    ranked = sorted(probs, key=lambda item: item[1], reverse=True)
    for code, prob in ranked:
        if not allowed or code in allowed:
            return code, prob
    return (allowed[0] if allowed else None), 0.0


class WhisperEngine:
    def __init__(self, config: Config) -> None:
        from faster_whisper import WhisperModel

        self.config = config
        self.model: Any = WhisperModel(
            str(model_dir(config.models_dir, config.model)),
            device="cpu",
            compute_type=config.compute_type,
            cpu_threads=config.cpu_threads,
            num_workers=config.concurrency,
            local_files_only=True,
        )

    def _language(self, audio: Any, language: str | None) -> str | None:
        allowed = self.config.languages
        if language:
            return language
        if len(allowed) == 1:
            return allowed[0]
        if not allowed:
            return None  # Whisper's own detection over all languages
        try:
            _, _, probs = self.model.detect_language(
                audio, vad_filter=self.config.vad, language_detection_segments=2
            )
        except ValueError:  # no speech found by the VAD
            return allowed[0]
        code, prob = pick_language(list(probs), allowed)
        log.info("language %s (p=%.2f)", code, prob)
        return code

    def transcribe(
        self, audio: BinaryIO, language: str | None, prompt: str | None
    ) -> Transcription:
        samples = decode_audio(audio)
        duration = len(samples) / 16000
        if duration < 0.2:
            return Transcription("", language, duration)
        lang = self._language(samples, language)
        segments, info = self.model.transcribe(
            samples,
            language=lang,
            beam_size=self.config.beam_size,
            vad_filter=self.config.vad,
            initial_prompt=prompt or None,
            # Dictation: each segment on its own — avoids Whisper's repetition loops.
            condition_on_previous_text=False,
        )
        text = " ".join(s.text.strip() for s in segments if s.text.strip())
        return Transcription(text, info.language, duration)
