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

## Endpoints (Sprint 1)

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
