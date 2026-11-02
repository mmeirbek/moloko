# syntax=docker/dockerfile:1
# moloko speech-to-text (apps/stt): faster-whisper on the CPU behind an OpenAI-compatible
# API. Build context: repository root. linux/amd64 and linux/arm64.
# The model is NOT baked in: the `stt-models` service downloads it once into a volume.

FROM python:3.12.16-slim AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
RUN pip install --no-cache-dir uv==0.11.32
WORKDIR /app
COPY apps/stt/pyproject.toml apps/stt/uv.lock apps/stt/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY apps/stt/stt_server ./stt_server
RUN uv sync --frozen --no-dev

FROM python:3.12.16-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    HF_HUB_DISABLE_TELEMETRY=1 \
    HF_HUB_DISABLE_XET=1 \
    HF_HOME=/models/.hf-home \
    STT_MODELS_DIR=/models
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /models && chown app:app /models
WORKDIR /app
COPY --from=builder --chown=root:root /app /app
USER app
EXPOSE 8000
ENTRYPOINT ["python", "-m", "stt_server"]
CMD ["serve"]
