#!/usr/bin/env bash
# Backend checks against throwaway PostgreSQL + Redis containers:
#   ruff (lint + format), mypy (strict), pytest, OpenAPI drift.
# Usage: infrastructure/scripts/test-api.sh [extra pytest args]
# Set TEST_DATABASE_URL and TEST_REDIS_URL to use existing services instead (CI does).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT/apps/api"

PG_IMAGE="pgvector/pgvector:0.8.1-pg17-trixie"  # PostgreSQL 17 + pgvector
REDIS_IMAGE="valkey/valkey:9.1.3-alpine"  # Redis-compatible (BSD-3)
PG_NAME="moloko-test-pg-$$"
REDIS_NAME="moloko-test-redis-$$"

cleanup() {
  docker rm -f "$PG_NAME" "$REDIS_NAME" >/dev/null 2>&1 || true
}

if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  trap cleanup EXIT
  echo "→ starting throwaway PostgreSQL and Redis"
  docker run -d --rm --name "$PG_NAME" -e POSTGRES_USER=moloko -e POSTGRES_PASSWORD=moloko \
    -e POSTGRES_DB=moloko_test -p 127.0.0.1::5432 "$PG_IMAGE" >/dev/null
  docker run -d --rm --name "$REDIS_NAME" -p 127.0.0.1::6379 "$REDIS_IMAGE" >/dev/null
  PG_PORT="$(docker port "$PG_NAME" 5432/tcp | head -n1 | awk -F: '{print $NF}')"
  REDIS_PORT="$(docker port "$REDIS_NAME" 6379/tcp | head -n1 | awk -F: '{print $NF}')"
  for _ in $(seq 1 60); do
    docker exec "$PG_NAME" pg_isready -U moloko -d moloko_test >/dev/null 2>&1 && break
    sleep 1
  done
  export TEST_DATABASE_URL="postgresql+asyncpg://moloko:moloko@127.0.0.1:${PG_PORT}/moloko_test"
  export TEST_REDIS_URL="redis://127.0.0.1:${REDIS_PORT}/15"
fi

echo "→ uv sync";            uv sync --frozen
echo "→ ruff check";         uv run ruff check .
echo "→ ruff format --check"; uv run ruff format --check .
echo "→ mypy";               uv run mypy app tests
echo "→ OpenAPI drift";      uv run python scripts/export_openapi.py --check
echo "→ pytest";             uv run pytest -q "$@"
