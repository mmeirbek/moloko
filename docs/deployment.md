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
docker compose ps                       # все сервисы должны стать "healthy"
```

`init-env.sh` не перезаписывает существующий `.env`. Сохраните копию `.env` в надёжном
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
| Логи бэкенда | `docker compose logs -f backend` |
| Обновление до новой версии | `git pull && docker compose up -d --build` (миграции БД применяются автоматически) |
| Перезапуск | `docker compose restart` |
| Остановка | `docker compose down` (данные сохраняются в томах Docker) |
| Забыли пароль | `docker compose exec backend python -m app.cli reset-password --username <имя>` (все сессии завершаются) |

После перезагрузки сервера Docker сам поднимает все контейнеры (`restart: unless-stopped`).
Бэкенд ждёт готовности PostgreSQL и применяет миграции.

## 5. Резервная копия вручную

Автоматические бэкапы появятся в спринте 8. До этого делайте копию вручную и храните
её **не на диске сервера** (внешний диск, другой компьютер):

```bash
docker compose exec -T postgres pg_dump -U moloko -Fc moloko > moloko-$(date +%F).dump
```

Восстановление (заменяет текущие данные):

```bash
docker compose exec -T postgres pg_restore -U moloko -d moloko --clean --if-exists < moloko-YYYY-MM-DD.dump
```

## 6. Если что-то не работает

| Симптом | Что проверить |
|---|---|
| Сайт не открывается | `tailscale status` на обоих устройствах, `tailscale serve status`, `docker compose ps` |
| Сервис `unhealthy` | `docker compose logs <сервис>`. Ответ `/api/v1/health` показывает, что именно недоступно |
| «Слишком много неудачных попыток» | Подождите 15 минут (`LOGIN_LOCKOUT_SECONDS`) |
| Сразу выкидывает на страницу входа | Открывайте сайт по `https://`: cookie с флагом `Secure` по `http://` не сохраняются |
| Ошибка с «Кодом ошибки» | Найдите этот код в логах: `docker compose logs backend \| grep <код>` |

Ограничение: ноутбук не работает круглосуточно. При отключении питания или интернета
приложение недоступно, но после включения оно поднимается само.
