#!/usr/bin/env bash
# Install or update moloko on the server — one command, safe to run again.
#
#   infrastructure/scripts/deploy.sh
#
# Steps: get the latest `main`, create/complete .env, back up existing data, build the
# images (including PostgreSQL+pgvector and the agents' browser), start everything,
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
if [[ -z "$backup_dir" || "$backup_dir" == "./backups" ]]; then
  warn "BACKUP_DIR указывает на этот же диск. Подключите внешний диск и пропишите его путь в .env."
fi

# --- 3. backup before an update -------------------------------------------------------------
if [[ "$first_install" == "0" && "${NO_BACKUP:-0}" != "1" ]] && docker compose ps --status running -q backup 2>/dev/null | grep -q .; then
  say "Резервная копия перед обновлением"
  infrastructure/scripts/backup-now.sh || fail "Копия не удалась — обновление остановлено (данные не тронуты)."
fi

# --- 4. build -----------------------------------------------------------------------------------
say "Сборка образов (первый раз — несколько минут)"
docker compose build --pull
if [[ "${NO_BROWSER:-0}" != "1" ]]; then
  docker compose --profile browser build --pull browser \
    || warn "Образ браузера не собрался: агенты не смогут открывать сайты, PDF — через печать браузера. Запустите скрипт ещё раз позже."
fi

# --- 5. start -------------------------------------------------------------------------------
say "Запуск"
docker compose up -d --remove-orphans

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
if docker volume inspect moloko_redis-data >/dev/null 2>&1; then
  echo "• Старый том Redis больше не нужен (теперь Valkey):  docker volume rm moloko_redis-data"
fi
[[ "$todo" == "0" ]] && echo "Всё готово. Откройте moloko на любом своём устройстве в Tailscale."
echo
echo "Сохраните копию .env в надёжном месте (менеджер паролей): без неё не расшифровать ключи."
