#!/usr/bin/env bash
# End-to-end test of the off-site copies (infrastructure/backup/offsite.sh) against a LOCAL
# restic repository — a folder standing in for the external disk, so no cloud account is
# needed. Uses only throwaway containers, volumes and folders; never touches the real stack.
#
#   infrastructure/scripts/test-offsite.sh
#
# Covers: off by default, local backup → init → backup → retention → check → restore drill
# into a scratch database → restore into a folder (byte-identical), "due" scheduling,
# wrong password, unplugged disk, and that no secret ever lands in the status files.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

ID="moloko-offsite-test-$$"
IMAGE="moloko-backup:offsite-test"
PG_IMAGE="pgvector/pgvector:0.8.1-pg17-trixie"  # PostgreSQL 17 + pgvector, as in production
PG="$ID-pg"
# Inside the project: Docker on a Mac may share only the home folder with containers.
WORK="$(mktemp -d "$ROOT/.offsite-test.XXXXXX")"
mkdir -p "$WORK/backups" "$WORK/disk" "$WORK/restore"
PASSWORD="$(openssl rand -hex 24)"

cleanup() {
  docker rm -f "$PG" "$ID-loop" > /dev/null 2>&1 || true
  # The containers write as root: remove their files from a container.
  docker run --rm --entrypoint sh -v "$WORK:/w" "$IMAGE" -c 'rm -rf /w/backups /w/disk /w/restore /w/loop' > /dev/null 2>&1 || true
  rm -rf "$WORK"
  docker volume rm -f "$ID-ws" "$ID-cache" > /dev/null 2>&1 || true
  docker network rm "$ID" > /dev/null 2>&1 || true
}
trap cleanup EXIT

step() { printf '\n\033[1m▶ %s\033[0m  (%ss)\n' "$*" "$SECONDS"; }
fail() { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
ok() { printf '  ✓ %s\n' "$*"; }
json() { # json FILE EXPR → the value of a Python expression over the parsed file `d`
  python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(eval(sys.argv[2]))' "$WORK/backups/$1" "$2"
}

# bk [docker options…] -- COMMAND…   run COMMAND in the backup image, set up like the
# compose service (read-only, only DAC_OVERRIDE), with the folder repository as OFFSITE_DISK.
bk() {
  local opts=()
  while [[ "$1" != "--" ]]; do opts+=("$1"); shift; done
  shift
  docker run --rm --network "$ID" --hostname moloko-backup --read-only --tmpfs /tmp \
    --cap-drop ALL --cap-add DAC_OVERRIDE --security-opt no-new-privileges:true \
    -e PGHOST="$PG" -e PGUSER=moloko -e PGPASSWORD=pg-test-secret -e PGDATABASE=moloko \
    -v "$ROOT/infrastructure/backup:/scripts:ro" -v "${BK_BACKUPS:-$WORK/backups}:/backups" \
    -v "$ID-ws:/data/workspaces:ro" -v "$ID-cache:/cache" \
    ${opts[@]+"${opts[@]}"} --entrypoint sh "$IMAGE" "$@"
}
DISK=(-e OFFSITE_DISK=/srv/usb-disk -e "OFFSITE_PASSWORD=$PASSWORD" -v "$WORK/disk:/offsite")

step "Build the backup image and start a throwaway PostgreSQL"
docker build -q -t "$IMAGE" infrastructure/backup > /dev/null
docker network create "$ID" > /dev/null
docker run -d --name "$PG" --network "$ID" -e POSTGRES_USER=moloko -e POSTGRES_PASSWORD=pg-test-secret \
  -e POSTGRES_DB=moloko "$PG_IMAGE" > /dev/null
for _ in $(seq 1 60); do
  # Over TCP: during its first start the image runs a temporary socket-only server.
  docker exec "$PG" pg_isready -h 127.0.0.1 -U moloko -d moloko > /dev/null 2>&1 && break
  sleep 1
done
# A small moloko-like database: the tables the drill counts, pgvector like production.
docker exec -i "$PG" psql -q -v ON_ERROR_STOP=1 -U moloko -d moloko > /dev/null <<'SQL'
CREATE EXTENSION vector;
CREATE TABLE users (id serial PRIMARY KEY, name text);
CREATE TABLE agents (id serial PRIMARY KEY, embedding vector(3));
CREATE TABLE tasks (id serial PRIMARY KEY);
CREATE TABLE agent_events (id serial PRIMARY KEY);
CREATE TABLE audit_logs (id serial PRIMARY KEY);
CREATE TABLE alembic_version (version_num text);
INSERT INTO users (name) VALUES ('owner');
INSERT INTO agents (embedding) VALUES ('[1,2,3]');
INSERT INTO tasks DEFAULT VALUES;
INSERT INTO alembic_version VALUES ('0013');
SQL
docker volume create "$ID-ws" > /dev/null
docker volume create "$ID-cache" > /dev/null
docker run --rm --entrypoint sh -v "$ID-ws:/w" "$IMAGE" -c 'mkdir -p /w/task-1 && echo "agent notes" > /w/task-1/notes.txt'
ok "ready"

step "Off by default: nothing configured, nothing breaks"
bk -- -c 'sh /scripts/offsite.sh state'
[[ "$(json offsite-config.json 'd["enabled"]')" == "False" ]] || fail "config should say off"
if bk -- -c 'sh /scripts/offsite.sh pending'; then fail "pending must be false when off"; fi
rc=0; bk -- -c 'sh /scripts/offsite.sh backup' 2> /dev/null || rc=$?
[[ "$rc" == 3 ]] || fail "backup when off should exit 3, got $rc"
bk -- -c 'sh /scripts/offsite.sh due'
[[ ! -e "$WORK/backups/offsite-status.json" ]] || fail "no attempt should be recorded when off"
ok "off: state written, pending=no, backup exits 3, due does nothing"

step "Local backup (backup.sh) and the local restore drill still work"
bk -- -c 'sh /scripts/backup.sh && sh /scripts/restore-check.sh' > /dev/null
[[ "$(json status.json 'd["ok"]')" == "True" ]] || fail "local backup failed"
[[ "$(json last-drill.json 'd["ok"]')" == "True" ]] || fail "local drill failed: $(cat "$WORK/backups/last-drill.json")"
ok "local backup + drill ok"

step "Before init: a clear error, not a crash"
bk "${DISK[@]}" -- -c 'sh /scripts/offsite.sh backup' 2> /dev/null && fail "backup without a repository must fail"
[[ "$(json offsite-status.json 'd["error_code"]')" == "no_repository" ]] || fail "expected no_repository: $(cat "$WORK/backups/offsite-status.json")"
ok "no_repository reported"

step "Init (twice: the second run keeps the repository)"
bk "${DISK[@]}" -- -c 'sh /scripts/offsite.sh init'
[[ -f "$WORK/disk/config" ]] || fail "no repository created on the disk"
bk "${DISK[@]}" -- -c 'sh /scripts/offsite.sh init' | grep -q "already exists" || fail "second init should keep it"
ok "repository created; init is idempotent"

step "Off-site backup → status, then nothing pending"
bk "${DISK[@]}" -- -c 'sh /scripts/offsite.sh state && sh /scripts/offsite.sh backup'
[[ "$(json offsite-config.json 'd["enabled"], d["kind"], d["repository"]')" == "(True, 'disk', '/srv/usb-disk')" ]] \
  || fail "config: $(cat "$WORK/backups/offsite-config.json")"
[[ "$(json offsite-status.json 'd["ok"]')" == "True" ]] || fail "status: $(cat "$WORK/backups/offsite-status.json")"
first="$(json offsite-last.json 'd["snapshot"]')"
[[ "$first" =~ ^[0-9a-f]{8}$ ]] || fail "no snapshot id: $(cat "$WORK/backups/offsite-last.json")"
[[ "$(json offsite-last.json 'd["source"] == json.load(open(sys.argv[1].replace("offsite-last","status")))["database"]')" == "True" ]] \
  || fail "the snapshot is not the newest local backup"
[[ "$(json offsite-last.json 'd["bytes"] > 0 and d["stored_bytes"] > 0')" == "True" ]] || fail "sizes missing"
if bk "${DISK[@]}" -- -c 'sh /scripts/offsite.sh pending'; then fail "nothing should be pending after a backup"; fi
ok "snapshot $first; pending=no"

step "A new local backup is pending; forget --prune applies the retention"
sleep 1
bk -- -c 'sh /scripts/backup.sh' > /dev/null
bk "${DISK[@]}" -- -c 'sh /scripts/offsite.sh pending' || fail "the new local backup should be pending"
bk "${DISK[@]}" -- -c 'sh /scripts/offsite.sh backup manual'
middle="$(json offsite-last.json 'd["snapshot"]')"
[[ "$middle" != "$first" ]] || fail "expected a new snapshot"
sleep 1
bk -- -c 'sh /scripts/backup.sh' > /dev/null
bk "${DISK[@]}" -- -c 'sh /scripts/offsite.sh backup'
second="$(json offsite-last.json 'd["snapshot"]')"
# Three copies on one day: restic keeps the newest of the day, plus the oldest one while
# fewer than OFFSITE_KEEP_DAILY days exist — the middle one must be gone.
[[ "$(json offsite-last.json 'd["snapshots"]')" == "2" ]] || fail "retention: $(cat "$WORK/backups/offsite-last.json")"
bk "${DISK[@]}" -- -c 'sh /scripts/offsite.sh snapshots' > "$WORK/snapshots.txt"
grep -q "$first" "$WORK/snapshots.txt" && grep -q "$second" "$WORK/snapshots.txt" \
  && ! grep -q "$middle" "$WORK/snapshots.txt" || fail "retention kept the wrong copies: $(cat "$WORK/snapshots.txt")"
ok "kept $first (oldest) and $second (newest), pruned $middle"

step "Check (restic check --read-data-subset)"
bk "${DISK[@]}" -e OFFSITE_CHECK_SUBSET=100% -- -c 'sh /scripts/offsite.sh check'
[[ "$(json offsite-check.json 'd["ok"], d["subset"]')" == "(True, '100%')" ]] || fail "check: $(cat "$WORK/backups/offsite-check.json")"
ok "check ok"

step "Restore drill from the off-site copy into a scratch database"
bk "${DISK[@]}" -- -c 'sh /scripts/offsite.sh drill'
[[ "$(json offsite-drill.json 'd["ok"], d["snapshot"], d["same_as_local"]')" == "(True, '$second', True)" ]] \
  || fail "drill: $(cat "$WORK/backups/offsite-drill.json")"
json offsite-drill.json 'd["detail"]' | grep -q "users=1" || fail "drill did not count the owner"
docker exec "$PG" psql -At -U moloko -d postgres -c "SELECT count(*) FROM pg_database WHERE datname = 'moloko_offsite_check'" \
  | grep -qx 0 || fail "the scratch database was not dropped"
bk "${DISK[@]}" -- -c '[ ! -e /cache/drill ]' || fail "the restored files were left in the cache"
ok "drill ok: $(json offsite-drill.json 'd["detail"]')"

step "Restore one copy into a folder (as offsite-restore.sh does)"
bk "${DISK[@]}" -v "$WORK/restore:/restore" --cap-add CHOWN -e "RESTORE_OWNER=$(id -u):$(id -g)" \
  -- -c 'sh /scripts/offsite.sh snapshots > /dev/null && sh /scripts/offsite.sh restore latest /restore > /dev/null'
db="$(json status.json 'd["database"]')"
files="$(json status.json 'd["files"]')"
cmp -s "$WORK/restore/backups/daily/$db" "$WORK/backups/daily/$db" || fail "the restored dump differs"
cmp -s "$WORK/restore/backups/daily/$files" "$WORK/backups/daily/$files" || fail "the restored workspace archive differs"
tar -tzf "$WORK/restore/backups/daily/$files" | grep -q "workspaces/task-1/notes.txt" || fail "workspace file missing"
ok "restored files are byte-identical to the local backup"

step "Due: fresh check/drill are not repeated; an old one is"
before="$(json offsite-check.json 'd["at"]')"
bk "${DISK[@]}" -- -c 'sh /scripts/offsite.sh due'
[[ "$(json offsite-check.json 'd["at"]')" == "$before" ]] || fail "a fresh check must not run again"
bk -- -c 'touch -d "2026-01-01 00:00:00" /backups/offsite-check.json'
sleep 1
bk "${DISK[@]}" -- -c 'sh /scripts/offsite.sh due' > /dev/null
[[ "$(json offsite-check.json 'd["at"]')" != "$before" ]] || fail "an old check must run again"
ok "due logic ok"

step "loop.sh: one round on a fresh server = local backup, off-site copy, check, drill"
# A stand-in `sleep` first on PATH: skips the start delay, ends the loop at its hourly sleep.
# (In /cache: the /tmp tmpfs is noexec. `; true` keeps loop.sh a child: PID 1 ignores kills.)
LOOP='mkdir -p /cache/bin && printf "#!/bin/sh\n[ \"\$1\" = 60 ] && exit 0\nkill -9 \$PPID\n" > /cache/bin/sleep && chmod +x /cache/bin/sleep && PATH=/cache/bin:$PATH sh /scripts/loop.sh; rm -rf /cache/bin; true'
mkdir -p "$WORK/loop"
loop_round() { # one round of loop.sh; fails the test if it does not end within 5 minutes
  BK_BACKUPS="$WORK/loop" bk -d --name "$ID-loop" "${DISK[@]}" "$@" -- -c "$LOOP" > /dev/null
  for _ in $(seq 1 300); do
    docker inspect "$ID-loop" > /dev/null 2>&1 || return 0  # finished (--rm removed it)
    sleep 1
  done
  docker rm -f "$ID-loop" > /dev/null 2>&1 || true
  fail "loop.sh did not finish its round"
}
lj() { python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(eval(sys.argv[2]))' "$WORK/loop/$1" "$2"; }
loop_round
for f in status offsite-status offsite-check offsite-drill; do
  [[ "$(lj "$f.json" 'd["ok"]')" == "True" ]] || fail "loop: $f.json: $(cat "$WORK/loop/$f.json" 2>/dev/null)"
done
[[ "$(lj offsite-last.json 'd["source"]')" == "$(lj status.json 'd["database"]')" ]] || fail "loop: sent the wrong backup"
at="$(lj status.json 'd["at"]')"
loop_round -e BACKUP_HOUR=0
[[ "$(lj status.json 'd["at"]')" == "$at" ]] || fail "loop: a second backup on the same day"
BK_BACKUPS="$WORK/loop" bk -- -c 'touch -d "$(date -u -d @$(( $(date -u +%s) - 86400 )) "+%Y-%m-%d %H:%M:%S")" /backups/status.json'
sleep 1
loop_round -e BACKUP_HOUR=0
[[ "$(lj status.json 'd["at"]')" != "$at" ]] || fail "loop: no backup although the last one is from yesterday"
[[ "$(lj offsite-last.json 'd["source_at"]')" == "$(lj status.json 'd["at"]')" ]] || fail "loop: the new backup was not sent off-site"
ok "first round did everything; same day = no new backup; next day = backup + off-site copy"

step "Wrong password → wrong_password, and the last good copy is kept"
bk -e OFFSITE_DISK=/srv/usb-disk -e OFFSITE_PASSWORD=not-the-password -v "$WORK/disk:/offsite" \
  -- -c 'sh /scripts/offsite.sh backup' 2> /dev/null && fail "a wrong password must fail"
[[ "$(json offsite-status.json 'd["ok"], d["error_code"]')" == "(False, 'wrong_password')" ]] \
  || fail "status: $(cat "$WORK/backups/offsite-status.json")"
[[ "$(json offsite-last.json 'd["snapshot"]')" == "$second" ]] || fail "the last good copy must stay recorded"
ok "wrong_password reported"

step "Disk not plugged in (the folder is on the laptop's own disk) → disk_missing"
bk -e OFFSITE_DISK=/srv/usb-disk -e "OFFSITE_PASSWORD=$PASSWORD" -v "$ID-ws:/offsite" \
  -- -c 'sh /scripts/offsite.sh backup' 2> /dev/null && fail "an unplugged disk must fail"
[[ "$(json offsite-status.json 'd["error_code"]')" == "disk_missing" ]] || fail "status: $(cat "$WORK/backups/offsite-status.json")"
ok "disk_missing reported, nothing written to the laptop disk"

step "Bad settings are reported, not crashed on"
bk "${DISK[@]}" -e OFFSITE_KEEP_DAILY=7a -- -c 'sh /scripts/offsite.sh state && sh /scripts/offsite.sh backup' 2> /dev/null \
  && fail "bad settings must fail"
[[ "$(json offsite-status.json 'd["error_code"]')" == "bad_settings" ]] || fail "status: $(cat "$WORK/backups/offsite-status.json")"
ok "bad_settings reported"

step "No secret in any status file; all of them are valid JSON"
for f in "$WORK"/backups/*.json; do
  python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$f" || fail "invalid JSON: $f"
  if grep -q -e "$PASSWORD" -e pg-test-secret "$f"; then fail "secret leaked into $f"; fi
done
ok "$(ls "$WORK"/backups/*.json | wc -l | tr -d ' ') status files clean"

printf '\n\033[32mAll off-site tests passed.\033[0m\n'
