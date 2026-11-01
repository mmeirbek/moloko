#!/bin/sh
# Restore drill (spec 21.3 "periodically test a restore"): restore the newest dump into a
# scratch database next to the real one, compare key row counts, drop it. Never touches
# the live database. Result in /backups/last-drill.json.
set -eu

ROOT=/backups
CHECK_DB=moloko_restore_check
DUMP="$(ls -1t "$ROOT"/daily/moloko-*.dump 2>/dev/null | head -n 1 || true)"

result() {
  printf '{"ok": %s, "at": "%s", "dump": "%s", "detail": "%s"}\n' "$1" "$(date -u +%FT%TZ)" "$(basename "${DUMP:-none}")" "$2" \
    > "$ROOT/last-drill.json.tmp"
  mv "$ROOT/last-drill.json.tmp" "$ROOT/last-drill.json"
}

[ -n "$DUMP" ] || { result false "no backup to test"; exit 1; }
(cd "$ROOT/daily" && sha256sum -c "$(basename "$DUMP").sha256" > /dev/null) || { result false "checksum mismatch"; exit 1; }

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
echo "restore drill ok:$counts"
