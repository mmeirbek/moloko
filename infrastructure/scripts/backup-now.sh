#!/usr/bin/env bash
# Make a backup now (and optionally test restoring it): backup-now.sh [--check]
set -euo pipefail
cd "$(dirname "$0")/../.."
# MOLOKO_ENV_FILE: another env file than ./.env (optional).
ENV_ARGS=()
[[ -n "${MOLOKO_ENV_FILE:-}" ]] && ENV_ARGS=(--env-file "$MOLOKO_ENV_FILE")
compose() { docker compose "${ENV_ARGS[@]}" "$@"; }
compose exec -T backup sh /scripts/backup.sh
if [[ "${1:-}" == "--check" ]]; then
  compose exec -T backup sh /scripts/restore-check.sh
fi
