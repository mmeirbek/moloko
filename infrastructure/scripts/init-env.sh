#!/usr/bin/env bash
# Create .env from .env.example with freshly generated secrets. Never overwrites.
#   init-env.sh                create .env
#   init-env.sh --add-missing  add keys that newer versions need to an existing .env
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

gen() { openssl rand -hex 32; }
docker_gid() { stat -c %g /var/run/docker.sock 2>/dev/null || echo 999; }
umask 077

if [[ "${1:-}" == "--add-missing" ]]; then
  [[ -e .env ]] || { echo "No .env yet: run without --add-missing." >&2; exit 1; }
  if ! grep -qE '^SANDBOX_RUNNER_TOKEN=.+' .env; then
    sed -i '/^SANDBOX_RUNNER_TOKEN=/d' .env
    echo "SANDBOX_RUNNER_TOKEN=$(gen)" >> .env
    echo "Added SANDBOX_RUNNER_TOKEN."
  fi
  if ! grep -q '^DOCKER_GID=' .env; then
    echo "DOCKER_GID=$(docker_gid)" >> .env
    echo "Added DOCKER_GID."
  fi
  exit 0
fi

if [[ -e .env ]]; then
  echo ".env already exists — leaving it untouched (use --add-missing for new keys)." >&2
  exit 1
fi

sed \
  -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(gen)|" \
  -e "s|^SECRET_KEY=.*|SECRET_KEY=$(gen)|" \
  -e "s|^APP_ENCRYPTION_KEY=.*|APP_ENCRYPTION_KEY=$(gen)|" \
  -e "s|^SANDBOX_RUNNER_TOKEN=.*|SANDBOX_RUNNER_TOKEN=$(gen)|" \
  -e "s|^DOCKER_GID=.*|DOCKER_GID=$(docker_gid)|" \
  .env.example > .env
echo "Created .env (mode 600) with new secrets. Back it up somewhere safe."
