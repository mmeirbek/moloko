#!/usr/bin/env bash
# Browser tests against a throwaway moloko stack (its own compose project, ports, volumes).
#   infrastructure/scripts/e2e.sh            build, start, test, tear down
#   KEEP=1 infrastructure/scripts/e2e.sh     leave the stack running afterwards
#   NO_BUILD=1 …                             use already built images
#   E2E_STT=1 STT_MODELS_FROM=<docker volume> …  real speech recognition: the local STT service
#                                            with a model copied from that volume (no download)
# Needs Docker and Node. Uses the offline mock provider (no API key, no cost).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
PROJECT="moloko-e2e"
PORT="${E2E_PORT:-18080}"
WORK="$(mktemp -d)"
ENV_FILE="$WORK/e2e.env"
gen() { openssl rand -hex 32; }

# The sandbox needs the Docker socket's group. Docker Desktop / colima on a Mac: the group
# inside the VM differs from the host's — pass it, e.g. DOCKER_GID=991 infrastructure/scripts/e2e.sh
DOCKER_GID="${DOCKER_GID:-$(stat -c %g /var/run/docker.sock 2>/dev/null || echo 999)}"
cat > "$ENV_FILE" <<ENV
POSTGRES_PASSWORD=$(gen)
SECRET_KEY=$(gen)
APP_ENCRYPTION_KEY=$(gen)
SANDBOX_RUNNER_TOKEN=$(gen)
DOCKER_GID=$DOCKER_GID
HTTP_BIND=127.0.0.1
HTTP_PORT=$PORT
COOKIE_SECURE=false
ENABLE_MOCK_PROVIDER=true
WORKSPACES_VOLUME=moloko_e2e_workspaces
FILES_VOLUME=moloko_e2e_files
BROWSER_NETWORK=moloko_e2e_browser
PACKAGES_NETWORK=moloko_e2e_packages
STT_URL=$([[ "${E2E_STT:-0}" == "1" ]] && echo "http://stt:8000")
STT_MODEL=${STT_MODEL:-large-v3-turbo}
BACKUP_DIR=$WORK/backups
ENV
mkdir -p "$WORK/backups"

compose() { docker compose -p "$PROJECT" --env-file "$ENV_FILE" "$@"; }
cleanup() {
  if [[ "${KEEP:-0}" != "1" ]]; then
    compose down -v --remove-orphans >/dev/null 2>&1 || true
    docker volume rm moloko_e2e_workspaces moloko_e2e_files >/dev/null 2>&1 || true
    rm -rf "$WORK"
  else
    echo "Stack kept: http://127.0.0.1:$PORT (env: $ENV_FILE)"
  fi
}
trap cleanup EXIT

# No local speech model by default (it is a 1.6 GB download): voice uses the mock provider.
NO_STT=(--scale stt=0 --scale stt-models=0)
if [[ "${E2E_STT:-0}" == "1" ]]; then
  NO_STT=(--scale stt-models=0)
  [[ -n "${STT_MODELS_FROM:-}" ]] || { echo "E2E_STT=1 needs STT_MODELS_FROM=<volume with the model>" >&2; exit 1; }
  model="${STT_MODEL:-large-v3-turbo}"
  compose create stt >/dev/null  # creates the project's stt-models volume
  docker run --rm --network none -v "$STT_MODELS_FROM:/from:ro" -v "${PROJECT}_stt-models:/to" \
    postgres:17.11-alpine sh -c "rm -rf '/to/$model' && cp -a '/from/$model' /to/"
fi
if [[ "${NO_BUILD:-0}" != "1" ]]; then
  compose --profile sandbox-image build sandbox-image  # the image agents' commands run in
fi
if [[ "${NO_BUILD:-0}" == "1" ]]; then compose up -d --no-build --wait "${NO_STT[@]}"; else compose up -d --build --wait "${NO_STT[@]}"; fi
export E2E_USERNAME=owner E2E_PASSWORD="e2e owner password 123"
printf '%s\n' "$E2E_PASSWORD" | compose exec -T backend python -m app.cli create-owner \
  --username "$E2E_USERNAME" --display-name Owner --password-stdin

export E2E_COMPOSE="docker compose -p $PROJECT --env-file $ENV_FILE"  # recovery tests restart services
cd e2e
E2E_BASE_URL="http://127.0.0.1:$PORT" npx playwright test "$@"
