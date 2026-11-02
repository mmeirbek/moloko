"""Whisper on the CPU (faster-whisper / CTranslate2). One loaded model; calls are blocking
and run in a worker thread (the API limits how many run at once)."""

from __future__ import annotations

import hashlib
import logging
import threading
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


class EncoderReuse:
    """Language detection and the first decoding window encode the same 30 seconds of
    audio, and the encoder is most of the CPU time. This wraps `WhisperModel.encode` and
    hands the last result back once when the same features come again, so a dictation
    with automatic language detection runs the encoder once instead of twice."""

    def __init__(self, encode: Any) -> None:
        self._encode = encode
        self._local = threading.local()
        self.hits = 0

    def forget(self) -> None:
        self._local.cached = None

    def __call__(self, features: Any) -> Any:
        import numpy as np

        data = np.ascontiguousarray(features)
        key = (data.shape, hashlib.blake2b(data.tobytes(), digest_size=16).digest())
        cached = getattr(self._local, "cached", None)
        self._local.cached = None
        if cached is not None and cached[0] == key:
            self.hits += 1
            return cached[1]
        out = self._encode(features)
        self._local.cached = (key, out)
        return out


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
        self.encoder = EncoderReuse(self.model.encode)
        self.model.encode = self.encoder

    def _language(self, audio: Any, language: str | None) -> str | None:
        allowed = self.config.languages
        if language:
            return language
        if len(allowed) == 1:
            return allowed[0]
        if not allowed:
            return None  # Whisper's own detection over all languages
        extractor = self.model.feature_extractor
        # The first 30 s, cut exactly like transcribe() cuts its first window (it drops
        # the last frame), so EncoderReuse hands that window's encoding back.
        features = extractor(audio[: extractor.n_samples])[:, :-1]
        _, _, probs = self.model.detect_language(features=features, language_detection_segments=1)
        code, prob = pick_language(list(probs), allowed)
        log.info("language %s (p=%.2f)", code, prob)
        return code

    def _speech(self, samples: Any) -> Any:
        """Only the parts with speech (Silero VAD): less to decode, fewer hallucinations."""
        if not self.config.vad:
            return samples
        import numpy as np
        from faster_whisper.vad import VadOptions, collect_chunks, get_speech_timestamps

        chunks = get_speech_timestamps(samples, VadOptions())
        if not chunks:
            return samples[:0]
        parts, _ = collect_chunks(samples, chunks)
        return np.concatenate(parts)

    def transcribe(
        self, audio: BinaryIO, language: str | None, prompt: str | None
    ) -> Transcription:
        self.encoder.forget()
        samples = decode_audio(audio)
        duration = len(samples) / SAMPLE_RATE
        speech = self._speech(samples)
        if len(speech) < 0.2 * SAMPLE_RATE:  # silence
            return Transcription("", language, duration)
        lang = self._language(speech, language)
        segments, info = self.model.transcribe(
            speech,
            language=lang,
            beam_size=self.config.beam_size,
            vad_filter=False,  # done above, once
            initial_prompt=prompt or None,
            # Dictation: each segment on its own — avoids Whisper's repetition loops.
            condition_on_previous_text=False,
        )
        text = " ".join(s.text.strip() for s in segments if s.text.strip())
        return Transcription(text, info.language, duration)
