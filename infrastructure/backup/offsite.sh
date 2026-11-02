#!/bin/sh
# Encrypted off-site copies with restic (spec 21.3; docs/deployment.md, section 6a). Runs in
# the `backup` service. Configured by OFFSITE_* in .env: with neither OFFSITE_REPOSITORY
# (cloud storage, SFTP) nor OFFSITE_DISK (an external disk) set, off-site copies are off and
# the scheduled commands do nothing.
#
#   offsite.sh state            record on/off and the settings for the app (loop.sh, at start)
#   offsite.sh pending          exit 0 when the newest local backup is not off-site yet
#   offsite.sh backup [manual]  send the newest local backup set, then forget --prune
#   offsite.sh check            restic check --read-data-subset OFFSITE_CHECK_SUBSET
#   offsite.sh drill            restore the newest off-site copy into a scratch database
#   offsite.sh due              run the check / the drill when they are due (loop.sh, hourly)
#   offsite.sh init             create the repository (offsite-init.sh)
#   offsite.sh snapshots        list the off-site copies (offsite-restore.sh)
#   offsite.sh restore ID DIR   put one copy's files into DIR (offsite-restore.sh)
#
# For Settings → Backups it writes these files to /backups — world-readable, so they never
# hold a secret (no password, no key, no credentials from a repository URL):
#   offsite-config.json   on/off, where to, retention, schedule
#   offsite-status.json   the last attempt: ok, or an error code and a short detail
#   offsite-last.json     the last good copy: snapshot id, sizes, which local backup
#   offsite-check.json    the last `restic check`
#   offsite-drill.json    the last restore drill from the off-site copy
set -eu
umask 077  # restored dumps and restic's scratch files hold everything: owner-only

ROOT=/backups
WORK=/cache                 # a Docker volume: restic's cache and scratch space for the drill
ERRF="$WORK/restic.err"     # restic's messages of the last command (no secrets in them)
HOST=moloko                 # snapshot host name (the container's own one changes on recreate)
CHECK_DB=moloko_offsite_check

KEEP_DAILY="${OFFSITE_KEEP_DAILY:-7}"
KEEP_WEEKLY="${OFFSITE_KEEP_WEEKLY:-4}"
KEEP_MONTHLY="${OFFSITE_KEEP_MONTHLY:-6}"
CHECK_DAYS="${OFFSITE_CHECK_DAYS:-7}"
DRILL_DAYS="${OFFSITE_DRILL_DAYS:-7}"
SUBSET="${OFFSITE_CHECK_SUBSET:-10%}"
LIMIT="${OFFSITE_UPLOAD_LIMIT_KIB:-0}"

now() { date -u +%FT%TZ; }
# Text fit for our JSON files: one line, no quotes, backslashes or control characters.
clean() { printf '%s' "$1" | tr '\t\r\n' '   ' | tr -d '\000-\037"\\' | cut -c1-300; }
# Like clean, but never lets a secret through (restic does not print them; belt and braces).
mask() {
  out="$(clean "$1")"
  for secret in "${OFFSITE_PASSWORD:-}" "${OFFSITE_S3_SECRET_ACCESS_KEY:-}" "${OFFSITE_S3_ACCESS_KEY_ID:-}" "${PGPASSWORD:-}"; do
    [ -n "$secret" ] || continue
    case "$out" in *"$secret"*) out="details hidden (they contained a secret): docker compose logs backup" ;; esac
  done
  printf '%s' "$out"
}
put() { # put FILE JSON — atomic, world-readable: the app shows it and it holds no secret
  printf '%s\n' "$2" > "$ROOT/$1.tmp" && mv "$ROOT/$1.tmp" "$ROOT/$1" && chmod 644 "$ROOT/$1"
}
field() { # field FILE KEY → a string value from one of our JSON files
  sed -n "s/.*\"$2\": *\"\([^\"]*\)\".*/\1/p" "$1" 2>/dev/null | head -n 1
}
number() { # number KEY TEXT → a whole-number value from restic's JSON output
  printf '%s' "$2" | sed -n "s/.*\"$1\": *\([0-9][0-9]*\).*/\1/p" | head -n 1
}
last_err() { grep -v '^[[:space:]]*$' "$ERRF" 2>/dev/null | tail -n 1 || true; }
code_for() { # restic's exit code → an error code the app translates
  case "$1" in
    10) echo no_repository ;;   # nothing at OFFSITE_REPOSITORY yet: run offsite-init.sh
    11) echo locked ;;          # another restic run holds the lock
    12) echo wrong_password ;;  # OFFSITE_PASSWORD does not open the repository
    3) echo incomplete ;;       # some files could not be read
    130 | 143) echo interrupted ;;
    *) echo failed ;;
  esac
}

# --- where to ------------------------------------------------------------------------------
REPO="${OFFSITE_REPOSITORY:-}"
if [ -z "$REPO" ] && [ -n "${OFFSITE_DISK:-}" ]; then REPO=/offsite; fi
case "$REPO" in
  "") KIND=off; WHERE="" ;;
  /offsite | /offsite/*) KIND=disk; WHERE="${OFFSITE_DISK:-/offsite}${REPO#/offsite}" ;;
  s3:* | sftp:* | rest:* | b2:* | azure:* | gs:* | swift:*)
    KIND="${REPO%%:*}"
    WHERE="$(printf '%s' "$REPO" | sed -E 's#(://)[^/@]*@#\1#')" ;;  # drop user:password@
  *) KIND=bad; WHERE="" ;;
esac
WHERE="$(clean "$WHERE")"

BAD=""
for value in "$KEEP_DAILY" "$KEEP_WEEKLY" "$KEEP_MONTHLY" "$CHECK_DAYS" "$DRILL_DAYS" "$LIMIT"; do
  case "$value" in "" | *[!0-9]*) BAD="OFFSITE_KEEP_*, OFFSITE_*_DAYS and OFFSITE_UPLOAD_LIMIT_KIB must be whole numbers" ;; esac
done
case "$SUBSET" in "" | *[!0-9./%KMGT]*) BAD="OFFSITE_CHECK_SUBSET must look like 10% or 500M" ;; esac
if [ "$KIND" = bad ]; then
  BAD="OFFSITE_REPOSITORY must start with s3:, sftp:, rest:, b2:, azure:, gs: or swift: (for a disk use OFFSITE_DISK)"
fi
if [ -z "$BAD" ] && [ $(( KEEP_DAILY + KEEP_WEEKLY + KEEP_MONTHLY )) -eq 0 ]; then
  BAD="keep at least one off-site copy (OFFSITE_KEEP_*)"
fi

disk_present() { # the external disk is mounted, not the empty folder on the laptop's own disk
  [ -d /offsite ] || return 1
  [ "$(stat -c %d /offsite)" != "$(stat -c %d /data/workspaces 2>/dev/null || echo none)" ]
}

REASON_CODE=""
REASON=""
ready() { # → 0 when restic can run; 3 when off-site is off; 1 (REASON_CODE, REASON) otherwise
  if [ "$KIND" = off ]; then
    echo "Off-site copies are off: set OFFSITE_REPOSITORY or OFFSITE_DISK in .env (docs/deployment.md, 6a)." >&2
    return 3
  fi
  if [ -n "$BAD" ]; then
    REASON_CODE=bad_settings; REASON="$BAD"
  elif [ -z "${OFFSITE_PASSWORD:-}" ]; then
    REASON_CODE=no_password; REASON="OFFSITE_PASSWORD is empty (offsite-init.sh creates one)"
  elif [ "$KIND" = disk ] && ! disk_present; then
    REASON_CODE=disk_missing
    REASON="the external disk (OFFSITE_DISK) is not mounted; if you plugged it in after the start: docker compose restart backup"
  fi
  if [ -n "$REASON_CODE" ]; then
    echo "off-site: $REASON" >&2
    return 1
  fi
  export RESTIC_REPOSITORY="$REPO" RESTIC_PASSWORD="$OFFSITE_PASSWORD"
  export RESTIC_CACHE_DIR="$WORK/restic" TMPDIR="$WORK/tmp"
  if [ -n "${OFFSITE_S3_ACCESS_KEY_ID:-}" ]; then export AWS_ACCESS_KEY_ID="$OFFSITE_S3_ACCESS_KEY_ID"; fi
  if [ -n "${OFFSITE_S3_SECRET_ACCESS_KEY:-}" ]; then export AWS_SECRET_ACCESS_KEY="$OFFSITE_S3_SECRET_ACCESS_KEY"; fi
  if [ -n "${OFFSITE_S3_REGION:-}" ]; then export AWS_DEFAULT_REGION="$OFFSITE_S3_REGION"; fi
  mkdir -p "$WORK/restic" "$WORK/tmp"
  return 0
}
# SFTP: never wait for a password prompt; the host key must be in known_hosts (OFFSITE_SSH_DIR).
sftp_opts() { if [ "$KIND" = sftp ]; then printf '%s' "-o sftp.args=-oBatchMode=yes"; fi; }

attempt() { # attempt ok | attempt CODE DETAIL — the result of the last attempt
  if [ "$1" = ok ]; then
    put offsite-status.json "{\"ok\": true, \"at\": \"$(now)\", \"repository\": \"$WHERE\"}"
  else
    put offsite-status.json "{\"ok\": false, \"at\": \"$(now)\", \"repository\": \"$WHERE\", \"error_code\": \"$1\", \"error\": \"$(mask "$2")\"}"
  fi
}

cmd_state() {
  if [ "$KIND" = off ]; then
    put offsite-config.json "{\"enabled\": false, \"at\": \"$(now)\"}"
    return 0
  fi
  if [ -n "$BAD" ]; then
    put offsite-config.json "{\"enabled\": true, \"at\": \"$(now)\", \"kind\": \"$KIND\", \"repository\": \"$WHERE\"}"
    attempt bad_settings "$BAD"
    return 0
  fi
  put offsite-config.json "{\"enabled\": true, \"at\": \"$(now)\", \"kind\": \"$KIND\", \"repository\": \"$WHERE\", \"keep_daily\": $KEEP_DAILY, \"keep_weekly\": $KEEP_WEEKLY, \"keep_monthly\": $KEEP_MONTHLY, \"check_days\": $CHECK_DAYS, \"drill_days\": $DRILL_DAYS, \"check_subset\": \"$(clean "$SUBSET")\"}"
}

cmd_pending() { # the newest good local backup has not reached this repository yet
  [ "$KIND" != off ] || return 1
  [ -f "$ROOT/status.json" ] && grep -q '"ok": true' "$ROOT/status.json" || return 1
  last="$ROOT/offsite-last.json"
  [ -f "$last" ] || return 0
  [ "$(field "$last" source_at)" = "$(field "$ROOT/status.json" at)" ] && [ "$(field "$last" repository)" = "$WHERE" ] && return 1
  return 0
}

cmd_backup() {
  tag="${1:-auto}"
  case "$tag" in auto | manual) ;; *) tag=auto ;; esac
  rc=0; ready || rc=$?
  if [ "$rc" -ne 0 ]; then
    if [ "$rc" -eq 1 ]; then attempt "$REASON_CODE" "$REASON"; fi
    return "$rc"
  fi
  status="$ROOT/status.json"
  if [ ! -f "$status" ] || ! grep -q '"ok": true' "$status"; then
    attempt no_local_backup "there is no good local backup to send yet"
    return 1
  fi
  db="$(field "$status" database)"
  files="$(field "$status" files)"
  source_at="$(field "$status" at)"
  if [ -z "$db" ] || [ ! -f "$ROOT/daily/$db" ]; then
    attempt no_local_backup "the newest local backup ($db) is missing from BACKUP_DIR"
    return 1
  fi
  # One snapshot = one local backup set, at the same paths as in BACKUP_DIR.
  set -- "$status" "$ROOT/daily/$db" "$ROOT/daily/$db.sha256"
  if [ -n "$files" ] && [ -f "$ROOT/daily/$files" ]; then
    set -- "$@" "$ROOT/daily/$files" "$ROOT/daily/$files.sha256"
  fi
  limit=""
  if [ "$LIMIT" -gt 0 ]; then limit="--limit-upload $LIMIT"; fi
  echo "off-site: sending $db to $WHERE"
  rc=0
  # shellcheck disable=SC2046,SC2086  # $limit and sftp_opts are deliberately split
  restic backup --host "$HOST" --tag moloko --tag "$tag" --json --retry-lock 10m $limit $(sftp_opts) "$@" \
    > "$WORK/backup.out" 2> "$ERRF" || rc=$?
  if [ "$rc" -ne 0 ]; then
    attempt "$(code_for "$rc")" "$(last_err)"
    echo "off-site backup failed: $(code_for "$rc"): $(mask "$(last_err)")" >&2
    return 1
  fi
  summary="$(grep '"message_type":"summary"' "$WORK/backup.out" | tail -n 1)"
  snapshot="$(printf '%s' "$summary" | sed -n 's/.*"snapshot_id":"\([0-9a-f]*\)".*/\1/p' | cut -c1-8)"
  bytes="$(number total_bytes_processed "$summary")"
  added="$(number data_added_packed "$summary")"

  # Retention: one group for all moloko snapshots (their paths differ every day).
  rc=0
  # shellcheck disable=SC2046
  restic forget --host "$HOST" --tag moloko --group-by host --keep-last 1 \
    --keep-daily "$KEEP_DAILY" --keep-weekly "$KEEP_WEEKLY" --keep-monthly "$KEEP_MONTHLY" \
    --prune --retry-lock 10m -q $(sftp_opts) > /dev/null 2> "$ERRF" || rc=$?
  forget_error="$(last_err)"
  # shellcheck disable=SC2046
  stats="$(restic stats --mode raw-data --json --no-lock $(sftp_opts) 2>/dev/null | tail -n 1 || true)"
  stored="$(number total_size "$stats")"
  count="$(number snapshots_count "$stats")"
  put offsite-last.json "{\"at\": \"$(now)\", \"repository\": \"$WHERE\", \"snapshot\": \"$snapshot\", \"source\": \"$(clean "$db")\", \"source_at\": \"$(clean "$source_at")\", \"bytes\": ${bytes:-0}, \"added_bytes\": ${added:-0}, \"stored_bytes\": ${stored:-null}, \"snapshots\": ${count:-null}}"
  if [ "$rc" -ne 0 ]; then
    attempt forget_failed "$forget_error"
    echo "off-site copy $snapshot made, but removing old copies failed: $(mask "$forget_error")" >&2
    return 1
  fi
  attempt ok
  echo "off-site ok: snapshot $snapshot, ${added:-0} new bytes uploaded, copies kept: ${count:-?}"
}

cmd_check() {
  ready || return $?
  echo "off-site: checking the repository (reading $SUBSET of the data)"
  rc=0
  # shellcheck disable=SC2046
  restic check --read-data-subset "$SUBSET" --retry-lock 10m -q $(sftp_opts) > /dev/null 2> "$ERRF" || rc=$?
  if [ "$rc" -eq 0 ]; then
    put offsite-check.json "{\"ok\": true, \"at\": \"$(now)\", \"subset\": \"$(clean "$SUBSET")\", \"detail\": \"no errors were found\"}"
    echo "off-site check ok"
    return 0
  fi
  put offsite-check.json "{\"ok\": false, \"at\": \"$(now)\", \"subset\": \"$(clean "$SUBSET")\", \"error_code\": \"$(code_for "$rc")\", \"detail\": \"$(mask "$(last_err)")\"}"
  echo "off-site check FAILED: $(mask "$(last_err)")" >&2
  return 1
}

cmd_drill() {
  ready || return $?
  dir="$WORK/drill"
  drill_fail() { # drill_fail CODE DETAIL [SNAPSHOT]
    put offsite-drill.json "{\"ok\": false, \"at\": \"$(now)\", \"snapshot\": \"${3:-}\", \"error_code\": \"$1\", \"detail\": \"$(mask "$2")\"}"
    rm -rf "$dir"
    echo "off-site restore drill FAILED: $(mask "$2")" >&2
    return 1
  }
  rm -rf "$dir"
  mkdir -p "$dir"
  rc=0
  # shellcheck disable=SC2046
  latest="$(restic snapshots latest --host "$HOST" --tag moloko --json --no-lock $(sftp_opts) 2> "$ERRF")" || rc=$?
  [ "$rc" -eq 0 ] || { drill_fail "$(code_for "$rc")" "$(last_err)"; return 1; }
  snapshot="$(printf '%s' "$latest" | sed -n 's/.*"short_id":"\([0-9a-f]*\)".*/\1/p' | head -n 1)"
  [ -n "$snapshot" ] || { drill_fail no_snapshot "there is no off-site copy yet"; return 1; }
  echo "off-site: restoring snapshot $snapshot into a scratch folder and database"
  # --verify reads every restored file back and compares it with the repository.
  # shellcheck disable=SC2046
  restic restore "$snapshot" --target "$dir" --verify -q $(sftp_opts) > /dev/null 2> "$ERRF" || rc=$?
  [ "$rc" -eq 0 ] || { drill_fail "$(code_for "$rc")" "$(last_err)" "$snapshot"; return 1; }
  db="$(field "$dir$ROOT/status.json" database)"
  files="$(field "$dir$ROOT/status.json" files)"
  dump="$dir$ROOT/daily/$db"
  [ -n "$db" ] && [ -f "$dump" ] || { drill_fail incomplete "the copy has no database dump" "$snapshot"; return 1; }
  if [ -n "$files" ]; then
    (cd "$dir$ROOT/daily" && sha256sum -c "$files.sha256" > /dev/null && gzip -t "$files") \
      || { drill_fail corrupt "the workspace archive in the copy is damaged" "$snapshot"; return 1; }
  fi
  same=null  # the dump is byte-identical to the local one (when that one still exists)
  if [ -f "$ROOT/daily/$db.sha256" ]; then
    if cmp -s "$ROOT/daily/$db.sha256" "$dump.sha256"; then same=true; else same=false; fi
  fi
  rc=0
  sh /scripts/restore-check.sh "$dump" offsite-drill.json "$CHECK_DB" \
    "\"snapshot\": \"$snapshot\", \"same_as_local\": $same, " || rc=$?
  rm -rf "$dir"
  return "$rc"
}

older_than() { # older_than FILE DAYS → due: missing, older than DAYS, or a failure older than a day
  f="$ROOT/$1"
  [ -f "$f" ] || return 0
  age=$(( $(date -u +%s) - $(stat -c %Y "$f") ))
  if grep -q '"ok": true' "$f"; then [ "$age" -ge $(( $2 * 86400 )) ]; else [ "$age" -ge 86400 ]; fi
}

cmd_due() {
  [ "$KIND" != off ] || return 0
  [ -f "$ROOT/offsite-last.json" ] || return 0  # nothing off-site yet
  if [ "$CHECK_DAYS" -gt 0 ] && older_than offsite-check.json "$CHECK_DAYS"; then cmd_check || true; fi
  if [ "$DRILL_DAYS" -gt 0 ] && older_than offsite-drill.json "$DRILL_DAYS"; then cmd_drill || true; fi
  return 0
}

cmd_init() {
  ready || return $?
  rc=0
  # shellcheck disable=SC2046
  restic cat config --no-lock $(sftp_opts) > /dev/null 2> "$ERRF" || rc=$?
  case "$rc" in
    0) echo "The off-site repository already exists and OFFSITE_PASSWORD opens it: $WHERE"; return 0 ;;
    12) echo "There is a repository at $WHERE, but OFFSITE_PASSWORD does not open it." >&2; return 1 ;;
    11) echo "The repository is locked by another restic run; try again later." >&2; return 1 ;;
  esac
  first="$(last_err)"
  rc=0
  # shellcheck disable=SC2046
  restic init $(sftp_opts) > /dev/null 2> "$ERRF" || rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "Could not create the repository at $WHERE: $(mask "$(last_err)")" >&2
    [ -z "$first" ] || echo "(opening it said: $(mask "$first"))" >&2
    return 1
  fi
  echo "Created the encrypted off-site repository: $WHERE"
}

cmd_snapshots() {
  ready || return $?
  # shellcheck disable=SC2046
  restic snapshots --host "$HOST" --tag moloko --no-lock $(sftp_opts)
}

cmd_restore() {
  id="${1:-}"
  target="${2:-}"
  case "$id" in
    latest) filter="--host $HOST --tag moloko" ;;
    *[!0-9a-f]* | "") echo "Give a snapshot ID from 'offsite-restore.sh' (or latest)." >&2; return 2 ;;
    *) filter="" ;;
  esac
  [ -n "$target" ] && [ -d "$target" ] || { echo "No folder to restore into: $target" >&2; return 2; }
  ready || return $?
  rc=0
  # shellcheck disable=SC2046,SC2086
  restic restore "$id" $filter --target "$target" --verify $(sftp_opts) || rc=$?
  [ "$rc" -eq 0 ] || { echo "restore failed ($(code_for "$rc"))" >&2; return 1; }
  if [ -n "${RESTORE_OWNER:-}" ]; then chown -R "$RESTORE_OWNER" "$target"; fi
}

case "${1:-}" in
  # One off-site run at a time inside this container (loop.sh and `docker compose exec`).
  backup | check | drill | due | init) exec 9> /tmp/offsite.lock && flock 9 ;;
esac
command="${1:-}"
[ $# -gt 0 ] && shift
case "$command" in
  state) cmd_state ;;
  pending) cmd_pending ;;
  backup) cmd_backup "$@" ;;
  check) cmd_check ;;
  drill) cmd_drill ;;
  due) cmd_due ;;
  init) cmd_init ;;
  snapshots) cmd_snapshots ;;
  restore) cmd_restore "$@" ;;
  *) echo "usage: offsite.sh state|pending|backup [manual]|check|drill|due|init|snapshots|restore ID DIR" >&2; exit 2 ;;
esac
