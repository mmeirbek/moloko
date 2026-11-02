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

### Вход по Face ID / Touch ID (ключи входа, passkeys)

Ключ входа привязан к адресу сайта, поэтому серверу нужно знать этот адрес. Впишите в `.env`
имя сервера в Tailscale — то, что видно в адресной строке, без `https://`:

```bash
WEBAUTHN_RP_ID=moloko.<ваш-tailnet>.ts.net
WEBAUTHN_ORIGINS=https://moloko.<ваш-tailnet>.ts.net
```

Точное имя покажет `tailscale status --json | grep DNSName` (первая строка, без точки в конце).
`deploy.sh` (через `init-env.sh`) вписывает эти две строки сам, если их ещё нет в `.env`
и Tailscale уже настроен. Затем перезапустите бэкенд: `docker compose up -d backend`.

Дальше на каждом устройстве: откройте moloko по адресу `…ts.net`, «Настройки → Система и данные →
Ключи входа (passkeys)» → «Добавить ключ», введите пароль moloko и подтвердите Face ID / Touch ID.
Ключ из Связки ключей iCloud сразу работает и на других ваших устройствах Apple. После этого на
странице входа есть кнопка «Войти по Face ID / Touch ID», а ключ подсказывается прямо в поле имени.

- Пароль продолжает работать всегда. Удалить ключ можно только с паролем.
- Пусто в обеих строках = ключи выключены. Так и должно быть на тестовом стенде `http://127.0.0.1`:
  ключам нужен настоящий домен.
- Если вы переименуете сервер в Tailscale, адрес изменится и старые ключи перестанут подходить:
  поправьте обе строки и добавьте ключи заново.
- Неверное значение (например, с `https://` в `WEBAUTHN_RP_ID`) не даст бэкенду запуститься, а в
  логе будет понятная ошибка: `docker compose logs backend`.

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

- **Песочница.** Сервис `sandbox` — единственный, кому доступен Docker (`/var/run/docker.sock`). Команды агентов выполняются в отдельных контейнерах без сети и без root. Нужен Docker Engine 26 или новее: проверьте `docker version`. Образ для команд — `moloko-sandbox:local` (Python 3.12, Node.js 22 с npm/npx, git, make). Его собирает `deploy.sh`; вручную: `docker compose --profile sandbox-image build sandbox-image`. Без него агенты не смогут выполнять команды. Лимиты на одну команду по умолчанию: 2 ГБ памяти, 512 процессов, до 10 минут (`SANDBOX_MEMORY_MB`, `SANDBOX_PIDS_LIMIT`, `SANDBOX_TIMEOUT_SECONDS`). Этого хватает на `npm ci`, проверку типов и сборку Next.js. `init-env.sh --add-missing` (его запускает `deploy.sh`) заменяет в `.env` старые значения по умолчанию (`python:3.12.16-slim`, 512, 128, 60) на новые. Значения, которые вы меняли сами, он не трогает.
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

Сервис просыпается раз в час. Если в `BACKUP_HOUR` сервер был выключен, копия будет сделана в тот же день позже, как только он включится.

**Важно: копии на этом же ноутбуке — не защита.** Если ноутбук сломается или пропадёт, пропадут и они. Настройте зашифрованные **копии вне ноутбука** — раздел 6a. Локальные копии при этом остаются: из них быстрее всего откатиться.

Локальные копии можно также держать на другом диске (внешний диск, сетевая папка) — путь в `.env`:

```bash
BACKUP_DIR=/mnt/backup/moloko
```

Затем перезапустите сервис:

```bash
docker compose up -d backup
```

Если копии лежат на одном диске с данными и копий вне ноутбука нет, приложение покажет предупреждение.

Файл `.env` в копию **не входит**: в нём ключи, без которых не расшифровать сохранённые токены и копии вне ноутбука. Храните его копию отдельно, например в менеджере паролей.

Сделать копию сейчас и сразу проверить восстановление:

```bash
infrastructure/scripts/backup-now.sh --check
```

Восстановить из копии. Это **заменяет все текущие данные**: скрипт попросит ввести `RESTORE`.

```bash
infrastructure/scripts/restore.sh /mnt/backup/moloko/daily/moloko-ГГГГММДД-ЧЧММСС.dump /mnt/backup/moloko/daily/workspaces-ГГГГММДД-ЧЧММСС.tar.gz
```

Восстановление было проверено целиком. Строки, созданные после копии, пропали, а приложение поднялось здоровым. Повторяйте такую проверку раз в несколько месяцев.

Скрипт сначала разворачивает копию в отдельную новую базу и подменяет ею рабочую, только если всё прошло без ошибок. Прежние данные остаются в базе `moloko_before_restore` до следующего восстановления. Если что-то пошло не так, данные не меняются, а moloko запускается снова.

`sudo` не нужен: файлы копий принадлежат root (их пишет контейнер), и `restore.sh` читает их через временный контейнер.

## 6a. Копии вне ноутбука (зашифрованные)

Каждая ежедневная копия может уходить **зашифрованной** за пределы ноутбука:

- в облако с доступом по S3 — **Backblaze B2** (дешевле всего), **Cloudflare R2** или любое другое S3-хранилище;
- на **внешний USB-диск**, подключённый к серверу. Он спасает при поломке диска ноутбука, но не при краже или пожаре — для этого нужно облако;
- на свой сервер по **SFTP**.

Как это устроено:

- Внутри сервиса `backup` работает программа **restic**. Она шифрует всё прямо на ноутбуке паролем `OFFSITE_PASSWORD` (AES-256) и только потом отправляет. Хранилище видит лишь зашифрованные куски.
- **После каждой ежедневной копии** отправляется её снимок: дамп базы, архив файлов агентов и их контрольные суммы. Если отправка не удалась (нет интернета, диск отключён), сервис повторяет её каждый час.
- **Хранение:** за последние 7 дней — по копии в день, за 4 недели — по копии в неделю, за 6 месяцев — по копии в месяц (`OFFSITE_KEEP_DAILY`, `OFFSITE_KEEP_WEEKLY`, `OFFSITE_KEEP_MONTHLY`). Лишние копии удаляются сами (`restic forget --prune`).
- **Раз в неделю — проверка хранилища** (`restic check`, при этом читается 10% данных: `OFFSITE_CHECK_DAYS`, `OFFSITE_CHECK_SUBSET`).
- **Раз в неделю — пробное восстановление** (`OFFSITE_DRILL_DAYS`): свежая копия скачивается, расшифровывается, разворачивается во временную базу, сверяется и удаляется. Рабочая база не затрагивается.
- Всё это видно в «Настройки → Резервные копии → Копии вне ноутбука»: когда ушла последняя копия, её размер, сколько копий хранится, итоги проверки и пробного восстановления, ошибки.

> **Пароль — самое важное.** `OFFSITE_PASSWORD` и ключи хранилища лежат только в `.env` на сервере. **Сохраните их ещё и в менеджере паролей** (лучше весь `.env` целиком). Без пароля копии не откроет никто: ни вы, ни Backblaze, ни Cloudflare. Если ноутбук пропадёт вместе с `.env`, а пароля в менеджере нет, копии бесполезны.

Пока ничего не настроено, всё работает как раньше: копии делаются только локально, а в настройках висит предупреждение.

### Вариант A: Backblaze B2 (рекомендуется)

У B2 и R2 есть бесплатный объём (на момент написания — 10 ГБ). Копии moloko обычно меньше. Актуальные цены смотрите на сайтах.

1. Зарегистрируйтесь на https://www.backblaze.com и откройте **B2 Cloud Storage**.
2. **Buckets → Create a Bucket.** Имя должно быть уникальным, например `moloko-backup-` и несколько случайных букв. «Files in Bucket»: **Private**. «Object Lock»: выключен.
3. В настройках бакета откройте **Lifecycle Settings** и выберите **«Keep only the last version of the file»**. Иначе удалённые старые копии останутся скрытыми версиями, и за них будут брать деньги.
4. **Application Keys → Add a New Application Key.** Имя: `moloko`. «Allow access to Bucket(s)»: только этот бакет. «Type of Access»: **Read and Write**. Сохраните `keyID` и `applicationKey` — ключ показывается один раз.
5. Посмотрите **Endpoint** бакета на странице Buckets, например `s3.eu-central-003.backblazeb2.com`.
6. Впишите в `.env` на сервере (`nano .env`):
   ```bash
   OFFSITE_REPOSITORY=s3:https://s3.eu-central-003.backblazeb2.com/<имя-бакета>/moloko
   OFFSITE_S3_ACCESS_KEY_ID=<keyID>
   OFFSITE_S3_SECRET_ACCESS_KEY=<applicationKey>
   ```
7. Запустите (подробнее — ниже, «Первый запуск»):
   ```bash
   infrastructure/scripts/offsite-init.sh
   ```

### Вариант B: Cloudflare R2

1. https://dash.cloudflare.com → **R2 Object Storage → Create bucket**. Имя любое, «Location»: Automatic.
2. **R2 → Manage R2 API Tokens → Create API token.** «Permissions»: **Object Read & Write**, «Specify bucket(s)»: только этот бакет. Сохраните **Access Key ID** и **Secret Access Key**. Адрес вида `https://<ACCOUNT_ID>.r2.cloudflarestorage.com` показан там же.
3. Впишите в `.env`:
   ```bash
   OFFSITE_REPOSITORY=s3:https://<ACCOUNT_ID>.r2.cloudflarestorage.com/<имя-бакета>/moloko
   OFFSITE_S3_ACCESS_KEY_ID=<Access Key ID>
   OFFSITE_S3_SECRET_ACCESS_KEY=<Secret Access Key>
   OFFSITE_S3_REGION=auto
   ```
4. `infrastructure/scripts/offsite-init.sh`

### Вариант C: внешний USB-диск

1. Подключите диск и найдите его: `lsblk -f` (например, `/dev/sdb1`). Отформатируйте его в ext4. **Это сотрёт всё на диске:**
   ```bash
   sudo mkfs.ext4 -L moloko-offsite /dev/sdb1
   ```
2. Сделайте постоянную точку монтирования. Параметр `nofail` нужен, чтобы ноутбук загружался и без диска:
   ```bash
   sudo mkdir -p /mnt/moloko-offsite
   echo 'LABEL=moloko-offsite /mnt/moloko-offsite ext4 defaults,nofail,x-systemd.device-timeout=5s 0 2' | sudo tee -a /etc/fstab
   sudo systemctl daemon-reload && sudo mount /mnt/moloko-offsite
   ```
3. Впишите в `.env` (`OFFSITE_REPOSITORY` оставьте пустым):
   ```bash
   OFFSITE_DISK=/mnt/moloko-offsite
   ```
4. Запустите `infrastructure/scripts/offsite-init.sh`. Он откажется работать, если папка лежит на диске самого ноутбука, то есть если внешний диск не смонтирован.

Если диск отключали, подключите его снова и выполните `sudo mount /mnt/moloko-offsite`, если он не смонтировался сам. Затем выполните `docker compose restart backup`. Пока диска нет, в настройках будет «Внешний диск не подключён». Копия уйдёт в течение часа после того, как диск вернётся.

### Вариант D: свой сервер по SFTP

```bash
mkdir -p ~/moloko-ssh && ssh-keygen -t ed25519 -N '' -f ~/moloko-ssh/id_ed25519
ssh-copy-id -i ~/moloko-ssh/id_ed25519.pub <пользователь>@<хост>
ssh-keyscan <хост> > ~/moloko-ssh/known_hosts
```

В `.env`: `OFFSITE_REPOSITORY=sftp:<пользователь>@<хост>:/srv/backup/moloko` и `OFFSITE_SSH_DIR=/home/<вы>/moloko-ssh`. Затем `infrastructure/scripts/offsite-init.sh`.

### Первый запуск: `offsite-init.sh`

```bash
infrastructure/scripts/offsite-init.sh
```

Скрипт делает всё сам, и его можно запускать повторно:

1. Если `OFFSITE_PASSWORD` пуст, создаёт случайный пароль и записывает его в `.env`.
2. Пересобирает и перезапускает сервис `backup` (внутри него restic).
3. Создаёт зашифрованное хранилище. Существующее хранилище не трогает, только проверяет, что пароль к нему подходит.
4. Отправляет первую копию, проверяет хранилище и делает пробное восстановление.
5. Напоминает, что сохранить в менеджере паролей. **Сделайте это сразу:**
   ```bash
   grep '^OFFSITE_' .env
   ```

Дальше всё происходит само. Отправить копию сейчас и проверить её:

```bash
infrastructure/scripts/backup-now.sh --offsite --check
```

### Восстановление из копии вне ноутбука

Список копий (ID, время, файлы):

```bash
infrastructure/scripts/offsite-restore.sh
```

Достать копию в пустую папку. Сам moloko при этом не меняется:

```bash
infrastructure/scripts/offsite-restore.sh <ID> ~/moloko-restore
```

Восстановить копию **в сам moloko**. Это заменяет **все текущие данные**: скрипт попросит ввести `RESTORE`.

```bash
infrastructure/scripts/offsite-restore.sh <ID> --replace
```

Вместо `<ID>` можно написать `latest` — самая свежая копия.

### Восстановление на НОВОМ компьютере (ноутбук пропал)

Нужны только менеджер паролей (`.env` или хотя бы строки `OFFSITE_*`) и доступ к бакету (или сам USB-диск).

1. Подготовьте новый сервер по разделу 1 (Docker, Tailscale). Для USB-диска смонтируйте его, как в варианте C, шаг 2.
2. Скачайте moloko:
   ```bash
   git clone -b main https://github.com/mmeirbek/moloko.git && cd moloko
   ```
3. Верните `.env` из менеджера паролей: `nano .env`, вставьте содержимое, затем `chmod 600 .env`.
   Если сохранены только строки `OFFSITE_*`, сначала запустите `infrastructure/scripts/init-env.sh`, затем допишите эти строки в новый `.env`. Ключи AI-провайдеров тогда придётся ввести заново: без старого `APP_ENCRYPTION_KEY` их не расшифровать.
4. Установите пустой moloko:
   ```bash
   infrastructure/scripts/deploy.sh
   ```
   **Аккаунт владельца не создавайте** — он придёт из копии.
5. Посмотрите список копий и восстановите самую свежую. Скрипт попросит ввести `RESTORE`:
   ```bash
   infrastructure/scripts/offsite-restore.sh
   ```
   ```bash
   infrastructure/scripts/offsite-restore.sh latest --replace
   ```
6. Войдите в moloko со своим прежним паролем и загляните в журнал аудита.
7. Включите отправку копий с нового компьютера:
   ```bash
   infrastructure/scripts/offsite-init.sh
   ```

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

## 8b. Голосовой ввод: своя модель распознавания речи

Голос распознаёт модель **Whisper** прямо на сервере (сервис `stt`, процессор, без видеокарты): ключ OpenAI не нужен, запись никуда не уходит, русский и английский (язык определяется сам; в микрофоне можно выбрать «ru»/«en»). Модель задаётся в `.env`: `STT_MODEL=large-v3-turbo` (по умолчанию), `medium` или `small` (быстрее, но хуже по-русски). Замер на Mac M4 (6 ядер в Docker): `large-v3-turbo` — ~4,5 с на фразу до 20 с, по-русски ~99 % слов верно; `small` — 1,5–3 с, ~92 %; `medium` — 4–9 с, ~96 % (`docs/decisions.md`). Короткая фраза почти не быстрее длинной: Whisper всегда обрабатывает окно в 30 с. Ноутбук-сервер может быть медленнее — проверьте командой ниже и при необходимости поставьте `small`.

- **Скачивание — один раз.** Сервис `stt-models` при `deploy.sh` скачивает модель (~1,6 ГБ для `large-v3-turbo`) в том `moloko_stt-models` и выходит; ход: `docker compose logs -f stt-models`. Версия модели закреплена, файл проверяется по SHA-256. Интернет есть только у `stt-models` (своя сеть `stt-download`), у самого `stt` его нет.
- Пока модель скачивается или загружается, голос идёт через провайдера OpenAI (если он добавлен). Состояние видно в «Настройки → Голос и поиск».
- Поменяли `STT_MODEL` — запустите `deploy.sh` ещё раз: скачается новая модель, старую можно удалить: `docker compose run --rm --entrypoint rm stt-models -rf /models/<старая>`.
- Нагрузка: `STT_CPU_THREADS` (6) потоков, лимит контейнера `STT_CPUS` (6) и `STT_MEMORY` (4g). Выключить: `STT_URL=` в `.env`.
- Проверить скорость на этом сервере: `docker compose exec -T stt python -m stt_server bench - < запись.webm` (печатает длительность записи, время распознавания и текст).

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
| «Копии вне ноутбука требуют внимания» | Текст ошибки в «Настройки → Резервные копии»; `docker compose logs backup`; затем `infrastructure/scripts/backup-now.sh --offsite --check`. «Хранилище не найдено» — запустите `offsite-init.sh`; «Внешний диск не подключён» — смонтируйте его и выполните `docker compose restart backup` |
| Ошибка с «Кодом ошибки» | Найдите этот код в логах: `docker compose logs backend \| grep <код>` |

Ограничение: ноутбук не работает круглосуточно. При отключении питания или интернета
приложение недоступно, но после включения оно поднимается само.
