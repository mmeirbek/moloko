#!/usr/bin/env bash
# Install or update moloko on the server — one command, safe to run again.
#
#   infrastructure/scripts/deploy.sh
#
# Steps: get the latest `main`, create/complete .env, back up existing data, build the
# images (including PostgreSQL+pgvector, the agents' sandbox and browser), start everything,
# wait until every service is healthy, then say what (if anything) is left to do.
# Options (environment): NO_PULL=1 (keep the current code), NO_BROWSER=1 (skip the
# browser image), NO_BACKUP=1 (skip the backup before an update — not recommended).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

say() { printf '\n\033[1m▶ %s\033[0m\n' "$*"; }
warn() { printf '\033[33m! %s\033[0m\n' "$*"; }
fail() { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

for tool in git docker openssl curl; do
  command -v "$tool" >/dev/null || fail "Нужна программа «$tool» (см. docs/deployment.md, раздел 1)."
done
docker compose version >/dev/null 2>&1 || fail "Нужен Docker Compose v2 (docker compose)."
docker info >/dev/null 2>&1 || fail "Docker не запущен или у пользователя нет доступа к нему (sudo usermod -aG docker \$USER, затем перелогиньтесь)."

# --- 1. code ----------------------------------------------------------------------------
if [[ "${NO_PULL:-0}" != "1" ]]; then
  say "Получаю свежую версию (ветка main)"
  if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
    fail "В папке есть изменённые файлы. Сохраните их (git stash) или запустите с NO_PULL=1."
  fi
  git fetch --quiet origin main
  if [[ "$(git rev-parse --abbrev-ref HEAD)" != "main" ]]; then
    git checkout --quiet -B main origin/main
  else
    git merge --quiet --ff-only origin/main
  fi
  echo "Версия: $(git log -1 --format='%h %s')"
fi

# --- 2. settings ---------------------------------------------------------------------------
say "Настройки (.env)"
first_install=0
if [[ ! -e .env ]]; then
  infrastructure/scripts/init-env.sh
  first_install=1
else
  infrastructure/scripts/init-env.sh --add-missing
fi
env_value() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- || true; }
if [[ "$(env_value PUSH_CONTACT)" == *"moloko.invalid"* || -z "$(env_value PUSH_CONTACT)" ]]; then
  warn "PUSH_CONTACT не задан: push-уведомления на iPhone не придут. Впишите в .env: PUSH_CONTACT=mailto:ваш@адрес"
fi
backup_dir="$(env_value BACKUP_DIR)"
if [[ ( -z "$backup_dir" || "$backup_dir" == "./backups" ) && -z "$(env_value OFFSITE_REPOSITORY)$(env_value OFFSITE_DISK)" ]]; then
  warn "Резервные копии лежат на этом же диске. Настройте копии вне ноутбука (docs/deployment.md, раздел 6a)."
fi

# --- 3. backup before an update -------------------------------------------------------------
if [[ "$first_install" == "0" && "${NO_BACKUP:-0}" != "1" ]] && docker compose ps --status running -q backup 2>/dev/null | grep -q .; then
  say "Резервная копия перед обновлением"
  infrastructure/scripts/backup-now.sh || fail "Копия не удалась — обновление остановлено (данные не тронуты)."
fi

# --- 4. build -----------------------------------------------------------------------------------
say "Сборка образов (первый раз — несколько минут)"
docker compose build --pull
# The image agents' commands run in (Python + Node.js + git): without it terminal_run fails.
docker compose --profile sandbox-image build --pull sandbox-image \
  || warn "Образ песочницы не собрался: агенты не смогут выполнять команды (terminal_run). Запустите скрипт ещё раз позже."
if [[ "${NO_BROWSER:-0}" != "1" ]]; then
  docker compose --profile browser build --pull browser \
    || warn "Образ браузера не собрался: агенты не смогут открывать сайты, PDF — через печать браузера. Запустите скрипт ещё раз позже."
fi

# --- 5. start -------------------------------------------------------------------------------
say "Запуск"
docker compose up -d --remove-orphans
# Caddy reads its Caddyfile (a single-file mount, pinned to the old file after `git checkout`)
# only at start, and compose does not recreate it for a changed file: recreate it here.
if ! docker compose exec -T caddy cat /etc/caddy/Caddyfile 2>/dev/null | cmp -s - infrastructure/caddy/Caddyfile; then
  echo "Caddyfile изменился — перезапускаю caddy"
  docker compose up -d --force-recreate --no-deps caddy
fi

say "Жду, пока все сервисы станут здоровыми"
deadline=$((SECONDS + 420))
while true; do
  states="$(docker compose ps --format '{{.Service}} {{.Health}}' 2>/dev/null || true)"
  bad="$(awk '$2 != "healthy" {print $1}' <<<"$states" | tr '\n' ' ')"
  [[ -z "${bad// /}" && -n "$states" ]] && break
  if (( SECONDS > deadline )); then
    docker compose ps
    for service in $bad; do
      echo "--- $service (последние строки журнала) ---"
      docker compose logs --tail 30 "$service" || true
    done
    fail "Не все сервисы поднялись: $bad"
  fi
  sleep 5
done
docker compose ps --format 'table {{.Service}}\t{{.Status}}'

port="$(env_value HTTP_PORT)"; port="${port:-8080}"
curl -fsS "http://127.0.0.1:$port/api/v1/health" >/dev/null || fail "Сайт не отвечает на 127.0.0.1:$port."
echo "Сайт отвечает на 127.0.0.1:$port ✓"

# --- 6. what is left ---------------------------------------------------------------------------
say "Что осталось сделать"
todo=0
owner="$(docker compose exec -T backend python -m app.cli has-owner 2>/dev/null || true)"
if [[ "$owner" == *no* ]]; then
  todo=1
  echo "• Создайте аккаунт владельца (пароль от 12 символов):"
  echo "    docker compose exec backend python -m app.cli create-owner --username <имя> --display-name \"<Ваше имя>\""
fi
if command -v tailscale >/dev/null; then
  if ! tailscale serve status 2>/dev/null | grep -q "127.0.0.1:$port"; then
    todo=1
    echo "• Откройте доступ через Tailscale (только в вашей сети):"
    echo "    sudo tailscale serve --bg $port"
  fi
  name="$(tailscale status --json 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))' 2>/dev/null || true)"
  [[ -n "$name" ]] && echo "• Адрес: https://$name"
else
  todo=1
  echo "• Установите Tailscale (docs/deployment.md, раздел 1), затем: sudo tailscale serve --bg $port"
fi
backup_root="${backup_dir:-./backups}"
if [[ -z "$(env_value OFFSITE_REPOSITORY)" && -z "$(env_value OFFSITE_DISK)" ]]; then
  todo=1
  echo "• Копии лежат только на этом ноутбуке. Настройте копии вне ноутбука (облако B2/R2 или внешний диск):"
  echo "    docs/deployment.md, раздел 6a, затем: infrastructure/scripts/offsite-init.sh"
elif [[ ! -f "$backup_root/offsite-last.json" ]]; then
  todo=1
  echo "• Копии вне ноутбука указаны в .env, но ещё ни одной не сделано:"
  echo "    infrastructure/scripts/offsite-init.sh"
fi
stt_status="$(docker compose exec -T stt python -c "import json, urllib.request; print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4))['status'])" 2>/dev/null || true)"
case "$stt_status" in
  ready) echo "• Распознавание речи: локальная модель Whisper готова ✓" ;;
  missing|loading)
    echo "• Модель распознавания речи ещё скачивается/загружается (один раз). Ход: docker compose logs -f stt-models"
    echo "  Пока она не готова, голос идёт через провайдера OpenAI (если он добавлен)." ;;
  *) warn "Локальное распознавание речи не готово (${stt_status:-нет ответа}): docker compose logs stt stt-models" ;;
esac
if docker volume inspect moloko_redis-data >/dev/null 2>&1; then
  echo "• Старый том Redis больше не нужен (теперь Valkey):  docker volume rm moloko_redis-data"
fi
[[ "$todo" == "0" ]] && echo "Всё готово. Откройте moloko на любом своём устройстве в Tailscale."
echo
echo "Сохраните копию .env в надёжном месте (менеджер паролей): без неё не расшифровать ключи и копии вне ноутбука."
