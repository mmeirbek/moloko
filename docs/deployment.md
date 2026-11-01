# Развёртывание на домашнем сервере

Инструкция для Ubuntu Server (Huawei MateBook D16). Приложение доступно **только** внутри
вашей сети Tailscale по HTTPS. В локальную сеть и в интернет ничего не открывается.

```
телефон / ноутбуки ──(Tailscale, HTTPS)──► tailscale serve ──► 127.0.0.1:8080 (Caddy) ──► приложение
```

## 1. Подготовка сервера (один раз)

1. **Docker Engine и плагин Compose**: следуйте официальной инструкции
   https://docs.docker.com/engine/install/ubuntu/. Затем включите автозапуск:
   ```bash
   sudo systemctl enable --now docker
   ```
2. **Tailscale**: следуйте инструкции https://tailscale.com/download/linux. Затем:
   ```bash
   sudo tailscale up
   ```
3. В админке Tailscale (https://login.tailscale.com/admin):
   - **Machines**: переименуйте сервер в `moloko`. Адрес приложения станет `https://moloko.<ваш-tailnet>.ts.net`.
   - **DNS**: включите **MagicDNS** и **HTTPS Certificates**. Без них `tailscale serve` не выдаст сертификат.
4. **Ноутбук как сервер**: чтобы он не засыпал при закрытой крышке, в `/etc/systemd/logind.conf`
   задайте `HandleLidSwitch=ignore` и `HandleLidSwitchExternalPower=ignore`, затем выполните:
   ```bash
   sudo systemctl restart systemd-logind
   ```

## 2. Установка moloko

```bash
git clone https://github.com/mmeirbek/moloko.git
cd moloko
infrastructure/scripts/init-env.sh      # создаёт .env со случайными секретами (права 600)
docker compose up -d --build            # первая сборка займёт несколько минут
docker compose ps                       # все сервисы (включая worker) должны стать "healthy"
```

`init-env.sh` не перезаписывает существующий `.env`. Если вы обновляетесь с версии до
спринта 7, добавьте новые ключи (токен песочницы и группу Docker) командой:

```bash
infrastructure/scripts/init-env.sh --add-missing
```

`init-env.sh` не трогает уже заданные значения. Сохраните копию `.env` в надёжном
месте (например, в менеджере паролей): без `SECRET_KEY` и `APP_ENCRYPTION_KEY` нельзя
будет расшифровать сохранённые ключи провайдеров (начиная со спринта 2).

### Создание аккаунта владельца

Регистрации через сайт нет. Аккаунт создаётся один раз из командной строки:

```bash
docker compose exec backend python -m app.cli create-owner --username <имя> --display-name "<Ваше имя>"
```

Пароль нужно ввести дважды, минимум 12 символов. Второй аккаунт команда создать не даст.

## 3. Доступ через Tailscale

```bash
sudo tailscale serve --bg 8080
tailscale serve status
```

Теперь приложение открывается по адресу `https://moloko.<ваш-tailnet>.ts.net` на любом
вашем устройстве, где запущен Tailscale: MacBook, Huawei, телефон. Настройка `--bg`
сохраняется после перезагрузки. Отключить доступ:

```bash
sudo tailscale serve reset
```

> Не используйте `tailscale funnel`: он открывает приложение в интернет.
> Если синтаксис команды изменился, сверьтесь с `tailscale serve --help`.

### Проверка, что лишнего наружу не открыто

```bash
sudo ss -ltnp | grep -E ':5432|:6379'   # пусто: PostgreSQL и Redis без портов на хосте
sudo ss -ltnp | grep ':8080'            # только 127.0.0.1:8080
curl -s http://127.0.0.1:8080/api/v1/health
```

Последняя команда должна вернуть `{"status":"ok",...}`.

### Ограничение доступа в Tailscale (рекомендуется)

Если в вашем tailnet есть чужие устройства, разрешите доступ к серверу только своим.
Пример политики в **Access controls**:

```json
{
  "tagOwners": { "tag:moloko": ["autogroup:admin"] },
  "grants": [
    { "src": ["autogroup:admin"], "dst": ["tag:moloko"], "ip": ["443", "22"] }
  ]
}
```

После этого назначьте серверу тег `tag:moloko` на странице Machines. Порт 22 (SSH)
откройте только для себя или уберите совсем.

## 4. Повседневные операции

| Задача | Команда |
|---|---|
| Состояние сервисов | `docker compose ps` |
| Логи бэкенда / воркера агентов | `docker compose logs -f backend worker` |
| Обновление до новой версии | `git pull && docker compose up -d --build` (миграции БД применяются автоматически) |
| Перезапуск | `docker compose restart` |
| Остановка | `docker compose down` (данные сохраняются в томах Docker) |
| Забыли пароль | `docker compose exec backend python -m app.cli reset-password --username <имя>` (все сессии завершаются) |

После перезагрузки сервера Docker сам поднимает все контейнеры (`restart: unless-stopped`).
Бэкенд ждёт готовности PostgreSQL и применяет миграции.

## 5. Инструменты агентов (песочница, GitHub, MCP)

- **Песочница.** Сервис `sandbox` — единственный, кому доступен Docker (`/var/run/docker.sock`). Команды агентов выполняются в отдельных контейнерах без сети и без root. Нужен Docker Engine 26 или новее: проверьте `docker version`. Первый запуск команды скачает образ `SANDBOX_IMAGE` (по умолчанию `python:3.12.16-slim`).
- **GitHub.** Создайте fine-grained token на github.com → Settings → Developer settings → Personal access tokens. Выдайте доступ только к нужным репозиториям: Contents (чтение и запись), Pull requests, Issues (чтение). Затем вставьте токен в «Интеграции → GitHub». Токен хранится зашифрованным.
- **Поиск в интернете** (необязательно). Запустите свой SearXNG и укажите `SEARXNG_URL` в `.env`. Без него агенты могут открывать страницы, но не искать.
- **MCP-серверы.** Подключайте серверы с HTTP-транспортом в «Интеграции → MCP». Новые инструменты выключены, пока вы их не включите.
- **Песочница на E2B** (на будущее) требует KVM. Проверить можно командой `ls -l /dev/kvm`.

## 6. Резервная копия вручную

Автоматические бэкапы появятся в спринте 8. До этого делайте копию вручную и храните
её **не на диске сервера** (внешний диск, другой компьютер):

```bash
docker compose exec -T postgres pg_dump -U moloko -Fc moloko > moloko-$(date +%F).dump
```

Восстановление (заменяет текущие данные):

```bash
docker compose exec -T postgres pg_restore -U moloko -d moloko --clean --if-exists < moloko-YYYY-MM-DD.dump
```

## 7. Если что-то не работает

| Симптом | Что проверить |
|---|---|
| Сайт не открывается | `tailscale status` на обоих устройствах, `tailscale serve status`, `docker compose ps` |
| Сервис `unhealthy` | `docker compose logs <сервис>`. Ответ `/api/v1/health` показывает, что именно недоступно |
| «Слишком много неудачных попыток» | Подождите 15 минут (`LOGIN_LOCKOUT_SECONDS`) |
| Сразу выкидывает на страницу входа | Открывайте сайт по `https://`: cookie с флагом `Secure` по `http://` не сохраняются |
| Терминал агента «не настроен» | `docker compose ps sandbox`; в `.env` задан `SANDBOX_RUNNER_TOKEN` (`init-env.sh --add-missing`) и верный `DOCKER_GID` (`stat -c %g /var/run/docker.sock`) |
| Ошибка с «Кодом ошибки» | Найдите этот код в логах: `docker compose logs backend \| grep <код>` |

Ограничение: ноутбук не работает круглосуточно. При отключении питания или интернета
приложение недоступно, но после включения оно поднимается само.
