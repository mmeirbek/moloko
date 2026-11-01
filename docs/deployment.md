# Развёртывание на домашнем сервере

Инструкция для Ubuntu Server и **Manjaro / Arch Linux** (шаг 1 отличается, дальше всё одинаково).
Приложение доступно **только** внутри вашей сети Tailscale по HTTPS. В локальную сеть и в интернет
ничего не открывается.

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

### 1a. Manjaro / Arch Linux вместо шагов 1–2 выше

```bash
sudo pacman -Syu --needed docker docker-compose docker-buildx git openssh tailscale
sudo systemctl enable --now docker tailscaled sshd
sudo usermod -aG docker "$USER"         # docker без sudo (после повторного входа)
sudo tailscale up                       # если сервер ещё не в tailnet
sudo tailscale set --operator="$USER"   # tailscale serve без sudo
```

`pacman -Syu` обновляет всю систему — на Manjaro пакеты ставят только так. У группы `docker`
на Arch нет постоянного номера: `init-env.sh` берёт его у `/var/run/docker.sock`, поэтому запускайте
его **после** установки Docker. Брандмауэр настраивать не нужно: Caddy слушает только `127.0.0.1`.

**Ноутбук как сервер** (не засыпать с закрытой крышкой и от бездействия — KDE/GNOME усыпляют по таймеру):

```bash
sudo mkdir -p /etc/systemd/logind.conf.d
printf '[Login]\nHandleLidSwitch=ignore\nHandleLidSwitchExternalPower=ignore\nHandleLidSwitchDocked=ignore\n' \
  | sudo tee /etc/systemd/logind.conf.d/moloko-server.conf
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
sudo reboot
```

Вернуть сон: `sudo systemctl unmask sleep.target suspend.target hibernate.target hybrid-sleep.target`.

## 2. Установка moloko

**Одной командой** (и для первой установки, и для обновлений):

```bash
git clone -b main https://github.com/mmeirbek/moloko.git
```

```bash
cd moloko && infrastructure/scripts/deploy.sh
```

Скрипт берёт свежую ветку `main` и создаёт `.env` со случайными секретами (или дописывает недостающие ключи). Перед обновлением он делает резервную копию. Затем собирает образы, включая PostgreSQL с pgvector и браузер для агентов, запускает всё и ждёт, пока сервисы станут здоровыми. В конце он пишет, что осталось сделать: создать владельца и включить `tailscale serve`. Запускать его можно сколько угодно раз.

То же самое по шагам, вручную:

```bash
git clone -b main https://github.com/mmeirbek/moloko.git
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

## 6. Резервные копии

Сервис `backup` каждый день в `BACKUP_HOUR` (по UTC, по умолчанию 3:00) делает:

- дамп базы данных и архив рабочих папок агентов;
- проверку целостности (контрольные суммы и чтение дампа);
- ротацию: хранятся 7 ежедневных и 4 еженедельные копии.

Каждое воскресенье он дополнительно проверяет восстановление: разворачивает свежую копию во временную базу и сверяет данные. Состояние видно в «Настройки → Резервные копии».

**Важно: копии должны лежать на другом диске.** Подключите внешний диск или сетевую папку и укажите путь в `.env`:

```bash
BACKUP_DIR=/mnt/backup/moloko
```

Затем перезапустите сервис:

```bash
docker compose up -d backup
```

Если копии лежат на одном диске с данными, приложение покажет предупреждение.

Файл `.env` в копию **не входит**: в нём ключи, без которых не расшифровать сохранённые токены. Храните его копию отдельно, например в менеджере паролей.

Сделать копию сейчас и сразу проверить восстановление:

```bash
infrastructure/scripts/backup-now.sh --check
```

Восстановить из копии. Это **заменяет все текущие данные**: скрипт попросит ввести `RESTORE`.

```bash
infrastructure/scripts/restore.sh /mnt/backup/moloko/daily/moloko-ГГГГММДД-ЧЧММСС.dump /mnt/backup/moloko/daily/workspaces-ГГГГММДД-ЧЧММСС.tar.gz
```

Восстановление было проверено целиком. Строки, созданные после копии, пропали, а приложение поднялось здоровым. Повторяйте такую проверку раз в несколько месяцев.

## 7. Телефон: установка как приложение и уведомления

- **iPhone (Safari).** Откройте `https://moloko.<ваш-tailnet>.ts.net`, нажмите «Поделиться», затем «На экран „Домой“».
- **Android (Chrome).** Меню, затем «Установить приложение».
- **Уведомления** (нужно одобрение, задача выполнена, задача не выполнена). Включаются в «Настройки → Уведомления» отдельно на каждом устройстве. Они приходят, пока moloko открыт, в том числе в фоне.
- **Уведомления при закрытом приложении (Web Push).** В «Настройки → Уведомления» включите «Уведомления, когда moloko закрыт (Web Push)» на каждом устройстве.
  - Нужен `APP_ENCRYPTION_KEY`: ключи VAPID хранятся зашифрованными.
  - Задайте в `.env` настоящий контакт `PUSH_CONTACT=mailto:вы@пример.org`, иначе Apple отклоняет такие уведомления. Затем выполните `docker compose up -d`.
  - **iPhone:** работает только у приложения, установленного на экран «Домой» (iOS 16.4+). Разрешение запрашивается после нажатия на переключатель.
  - Текст уведомления шифруется. Сервис доставки (Apple, Google или Mozilla) видит только зашифрованные данные.

## 8. Браузер для агентов и PDF

Агенты могут открывать сайты (инструмент «Открыть сайт в браузере», всегда с вашим одобрением). Экспорт результата в PDF печатается тем же браузером. Его образ собирается отдельно, один раз и после обновлений:

```bash
docker compose --profile browser build browser
```

Браузер выходит в интернет только через сервис `egress`: только публичные адреса и порты 80/443. Домашняя сеть, Tailscale и сам сервер для него закрыты. Без собранного образа PDF всё равно можно сохранить через печать браузера («Сохранить как PDF»).

## 8a. GitHub MCP (официальный сервер GitHub)

1. «Интеграции → GitHub»: вставьте токен (fine-grained PAT с доступом только к нужным репозиториям) и нажмите «Проверить».
2. «Интеграции», блок «GitHub — официальный MCP-сервер»: выберите наборы инструментов и нажмите «Подключить GitHub MCP». По умолчанию сервер работает только на чтение.
3. Все инструменты сервера появляются **выключенными**. Включайте только нужные. Инструменты, которые что-то меняют, требуют одобрения.

Токен хранится один раз, в интеграции GitHub. Если его убрать, MCP-сервер тоже перестаёт работать.

## 9. Проверка после обновления

Обновление = та же команда: `infrastructure/scripts/deploy.sh` (копия → сборка → запуск → проверка).

**Обновление с версии без поиска (PostgreSQL на Alpine).** Образ базы теперь собирается локально: PostgreSQL 17.11 на Debian с расширением pgvector. Сначала сделайте свежую копию, потом пересоберите образ:

```bash
infrastructure/scripts/backup-now.sh --check
```

```bash
docker compose up -d --build
```

Миграция один раз перестроит индексы таблиц: на Debian порядок сортировки текста может отличаться от Alpine. Ваши данные остаются на месте.

Если вы обновляетесь с версии, где был Redis, старый том больше не нужен (moloko теперь использует Valkey):

```bash
docker volume rm moloko_redis-data
```

Полный набор браузерных тестов поднимает отдельный временный стенд: свой порт, свои тома, модель-заглушка без ключей. Ваши данные он не трогает.

```bash
npm ci && infrastructure/scripts/e2e.sh
```

## 10. Если что-то не работает

| Симптом | Что проверить |
|---|---|
| Сайт не открывается | `tailscale status` на обоих устройствах, `tailscale serve status`, `docker compose ps` |
| Сервис `unhealthy` | `docker compose logs <сервис>`. Ответ `/api/v1/health` показывает, что именно недоступно |
| «Слишком много неудачных попыток» | Подождите 15 минут (`LOGIN_LOCKOUT_SECONDS`) |
| Сразу выкидывает на страницу входа | Открывайте сайт по `https://`: cookie с флагом `Secure` по `http://` не сохраняются |
| Терминал агента «не настроен» | `docker compose ps sandbox`; в `.env` задан `SANDBOX_RUNNER_TOKEN` (`init-env.sh --add-missing`) и верный `DOCKER_GID` (`stat -c %g /var/run/docker.sock`) |
| «Резервные копии: старая копия / ошибка» | `docker compose logs backup`; доступен ли диск `BACKUP_DIR`; затем `infrastructure/scripts/backup-now.sh --check` |
| Ошибка с «Кодом ошибки» | Найдите этот код в логах: `docker compose logs backend \| grep <код>` |

Ограничение: ноутбук не работает круглосуточно. При отключении питания или интернета
приложение недоступно, но после включения оно поднимается само.
