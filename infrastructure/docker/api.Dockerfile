# syntax=docker/dockerfile:1
# moloko backend (FastAPI). Build context: repository root.

FROM python:3.12.16-slim AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
RUN pip install --no-cache-dir uv==0.11.32
WORKDIR /app
# Dependencies first (cached layer), then the project itself.
COPY apps/api/pyproject.toml apps/api/uv.lock apps/api/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY apps/api/ ./
RUN uv sync --frozen --no-dev

FROM python:3.12.16-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /data/workspaces && chown app:app /data/workspaces
WORKDIR /app
COPY --from=builder --chown=root:root /app /app
USER app
EXPOSE 8000
ENTRYPOINT ["/app/scripts/entrypoint.sh"]
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--no-server-header", "--timeout-graceful-shutdown", "20"]
