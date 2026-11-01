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

## Tables (revision 0002 — Sprint 2)

### `model_providers`
`id, user_id → users, kind (openai|anthropic|mock), name (unique per user), base_url?, api_key_encrypted? (Fernet "v1:…"), api_key_hint? ("…abcd"), enabled, created_at, updated_at`

### `model_configs`
`id, user_id, provider_id → model_providers (cascade), model (provider's id; unique per provider), display_name?, enabled, is_default, input_price_per_mtok?, output_price_per_mtok? (numeric, USD), params jsonb {temperature?, max_tokens?}, created_at, updated_at`

### `conversations`
`id, user_id, title, model_config_id? → model_configs (set null), last_message_at, created_at, updated_at` — index `(user_id, last_message_at)`.

### `messages`
`id, conversation_id → conversations (cascade), user_id, role (user|assistant), content, status (streaming|completed|failed|cancelled), model_config_id?, provider_kind?, model?, input_tokens?, output_tokens?, cost_usd?, error_code?, error_message?, error_id?, agent_run_id? (Sprint 4), completed_at?, created_at, updated_at` — index `(conversation_id, created_at)`.
An assistant reply is created as `streaming` in the same transaction as the question (1 µs later, so ordering is stable).

## Tables (revision 0003 — Sprint 3)

- **`agents`** — profile (spec 8.3): `name, description, agent_type (orchestrator|subagent|autonomous), specialization, model_config_id, system_prompt, autonomy_level, allowed_tools jsonb[], permissions jsonb, status (AgentStatus), paused_from, current_task_id, parent_agent_id, run_id (subagents), depth, limits jsonb, memory_settings jsonb, runtime, config_version, archived_at`.
- **`agent_runs`** — one execution: `agent_id, task_id, parent_run_id, status (TaskStatus values), phase, plan jsonb, state jsonb (checkpoint: transcript, elapsed, in_flight), steps, usage jsonb, result, error_*, conversation_id, started_at, finished_at`.
- **`tasks`** — `title, description, task_type, status, priority (-1/0/1), deadline, agent_id, run_id, parent_task_id (subtasks), attempt, retry_of_id, depends_on jsonb, progress, result, status_reason, error_*, created_by, extra jsonb, started_at, completed_at`.
- **`agent_events`** — append-only (trigger): `seq bigint identity unique, type, version, created_at, user_id, agent_id, task_id, run_id, payload jsonb`; indexes `(user_id, seq)`, `(run_id, seq)`, `(task_id, seq)`.
- **`idempotency_keys`** — `(user_id, scope, key)` unique, `request_hash, response_status, response_body`.
- **`system_settings`** — `(user_id, key)` unique, `value jsonb` (kill switch).

## Tables (revision 0004 — Sprint 4)

- **`agent_messages`** — `created_at, user_id, run_id (root run), sender_agent_id, receiver_agent_id, task_id?, message_type (task_result|error|context|note), content jsonb {summary, result, artifacts, notes}, status (delivered|refused), error?`.
- Subagents are `agents` rows with `agent_type = subagent`, `parent_agent_id`, `run_id` = root run, `depth`, `runtime` (`orchestrator` if it may delegate further).

## Tables (revision 0005 — Sprint 6)

- **`memories`** — `user_id, agent_id? (NULL = shared; FK → agents, cascade), memory_type (user|agent|project|task_context|conversation_context), project?, title, content, pinned, revision, created_by (user|agent|system), created_at, updated_at`; index `(user_id, agent_id)`.
- **`memory_revisions`** — one row per saved version: `memory_id (FK → memories, cascade), user_id, revision, memory_type, agent_id, project, title, content, pinned, changed_by, created_at`; unique `(memory_id, revision)`. Forgetting a memory deletes its revisions too.
- `agents.memory_settings` is validated: `{enabled, include_shared, projects[], max_context_chars}` (defaults omitted).

## Tables (revision 0006 — Sprint 7)

- **`tools`** — `(user_id, name)` unique; `source (builtin|mcp), server_id?, remote_name?, description, category?, input_schema jsonb, enabled, available`.
- **`mcp_servers`** — `(user_id, slug)` unique; `name, url, secret_encrypted?, enabled, status, last_error, last_checked_at, server_info jsonb`.
- **`integrations`** — `(user_id, kind)` unique (`github`); `config jsonb (login, allowed_repos), secret_encrypted, secret_hint, enabled, status, last_error, last_checked_at`.
- **`workspaces`** — `name, kind (task|project), task_id? (root task), cleaned_at?`; **`workspace_files`** — `(workspace_id, path)` unique; `size, sha256, deleted, last_task_id, last_agent_id, last_tool_call_id`.
- **`tool_calls`** — `(run_id, call_id)` unique; `task_id, agent_id, step, tool_name, category, args jsonb, args_hash, decision, decision_reason, approval_id, status, result, is_error, duration_ms, started_at, finished_at`.
- **`approvals`** — `agent_id, task_id, run_id, tool_call_id → tool_calls, tool_name, category, args (preview), args_hash, summary, resources jsonb, consequences, reason, status (pending|approved|rejected|expired|cancelled), expires_at, resolved_at, used_at`.
- `agents.workspace_id` → `workspaces` (project workspace, SET NULL).

## Tables (revision 0007 — Sprint 8)

- **`attachments`** — `user_id, conversation_id → conversations (cascade), message_id? → messages (cascade; NULL until sent), filename, content_type, size, sha256, text, created_at, updated_at`. Text files only; the content lives in PostgreSQL (and therefore in backups).

