#!/usr/bin/env bash
# Speech-to-text service checks (apps/stt): ruff, mypy, pytest. No model download needed.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT/apps/stt"

echo "→ uv sync";             uv sync --frozen
echo "→ ruff check";          uv run ruff check .
echo "→ ruff format --check"; uv run ruff format --check .
echo "→ mypy";                uv run mypy stt_server tests
echo "→ pytest";              uv run pytest -q "$@"
