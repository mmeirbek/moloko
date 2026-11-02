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
