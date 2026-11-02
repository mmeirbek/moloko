"""moloko speech-to-text: Whisper (faster-whisper / CTranslate2, int8 on CPU) behind an
OpenAI-compatible ``POST /v1/audio/transcriptions``. Runs on the internal Docker network
only; the model is downloaded once by ``python -m stt_server download`` (the
``stt-models`` compose service; docs/deployment.md, section 8b)."""
