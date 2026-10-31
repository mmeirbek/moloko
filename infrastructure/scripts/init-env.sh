#!/usr/bin/env bash
# Create .env from .env.example with freshly generated secrets. Never overwrites.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

if [[ -e .env ]]; then
  echo ".env already exists — leaving it untouched." >&2
  exit 1
fi

gen() { openssl rand -hex 32; }
umask 077
sed \
  -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(gen)|" \
  -e "s|^SECRET_KEY=.*|SECRET_KEY=$(gen)|" \
  -e "s|^APP_ENCRYPTION_KEY=.*|APP_ENCRYPTION_KEY=$(gen)|" \
  .env.example > .env
echo "Created .env (mode 600) with new secrets. Back it up somewhere safe."
