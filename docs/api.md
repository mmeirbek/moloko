# API

Base path `/api/v1`, JSON only. Interactive docs at `/api/docs` when `ENVIRONMENT=development`
(disabled in production). The machine-readable schema is `packages/shared-types/openapi.json`.

## Conventions

- **Errors** always look like:
  ```json
  {"error": {"id": "uuid", "code": "invalid_credentials", "message": "Invalid username or password.", "details": null}}
  ```
  `id` is unique per occurrence and appears in the server log next to the technical details.
  Validation errors (`422 validation_error`) list `details[].loc/msg/type` and never echo submitted values.
- **Auth**: session cookie `moloko_session` (HttpOnly). Every route requires it unless listed as public below.
- **CSRF**: every non-GET request to `/api/*` must send header `X-CSRF-Token` equal to the
  `moloko_csrf` cookie. Get one with `GET /auth/csrf` (the web client does this automatically).
  Tokens are bound to the session and rotate on login/logout.
- Responses carry `X-Request-ID` and `Cache-Control: no-store`.
- Pagination (`limit`, `cursor`) and `Idempotency-Key` apply to list/work-starting endpoints from Sprint 2+.

### Error codes in use

| HTTP | code | When |
|---|---|---|
| 401 | `not_authenticated` | No/invalid/expired/revoked session |
| 401 | `invalid_credentials` | Wrong username or password (same answer for unknown users) |
| 403 | `csrf_failed` | Missing/mismatched/forged CSRF token |
| 404 | `not_found` | Unknown route |
| 405 | `method_not_allowed` | |
| 422 | `validation_error` | Body/params failed validation |
| 429 | `too_many_attempts` | Login locked out; see `Retry-After` |
| 500 | `internal_error` | Unexpected bug (details only in server log) |
| 503 | `database_unavailable` / `redis_unavailable` | A dependency is down; see `Retry-After` |

## Endpoints — auth & health (Sprint 1)

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/health` | public | Readiness: `{"status":"ok"\|"degraded","version","checks":{"database","redis"}}`; `503` when degraded |
| GET | `/health/live` | public | Liveness: `{"status":"ok"}` |
| GET | `/auth/csrf` | public | Sets `moloko_csrf` cookie, returns `{"csrf_token"}` |
| POST | `/auth/login` | public + CSRF | Body `{"username","password"}` → `{"user","session"}`; sets session cookie, rotates CSRF |
| POST | `/auth/logout` | public + CSRF | Revokes the current session (if any), clears the cookie → `204` |
| GET | `/auth/me` | session | `{"user":{"id","username","display_name"},"session":{"id","created_at","expires_at"}}` |

### Example (curl)

```bash
B=https://moloko.<tailnet>.ts.net
curl -c jar -b jar $B/api/v1/auth/csrf
CSRF=$(awk '$6=="moloko_csrf"{print $7}' jar)
curl -c jar -b jar -H 'Content-Type: application/json' -H "X-CSRF-Token: $CSRF" \
     -d '{"username":"me","password":"…"}' $B/api/v1/auth/login
curl -b jar $B/api/v1/auth/me
```

## Endpoints — models & providers (Sprint 2)

| Method | Path | Description |
|---|---|---|
| GET | `/providers/kinds` | Provider types available on this server (`mock` only with `ENABLE_MOCK_PROVIDER`) |
| GET | `/providers` | Configured providers. Keys are never returned: `api_key_source` = `stored` (`api_key_hint` "…abcd") / `environment` / `none` |
| POST | `/providers` | `{kind, name, api_key?, base_url?, enabled?}` — key encrypted at rest; audited |
| PATCH | `/providers/{id}` | `{name?, api_key?, clear_api_key?, base_url?, enabled?}`; audited |
| POST | `/providers/{id}/test` | Lists models with the stored credentials → `{ok, models_found, error_code, error_message}` |
| POST | `/providers/{id}/sync-models` | Imports the provider's model list → `{added, total}` |
| GET | `/models` | Enabled models (chat picker). `?include_disabled=true` for settings |
| POST | `/models` | `{provider_id, model, display_name?}` — add a model by id |
| PATCH | `/models/{id}` | `{display_name?, enabled?, is_default?, input_price_per_mtok?, output_price_per_mtok?, params?{temperature,max_tokens}}` |

## Endpoints — chat (Sprint 2)

| Method | Path | Description |
|---|---|---|
| GET | `/chats?limit&cursor` | Conversations, most recent first; `{items, next_cursor}` |
| POST | `/chats` | `{title?, model_config_id?}` |
| GET / PATCH / DELETE | `/chats/{id}` | Read, rename / change model, delete (cascades messages; audited) |
| GET | `/chats/{id}/messages?limit&cursor` | Newest page first, items oldest→newest; `next_cursor` = older |
| POST | `/chats/{id}/messages` | `{content, model_config_id?}` → **SSE**: `message.created` `{user_message, assistant_message}`, `message.delta` `{message_id, text}`…, then `message.completed` or `message.failed` `{message}`. Heartbeat comments every 15 s. `409 generation_in_progress` if an answer is running; `409 no_model_configured` / `model_unavailable` |
| GET | `/chats/{id}/messages/{mid}/stream` | **SSE** re-attach: `message.snapshot` `{text}` then deltas, or the saved final event if already finished |
| POST | `/chats/{id}/messages/{mid}/cancel` | Stop a running answer → `{cancelled}`; the partial text is kept with status `cancelled` |

Assistant message `status`: `streaming` → `completed` \| `failed` (with `error_code`, `error_message`, `error_id`) \| `cancelled`.
Error codes: `provider_auth_failed`, `provider_rate_limited`, `provider_timeout`, `provider_unavailable`, `provider_bad_request`, `provider_model_not_found`, `provider_unknown`, `interrupted` (server restarted mid-answer), `internal_error`.
