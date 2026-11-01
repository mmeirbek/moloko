#!/bin/sh
# One backup run (spec 21.3): PostgreSQL dump + workspace files, checksums, integrity
# check, rotation, status file. Runs inside the `backup` service (postgres image).
#   /backups/daily/moloko-YYYYmmdd-HHMMSS.dump(.sha256)   pg_dump custom format
#   /backups/daily/workspaces-YYYYmmdd-HHMMSS.tar.gz(.sha256)
#   /backups/weekly/…                                      copies made on Sundays
#   /backups/status.json                                   last run, read by the app
set -eu

ROOT=/backups
KEEP_DAILY="${BACKUP_KEEP_DAILY:-7}"
KEEP_WEEKLY="${BACKUP_KEEP_WEEKLY:-4}"
TS="$(date -u +%Y%m%d-%H%M%S)"
mkdir -p "$ROOT/daily" "$ROOT/weekly"

fail() {
  printf '{"ok": false, "at": "%s", "error": "%s"}\n' "$(date -u +%FT%TZ)" "$1" > "$ROOT/status.json.tmp"
  mv "$ROOT/status.json.tmp" "$ROOT/status.json"
  echo "backup failed: $1" >&2
  exit 1
}

DUMP="$ROOT/daily/moloko-$TS.dump"
pg_dump -Fc --no-owner -f "$DUMP.tmp" || fail "pg_dump failed"
pg_restore --list "$DUMP.tmp" > /dev/null || fail "the dump cannot be read back"
mv "$DUMP.tmp" "$DUMP"
(cd "$ROOT/daily" && sha256sum "$(basename "$DUMP")" > "$(basename "$DUMP").sha256")

FILES="$ROOT/daily/workspaces-$TS.tar.gz"
if [ -d /data/workspaces ]; then
  tar -czf "$FILES.tmp" -C /data workspaces || fail "workspace archive failed"
  gzip -t "$FILES.tmp" || fail "the workspace archive is corrupt"
  mv "$FILES.tmp" "$FILES"
  (cd "$ROOT/daily" && sha256sum "$(basename "$FILES")" > "$(basename "$FILES").sha256")
fi

if [ "$(date -u +%u)" = "7" ]; then  # Sunday: keep a weekly copy
  cp "$DUMP" "$DUMP.sha256" "$ROOT/weekly/"
  [ -f "$FILES" ] && cp "$FILES" "$FILES.sha256" "$ROOT/weekly/"
fi

prune() {  # keep the newest $2 sets in $1
  ls -1t "$1"/moloko-*.dump 2>/dev/null | tail -n +"$(( $2 + 1 ))" | while read -r old; do
    stamp="$(basename "$old" .dump | sed 's/^moloko-//')"
    rm -f "$1/moloko-$stamp.dump" "$1/moloko-$stamp.dump.sha256" \
          "$1/workspaces-$stamp.tar.gz" "$1/workspaces-$stamp.tar.gz.sha256"
  done
}
prune "$ROOT/daily" "$KEEP_DAILY"
prune "$ROOT/weekly" "$KEEP_WEEKLY"

DUMP_SIZE="$(stat -c %s "$DUMP")"
FILES_SIZE="$( [ -f "$FILES" ] && stat -c %s "$FILES" || echo 0)"
printf '{"ok": true, "at": "%s", "database": "%s", "database_bytes": %s, "files": "%s", "files_bytes": %s}\n' \
  "$(date -u +%FT%TZ)" "$(basename "$DUMP")" "$DUMP_SIZE" "$( [ -f "$FILES" ] && basename "$FILES")" "$FILES_SIZE" \
  > "$ROOT/status.json.tmp"
mv "$ROOT/status.json.tmp" "$ROOT/status.json"
echo "backup ok: $DUMP ($DUMP_SIZE bytes)"
