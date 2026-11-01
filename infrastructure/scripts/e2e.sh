#!/usr/bin/env bash
# Browser tests against a throwaway moloko stack (its own compose project, ports, volumes).
#   infrastructure/scripts/e2e.sh            build, start, test, tear down
#   KEEP=1 infrastructure/scripts/e2e.sh     leave the stack running afterwards
#   NO_BUILD=1 …                             use already built images
# Needs Docker and Node. Uses the offline mock provider (no API key, no cost).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
PROJECT="moloko-e2e"
PORT="${E2E_PORT:-18080}"
WORK="$(mktemp -d)"
ENV_FILE="$WORK/e2e.env"
gen() { openssl rand -hex 32; }

cat > "$ENV_FILE" <<ENV
POSTGRES_PASSWORD=$(gen)
SECRET_KEY=$(gen)
APP_ENCRYPTION_KEY=$(gen)
SANDBOX_RUNNER_TOKEN=$(gen)
DOCKER_GID=$(stat -c %g /var/run/docker.sock 2>/dev/null || echo 999)
HTTP_BIND=127.0.0.1
HTTP_PORT=$PORT
COOKIE_SECURE=false
ENABLE_MOCK_PROVIDER=true
WORKSPACES_VOLUME=moloko_e2e_workspaces
BROWSER_NETWORK=moloko_e2e_browser
BACKUP_DIR=$WORK/backups
ENV
mkdir -p "$WORK/backups"

compose() { docker compose -p "$PROJECT" --env-file "$ENV_FILE" "$@"; }
cleanup() {
  if [[ "${KEEP:-0}" != "1" ]]; then
    compose down -v --remove-orphans >/dev/null 2>&1 || true
    docker volume rm moloko_e2e_workspaces >/dev/null 2>&1 || true
    rm -rf "$WORK"
  else
    echo "Stack kept: http://127.0.0.1:$PORT (env: $ENV_FILE)"
  fi
}
trap cleanup EXIT

if [[ "${NO_BUILD:-0}" == "1" ]]; then compose up -d --no-build --wait; else compose up -d --build --wait; fi
export E2E_USERNAME=owner E2E_PASSWORD="e2e owner password 123"
printf '%s\n' "$E2E_PASSWORD" | compose exec -T backend python -m app.cli create-owner \
  --username "$E2E_USERNAME" --display-name Owner --password-stdin

export E2E_COMPOSE="docker compose -p $PROJECT --env-file $ENV_FILE"  # recovery tests restart services
cd e2e
E2E_BASE_URL="http://127.0.0.1:$PORT" npx playwright test "$@"
