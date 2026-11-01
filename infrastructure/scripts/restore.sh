#!/usr/bin/env bash
# Restore a backup. REPLACES the current data. Usage:
#   restore.sh backups/daily/moloko-YYYYmmdd-HHMMSS.dump [backups/daily/workspaces-….tar.gz]
set -euo pipefail
cd "$(dirname "$0")/../.."
# MOLOKO_ENV_FILE: another env file than ./.env (optional).
ENV_ARGS=()
[[ -n "${MOLOKO_ENV_FILE:-}" ]] && ENV_ARGS=(--env-file "$MOLOKO_ENV_FILE")
compose() { docker compose "${ENV_ARGS[@]}" "$@"; }

DUMP="${1:?give the .dump file}"
FILES="${2:-}"
[[ -f "$DUMP" ]] || { echo "No such file: $DUMP" >&2; exit 1; }
if [[ -f "$DUMP.sha256" ]]; then
  (cd "$(dirname "$DUMP")" && sha256sum -c "$(basename "$DUMP").sha256")
fi

echo "This replaces ALL current moloko data with the backup $(basename "$DUMP")."
read -r -p "Type RESTORE to continue: " answer
[[ "$answer" == "RESTORE" ]] || { echo "Cancelled."; exit 1; }

compose stop backend worker frontend
compose exec -T postgres sh -c 'pg_restore --clean --if-exists --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < "$DUMP"
if [[ -n "$FILES" ]]; then
  [[ -f "$FILES" ]] || { echo "No such file: $FILES" >&2; exit 1; }
  docker run --rm -v moloko_workspaces:/data/workspaces -v "$(realpath "$FILES"):/restore.tar.gz:ro" \
    postgres:17.11-alpine sh -c 'rm -rf /data/workspaces/* && tar -xzf /restore.tar.gz -C /data'
fi
compose up -d
echo "Restored. Check the app, then the audit log."
