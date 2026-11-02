#!/usr/bin/env bash
# Restore a backup. REPLACES the current data. Usage:
#   restore.sh backups/daily/moloko-YYYYmmdd-HHMMSS.dump [backups/daily/workspaces-….tar.gz]
# (For a copy from the off-site repository: offsite-restore.sh <ID> --replace.)
set -euo pipefail
cd "$(dirname "$0")/../.."
# MOLOKO_ENV_FILE: another env file than ./.env (optional).
ENV_ARGS=()
[[ -n "${MOLOKO_ENV_FILE:-}" ]] && ENV_ARGS=(--env-file "$MOLOKO_ENV_FILE")
compose() { docker compose ${ENV_ARGS[@]+"${ENV_ARGS[@]}"} "$@"; }
# Backup files belong to root (the backup container writes them, owner-only): read them
# through a throwaway container instead of needing sudo.
HELPER=postgres:17.11-alpine
as_root() { docker run --rm --network none "$@"; }
# The agents' workspaces volume (WORKSPACES_VOLUME in the env file, as in docker-compose.yml).
WORKSPACES_VOLUME="$(grep -E '^WORKSPACES_VOLUME=' "${MOLOKO_ENV_FILE:-.env}" 2> /dev/null | tail -1 | cut -d= -f2- || true)"
WORKSPACES_VOLUME="${WORKSPACES_VOLUME:-moloko_workspaces}"
# Chat attachments (FILES_VOLUME, likewise).
FILES_VOLUME="$(grep -E '^FILES_VOLUME=' "${MOLOKO_ENV_FILE:-.env}" 2> /dev/null | tail -1 | cut -d= -f2- || true)"
FILES_VOLUME="${FILES_VOLUME:-moloko_files}"

DUMP="${1:?give the .dump file}"
FILES="${2:-}"
[[ -f "$DUMP" ]] || { echo "No such file: $DUMP" >&2; exit 1; }
[[ -z "$FILES" || -f "$FILES" ]] || { echo "No such file: $FILES" >&2; exit 1; }
DUMP="$(realpath "$DUMP")"
[[ -z "$FILES" ]] || FILES="$(realpath "$FILES")"
for file in "$DUMP" ${FILES:+"$FILES"}; do
  if [[ -f "$file.sha256" ]]; then
    as_root -v "$(dirname "$file"):/r:ro" -w /r "$HELPER" sha256sum -c "$(basename "$file").sha256"
  fi
done

echo "This replaces ALL current moloko data with the backup $(basename "$DUMP")."
read -r -p "Type RESTORE to continue: " answer
[[ "$answer" == "RESTORE" ]] || { echo "Cancelled."; exit 1; }

compose stop backend worker frontend
swapped=0
trap '[[ "$swapped" == 1 ]] || { echo "Restore failed: the current data is unchanged. Starting moloko again." >&2; compose up -d; }' EXIT
psql_admin() { # SQL on stdin, run against the maintenance database; :db = the app's database
  compose exec -T postgres sh -c 'psql -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres -v db="$POSTGRES_DB"'
}
# Restore into a fresh database first, so the result is exactly the backup (no tables left
# over from a newer version) and the live data stays untouched if anything fails. Only then
# swap it in; the previous data is kept as <db>_before_restore until the next restore.
psql_admin <<'SQL'
\set restoring :db _restoring
SET client_min_messages TO warning;
DROP DATABASE IF EXISTS :"restoring";
CREATE DATABASE :"restoring";
SQL
as_root -v "$DUMP:/restore.dump:ro" "$HELPER" cat /restore.dump \
  | compose exec -T postgres sh -c 'pg_restore --no-owner -U "$POSTGRES_USER" -d "${POSTGRES_DB}_restoring"'
psql_admin <<'SQL'
\set restoring :db _restoring
\set previous :db _before_restore
\o /dev/null
SET client_min_messages TO warning;
DROP DATABASE IF EXISTS :"previous";
SELECT pg_terminate_backend(pid, 5000) FROM pg_stat_activity WHERE datname = :'db' AND pid <> pg_backend_pid();
ALTER DATABASE :"db" RENAME TO :"previous";
ALTER DATABASE :"restoring" RENAME TO :"db";
SQL
swapped=1
echo "The data from before the restore is kept as the database …_before_restore (the next restore removes it)."
if [[ -n "$FILES" ]]; then
  # The archive holds workspaces/ and (since chat files moved to disk) files/.
  docker run --rm --network none -v "$WORKSPACES_VOLUME:/data/workspaces" -v "$FILES_VOLUME:/data/files" \
    -v "$FILES:/restore.tar.gz:ro" "$HELPER" \
    sh -c 'rm -rf /data/workspaces/* && if tar -tzf /restore.tar.gz files >/dev/null 2>&1; then rm -rf /data/files/*; fi && tar -xzf /restore.tar.gz -C /data'
fi
compose up -d
echo "Restored. Check the app, then the audit log."
