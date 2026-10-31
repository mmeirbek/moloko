# Database

PostgreSQL 17 is the single durable store (spec invariant 2). Schema is managed only by
Alembic migrations in `apps/api/migrations/versions/`.

## Conventions

- UUID primary keys (generated in Python, `uuid4`). `timestamptz` everywhere (UTC).
- `created_at` / `updated_at` on every table except append-only ones.
- Every owned table gets a `user_id` (multi-user later without reshaping data).
- Constraint/index names come from the naming convention in `app/models/base.py`.
- A test (`tests/test_migrations_and_audit.py`) runs upgrade → compare with models → downgrade → upgrade
  on a scratch database, so models and migrations can't drift.

## Tables (revision 0001)

### `users`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| username | varchar(64) unique | stored lower-case; created via CLI |
| password_hash | varchar(255) | argon2id |
| display_name | varchar(128) null | |
| is_active | bool default true | inactive users cannot log in; their sessions stop working |
| last_login_at | timestamptz null | |
| created_at, updated_at | timestamptz | |

### `sessions`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| user_id | uuid FK → users (cascade) | indexed |
| token_hash | varchar(64) unique | SHA-256 of the cookie token; the raw token is never stored |
| expires_at | timestamptz | indexed; absolute expiry |
| last_seen_at | timestamptz | updated at most every `SESSION_TOUCH_INTERVAL_SECONDS` |
| revoked_at | timestamptz null | set on logout / password reset |
| ip_address, user_agent | varchar null | informational |
| created_at, updated_at | timestamptz | |

### `audit_logs` (append-only)
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| created_at | timestamptz | |
| actor_type | varchar(32) | `user` \| `agent` \| `system` \| `anonymous` |
| actor_id, user_id | uuid null | **no FK** — history survives account deletion |
| action | varchar(64) | e.g. `auth.login`, `auth.login_failed`, `auth.login_blocked`, `auth.logout`, `user.created`, `user.password_reset` |
| outcome | varchar(16) | `success` \| `failure` \| `denied` |
| resource_type, resource_id | varchar null | |
| ip_address | varchar null | |
| details | jsonb | never secrets; failed logins store only `subject_key` (hash of the username) |

Trigger `audit_logs_append_only` raises on any UPDATE or DELETE. Index `(action, created_at)`
serves the login lockout query.

## Workflow

```bash
cd apps/api
uv run alembic revision --autogenerate -m "add conversations"   # then review the file
uv run alembic upgrade head
```
In Docker, the backend entrypoint applies pending migrations on start.
