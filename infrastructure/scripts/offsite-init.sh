#!/usr/bin/env bash
# Set up the encrypted off-site copies — once (docs/deployment.md, section 6a):
#   1. put OFFSITE_REPOSITORY (+ keys) for cloud storage / SFTP, or OFFSITE_DISK for an
#      external disk, into .env;
#   2. run this script. It creates OFFSITE_PASSWORD if it is empty, restarts the backup
#      service, creates the encrypted repository, sends the first copy, checks it,
#      test-restores it and tells you what to save in your password manager.
# Safe to run again: an existing repository is kept, nothing is deleted.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
ENV_FILE="${MOLOKO_ENV_FILE:-.env}"
ENV_ARGS=()
[[ -n "${MOLOKO_ENV_FILE:-}" ]] && ENV_ARGS=(--env-file "$MOLOKO_ENV_FILE")
compose() { docker compose ${ENV_ARGS[@]+"${ENV_ARGS[@]}"} "$@"; }

say() { printf '\n\033[1m▶ %s\033[0m\n' "$*"; }
warn() { printf '\033[33m! %s\033[0m\n' "$*"; }
fail() { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

[[ -f "$ENV_FILE" ]] || fail "Нет файла $ENV_FILE. Сначала установите moloko: infrastructure/scripts/deploy.sh"
env_value() { # the value of KEY in the env file, without surrounding quotes
  local v
  v="$(grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- || true)"
  v="${v%\"}"; v="${v#\"}"; v="${v%\'}"; v="${v#\'}"
  printf '%s' "$v"
}

repo="$(env_value OFFSITE_REPOSITORY)"
disk="$(env_value OFFSITE_DISK)"
if [[ -z "$repo" && -z "$disk" ]]; then
  cat <<'EOF'
Куда отправлять копии? Впишите в .env ОДИН из вариантов (подробно: docs/deployment.md, раздел 6a)
и запустите этот скрипт ещё раз.

  Backblaze B2 (дешевле всего):
    OFFSITE_REPOSITORY=s3:https://s3.<регион>.backblazeb2.com/<бакет>/moloko
    OFFSITE_S3_ACCESS_KEY_ID=<keyID>
    OFFSITE_S3_SECRET_ACCESS_KEY=<applicationKey>

  Cloudflare R2:
    OFFSITE_REPOSITORY=s3:https://<ID аккаунта>.r2.cloudflarestorage.com/<бакет>/moloko
    OFFSITE_S3_ACCESS_KEY_ID=<Access Key ID>
    OFFSITE_S3_SECRET_ACCESS_KEY=<Secret Access Key>
    OFFSITE_S3_REGION=auto

  Внешний USB-диск (смонтированный, см. раздел 6a):
    OFFSITE_DISK=/mnt/moloko-offsite
EOF
  exit 1
fi

if [[ -z "$repo" ]]; then
  # The disk must really be a separate disk, mounted now — not a folder on the laptop's disk.
  [[ -d "$disk" ]] || fail "Папки $disk нет. Подключите и смонтируйте диск (раздел 6a), затем запустите снова."
  dev() { stat -c %d "$1" 2> /dev/null || stat -f %d "$1"; }
  docker_root="$(docker info -f '{{.DockerRootDir}}' 2> /dev/null || echo /)"
  for other in / "$ROOT" "$docker_root"; do
    if [[ -e "$other" && "$(dev "$disk")" == "$(dev "$other")" ]]; then
      fail "$disk находится на диске самого ноутбука (как $other). Смонтируйте туда внешний диск (раздел 6a)."
    fi
  done
fi

new_password=0
if [[ -z "$(env_value OFFSITE_PASSWORD)" ]]; then
  password="$(openssl rand -hex 32)"
  umask 077
  # Rewritten with shell built-ins only, so the password never shows up in `ps`.
  tmp="$(mktemp "$ENV_FILE.XXXXXX")"
  found=0
  while IFS= read -r line || [[ -n "$line" ]]; do
    if [[ "$line" == OFFSITE_PASSWORD=* ]]; then
      printf 'OFFSITE_PASSWORD=%s\n' "$password"
      found=1
    else
      printf '%s\n' "$line"
    fi
  done < "$ENV_FILE" > "$tmp"
  [[ "$found" == 1 ]] || printf '\n# Off-site copies: restic encryption password (also in your password manager!)\nOFFSITE_PASSWORD=%s\n' "$password" >> "$tmp"
  mv "$tmp" "$ENV_FILE"
  unset password
  new_password=1
  echo "Создан пароль шифрования копий OFFSITE_PASSWORD (записан в $ENV_FILE)."
fi

say "Обновляю сервис backup (restic внутри)"
compose build backup
compose up -d backup

say "Создаю зашифрованное хранилище копий"
compose exec -T backup sh /scripts/offsite.sh init || fail "Хранилище не создано — проверьте адрес и ключи в .env (раздел 6a)."
compose exec -T backup sh /scripts/offsite.sh state

say "Первая копия вне ноутбука"
if ! compose exec -T backup test -f /backups/status.json; then
  compose exec -T backup sh /scripts/backup.sh
fi
compose exec -T backup sh /scripts/offsite.sh backup manual || fail "Копия не отправлена (подробности выше и в «Настройки → Резервные копии»)."

say "Проверка: целостность копии и восстановление из неё во временную базу"
compose exec -T backup sh /scripts/offsite.sh check || warn "Проверка хранилища не прошла — подробности выше."
compose exec -T backup sh /scripts/offsite.sh drill || warn "Пробное восстановление не прошло — подробности выше."

say "Готово. Что сделать сейчас"
if [[ "$new_password" == 1 ]]; then
  warn "Пароль OFFSITE_PASSWORD создан только что. Без него копию НЕ открыть никому, даже вам."
fi
cat <<EOF
• Сохраните в менеджере паролей (лучше — весь файл .env целиком):
    grep '^OFFSITE_' $ENV_FILE
  OFFSITE_PASSWORD и ключи хранилища нужны, чтобы восстановить moloko на НОВОМ компьютере,
  если этот ноутбук пропадёт. SECRET_KEY и APP_ENCRYPTION_KEY из того же .env нужны для
  сохранённых ключей провайдеров.
• Дальше всё само: после каждой ежедневной копии она уходит вне ноутбука, раз в неделю
  хранилище проверяется и из него делается пробное восстановление.
• Состояние: «Настройки → Резервные копии».
• Список копий и восстановление: infrastructure/scripts/offsite-restore.sh
EOF
