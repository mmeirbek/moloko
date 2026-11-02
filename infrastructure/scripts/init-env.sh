#!/usr/bin/env bash
# Create .env from .env.example with freshly generated secrets. Never overwrites.
#   init-env.sh                create .env
#   init-env.sh --add-missing  add keys that newer versions need to an existing .env
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

gen() { openssl rand -hex 32; }
docker_gid() { stat -c %g /var/run/docker.sock 2>/dev/null || echo 999; }
# This server's Tailscale name (moloko.<tailnet>.ts.net) for passkeys; empty if unknown.
tailnet_name() {
  local name
  command -v tailscale >/dev/null || return 0
  name="$(tailscale status --json 2>/dev/null \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip(".").lower())' 2>/dev/null || true)"
  if [[ "$name" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ && "$name" == *.* ]]; then echo "$name"; fi
  return 0
}
umask 077

if [[ "${1:-}" == "--add-missing" ]]; then
  [[ -e .env ]] || { echo "No .env yet: run without --add-missing." >&2; exit 1; }
  if ! grep -qE '^SANDBOX_RUNNER_TOKEN=.+' .env; then
    sed -i '/^SANDBOX_RUNNER_TOKEN=/d' .env
    echo "SANDBOX_RUNNER_TOKEN=$(gen)" >> .env
    echo "Added SANDBOX_RUNNER_TOKEN."
  fi
  # Sandbox values copied from an older .env.example → today's defaults (the command image
  # with Node.js and git, room for npm/builds). A value changed by hand is left alone.
  new_default() {  # key old new
    if grep -qxF "$1=$2" .env; then
      sed -i "s|^$1=$2\$|$1=$3|" .env
      echo "Updated $1: $2 → $3 (new default)."
    fi
  }
  new_default SANDBOX_IMAGE python:3.12.16-slim moloko-sandbox:local
  new_default SANDBOX_MEMORY_MB 512 2048
  new_default SANDBOX_PIDS_LIMIT 128 512
  new_default SANDBOX_TIMEOUT_SECONDS 60 600
  new_default SANDBOX_PACKAGE_HOSTS registry.npmjs.org,pypi.org,files.pythonhosted.org registry.npmjs.org,pypi.org,files.pythonhosted.org,cdn.playwright.dev,playwright.download.prss.microsoft.com
  if ! grep -q '^DOCKER_GID=' .env; then
    echo "DOCKER_GID=$(docker_gid)" >> .env
    echo "Added DOCKER_GID."
  fi
  if ! grep -q '^WEBAUTHN_RP_ID=' .env; then
    # Passkeys (Face ID / Touch ID) are bound to the site's ts.net name; empty = off.
    name="$(tailnet_name)"
    sed -i '/^WEBAUTHN_ORIGINS=/d' .env
    echo "WEBAUTHN_RP_ID=$name" >> .env
    echo "WEBAUTHN_ORIGINS=${name:+https://$name}" >> .env
    if [[ -n "$name" ]]; then
      echo "Added WEBAUTHN_RP_ID / WEBAUTHN_ORIGINS (passkeys) for https://$name."
    else
      echo "Added empty WEBAUTHN_RP_ID / WEBAUTHN_ORIGINS (passkeys off): set them to moloko's ts.net address."
    fi
  fi
  exit 0
fi

if [[ -e .env ]]; then
  echo ".env already exists — leaving it untouched (use --add-missing for new keys)." >&2
  exit 1
fi

name="$(tailnet_name)"
sed \
  -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(gen)|" \
  -e "s|^SECRET_KEY=.*|SECRET_KEY=$(gen)|" \
  -e "s|^APP_ENCRYPTION_KEY=.*|APP_ENCRYPTION_KEY=$(gen)|" \
  -e "s|^SANDBOX_RUNNER_TOKEN=.*|SANDBOX_RUNNER_TOKEN=$(gen)|" \
  -e "s|^DOCKER_GID=.*|DOCKER_GID=$(docker_gid)|" \
  -e "s|^WEBAUTHN_RP_ID=.*|WEBAUTHN_RP_ID=$name|" \
  -e "s|^WEBAUTHN_ORIGINS=.*|WEBAUTHN_ORIGINS=${name:+https://$name}|" \
  .env.example > .env
echo "Created .env (mode 600) with new secrets. Back it up somewhere safe."
