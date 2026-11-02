#!/usr/bin/env bash
# Restore from the encrypted off-site copies (docs/deployment.md, section 6a).
#
#   offsite-restore.sh                        list the off-site copies (ID, time, files)
#   offsite-restore.sh <ID|latest> <folder>   put that copy's files into an EMPTY folder;
#                                             moloko itself is not touched
#   offsite-restore.sh <ID|latest> --replace  restore that copy INTO moloko: replaces ALL
#                                             current data (restore.sh asks you to type RESTORE)
#
# Works on a new machine too: install moloko (deploy.sh) with the .env from your password
# manager — at least the OFFSITE_* lines — then run this.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
ENV_ARGS=()
[[ -n "${MOLOKO_ENV_FILE:-}" ]] && ENV_ARGS=(--env-file "$MOLOKO_ENV_FILE")
compose() { docker compose ${ENV_ARGS[@]+"${ENV_ARGS[@]}"} "$@"; }
fail() { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
# A one-off backup container (built if needed); works whether or not moloko is running.
# stdin from /dev/null: it must not swallow what you type for restore.sh's question.
offsite() { compose run --rm --no-deps -T "$@" < /dev/null; }

if [[ $# -eq 0 ]]; then
  offsite backup sh /scripts/offsite.sh snapshots
  cat <<EOF

Восстановить копию (ID — первая колонка, или latest — самая свежая):
  в пустую папку, ничего не меняя:   $0 <ID> ~/moloko-restore
  в сам moloko (ЗАМЕНИТ все данные): $0 <ID> --replace
EOF
  exit 0
fi

id="$1"
target="${2:-}"
[[ "$id" =~ ^(latest|[0-9a-f]{8,64})$ ]] || fail "ID копии — 8 или больше символов 0-9a-f из списка ($0 без аргументов), или latest."
[[ -n "$target" ]] || fail "Куда восстановить? Пустая папка или --replace (см. $0 без аргументов)."

restore_into() { # restore_into FOLDER — the copy's files, owned by you
  offsite --cap-add CHOWN -e "RESTORE_OWNER=$(id -u):$(id -g)" -v "$1:/restore" \
    backup sh /scripts/offsite.sh restore "$id" /restore
}

if [[ "$target" == "--replace" ]]; then
  staging="$(mktemp -d "$ROOT/.offsite-restore.XXXXXX")"
  trap 'rm -rf "$staging"' EXIT
  echo "Скачиваю и расшифровываю копию ${id}…"
  restore_into "$staging"
  dump="$(ls -1 "$staging"/backups/daily/moloko-*.dump 2> /dev/null | head -n 1 || true)"
  files="$(ls -1 "$staging"/backups/daily/workspaces-*.tar.gz 2> /dev/null | head -n 1 || true)"
  [[ -n "$dump" ]] || fail "В копии нет дампа базы."
  infrastructure/scripts/restore.sh "$dump" ${files:+"$files"}
  exit 0
fi

mkdir -p "$target"
target="$(cd "$target" && pwd)"
[[ -z "$(ls -A "$target")" ]] || fail "Папка $target не пуста. Выберите пустую или новую папку."
restore_into "$target"
cat <<EOF

Файлы копии лежат в $target/backups/daily:
$(ls -1 "$target"/backups/daily)
Вернуть их в moloko (ЗАМЕНИТ все данные):
  infrastructure/scripts/restore.sh $target/backups/daily/moloko-….dump $target/backups/daily/workspaces-….tar.gz
EOF
