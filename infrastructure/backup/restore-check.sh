#!/bin/sh
# Restore drill (spec 21.3 "periodically test a restore"): restore a dump into a scratch
# database next to the real one, compare key row counts, drop it. Never touches the live
# database.
#   restore-check.sh                         the newest local dump → /backups/last-drill.json
#   restore-check.sh DUMP RESULT DB [EXTRA]  a given dump (offsite.sh drill: a copy restored
#                                            from off-site) → /backups/RESULT, scratch database
#                                            DB; EXTRA = more JSON members for the result
set -eu

ROOT=/backups
DUMP="${1:-$(ls -1t "$ROOT"/daily/moloko-*.dump 2>/dev/null | head -n 1 || true)}"
RESULT="${2:-last-drill.json}"
CHECK_DB="${3:-moloko_restore_check}"
EXTRA="${4:-}"
case "$CHECK_DB" in "" | *[!a-z0-9_]*) echo "bad scratch database name" >&2; exit 2 ;; esac
case "$RESULT" in "" | */* | *[!a-z0-9.-]*) echo "bad result file name" >&2; exit 2 ;; esac

result() {
  printf '{"ok": %s, "at": "%s", "dump": "%s", %s"detail": "%s"}\n' "$1" "$(date -u +%FT%TZ)" "$(basename "${DUMP:-none}")" "$EXTRA" "$2" \
    > "$ROOT/$RESULT.tmp"
  mv "$ROOT/$RESULT.tmp" "$ROOT/$RESULT"
  chmod 644 "$ROOT/$RESULT"
}

[ -n "$DUMP" ] && [ -f "$DUMP" ] || { result false "no backup to test"; exit 1; }
(cd "$(dirname "$DUMP")" && sha256sum -c "$(basename "$DUMP").sha256" > /dev/null) || { result false "checksum mismatch"; exit 1; }

psql -q -d postgres -c "DROP DATABASE IF EXISTS $CHECK_DB" > /dev/null
psql -q -d postgres -c "CREATE DATABASE $CHECK_DB" > /dev/null
trap 'psql -q -d postgres -c "DROP DATABASE IF EXISTS $CHECK_DB" > /dev/null' EXIT
pg_restore --no-owner -d "$CHECK_DB" "$DUMP" || { result false "pg_restore failed"; exit 1; }

counts=""
for table in users agents tasks agent_events audit_logs alembic_version; do
  n="$(psql -At -d "$CHECK_DB" -c "SELECT count(*) FROM $table")" || { result false "table $table missing"; exit 1; }
  counts="$counts $table=$n"
done
[ "$(psql -At -d "$CHECK_DB" -c 'SELECT count(*) FROM users')" -ge 1 ] || { result false "no owner account in the backup"; exit 1; }
result true "restored:$counts"
echo "restore drill ok ($(basename "$DUMP")):$counts"
