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
| 422 | `limit_too_high` | A per-agent limit above the global one (`details: {field, max}`) |
| 422 | `invalid_memory` / `memory_too_long` | Memory scope rules broken / entry longer than `MEMORY_ENTRY_MAX_CHARS` |
| 409 | `approval_not_pending` | The approval was already answered or expired |
| 422 | `unknown_tool` / `invalid_path` / `category_fixed` | Unknown tool name; workspace path outside the workspace; category of a built-in tool |
| 422 | `invalid_attachment` / `attachment_too_large` | Not a UTF-8 text file / larger than `CHAT_ATTACHMENT_MAX_BYTES` |
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

## Endpoints — agents, tasks, events, system (Sprint 3)

| Method | Path | Description |
|---|---|---|
| GET | `/agents?agent_type&run_id&include_archived` | Agent profiles |
| POST | `/agents` | `{name, description?, agent_type?, specialization?, model_config_id?, system_prompt?, autonomy_level?, allowed_tools?, limits?{max_steps, run_timeout_seconds}, memory_settings?}` (subagents are created by the Orchestrator only) |
| GET / PATCH / DELETE | `/agents/{id}` | Read, edit (bumps `config_version`), archive (refused while busy) |
| POST | `/agents/{id}/run` | `{title, description}` or `{task_id}` → `{task, run}`; `Idempotency-Key` supported; `409 agent_busy` / `engine_stopped` |
| POST | `/agents/{id}/pause` · `/resume` · `/stop` | Run control (pause keeps the checkpoint; resume re-queues; stop cancels the current task) |
| GET | `/tasks?status=all\|active\|completed\|failed\|cancelled&q&agent_id&parent_task_id&include_subtasks&limit&cursor` | Task list (top-level by default) |
| POST | `/tasks` | `{title, description?, agent_id?, priority?, deadline?, start?}`; `Idempotency-Key` |
| GET | `/tasks/{id}` | `{task, subtasks, run}` |
| PATCH | `/tasks/{id}` | Edit while active; `agent_id` only before start |
| POST | `/tasks/{id}/cancel` | Cancels the task and its subtasks |
| POST | `/tasks/{id}/retry` | New task with `attempt + 1`, `retry_of_id`; the old one keeps its history |
| GET | `/tasks/{id}/events` | Execution history (ordered by `seq`) |
| GET | `/events?after_seq&run_id&task_id&agent_id&limit&latest` · `/events/{id}` | Event log (oldest → newest; `latest=true` returns the newest `limit` events — used by the Agent Inspector) |
| GET | `/system/state` | `{engine_stopped, active_tasks}` |
| POST | `/system/stop-all` · `/system/start` | Kill switch |

### Realtime: `WS /ws/v1/events`

```
client → {"type":"hello","last_seq":<int|null>,"csrf":"<moloko_csrf cookie>"}
server → {"type":"snapshot","seq":N,"agents":[…],"tasks":[…],"runs":[…],"approvals":[]}   (no/invalid/too-old last_seq)
      or {"type":"event","event":{…envelope}} …  {"type":"resumed","seq":N}                  (replay of what was missed)
server → {"type":"event","event":{…}}                                                         (live)
client ↔ {"type":"ping"} / {"type":"pong"}  (every 25 s)
```
Close codes: `4401` not authenticated / session ended, `4403` bad CSRF in hello, `4400` bad hello. Envelope = spec 10.1; schemas in `packages/agent-contracts/schemas/`.

## Endpoints — orchestrated runs (Sprint 4)

| Method | Path | Description |
|---|---|---|
| POST | `/runs` | `{title, description}` → `{task, run}`: give a task to the Orchestrator (created on first use). `Idempotency-Key` |
| GET | `/runs?active&limit` | Orchestrated runs, newest first |
| GET | `/runs/{id}` | `{run (with plan), task, subagents, subtasks, messages}` |
| POST | `/chats/{id}/handoff` | `{content}` → `{task, run}`: the question goes to the Orchestrator; the result is posted back into the chat |

Plan format and limits: see `docs/decisions.md` (Sprint 4). Subtasks are tasks with `task_type = subtask | review` and `parent_task_id`; dependencies in `depends_on` (task ids); the subagent's plan key in `extra.key`.

## Endpoints — autonomous agents & memory (Sprint 6)

| Method | Path | Description |
|---|---|---|
| GET | `/system/limits` | Global limits: `max_steps_per_run, run_timeout_seconds, max_active_subagents_per_run, max_subagent_depth, memory_context_max_chars, memory_entry_max_chars` |
| POST / PATCH | `/agents` · `/agents/{id}` | `limits` and `memory_settings {enabled, include_shared, projects[], max_context_chars}` are validated; values above the global limits → `422 limit_too_high` |
| GET | `/agents/{id}/memory-context` | `{enabled, text, included[], omitted[], chars, max_chars}` — exactly what the agent's prompt receives |
| GET | `/memories?agent_id&shared&memory_type&project&q&limit` | Memory entries, pinned first then newest |
| POST | `/memories` | `{memory_type, agent_id?, project?, title, content, pinned?}` (scope rules: `docs/decisions.md`, Sprint 6) |
| GET / PATCH / DELETE | `/memories/{id}` | Read; edit (`title, content, project, pinned` — saves a new revision); forget (deletes the entry and its history) |
| GET | `/memories/{id}/revisions` | Change history, newest first |
| GET | `/tasks?agent_id={id}&status=all` | Per-agent task history (already available since Sprint 3) |

## Endpoints — tools & integrations (Sprint 7)

| Method | Path | Description |
|---|---|---|
| GET | `/tools` | Built-in + MCP tools: `name, title, description, group, category, source, enabled, available, input_schema` |
| PATCH | `/tools/{name}` | `{enabled?, category?}` (category only for MCP tools) |
| GET | `/approvals?status&task_id&limit` · `/approvals/{id}` | Approval requests (pending ones are also in the WS snapshot) |
| POST | `/approvals/{id}/approve` · `/reject` · `/cancel-task` | Decide ONE operation; cancel-task cancels the whole run |
| GET | `/integrations/status` | Sandbox (configured, ok, image, limits, network, allowed commands), web search, GitHub |
| GET / PUT | `/integrations/github` | `{token?, clear_token?, enabled?, allowed_repos?}` — the token is never returned (`token_hint` only) |
| POST | `/integrations/github/test` | Checks the token (`login`) |
| GET / POST | `/mcp-servers` | `{name, url, token?}`; tools are listed and start disabled |
| PATCH / DELETE | `/mcp-servers/{id}` | Edit (new URL/token → tools off again) / remove with its tools |
| POST | `/mcp-servers/{id}/refresh` | Reconnect and list tools |
| GET / POST | `/workspaces?kind&limit` | Workspaces; POST `{name}` creates a project workspace |
| GET | `/workspaces/{id}/files?path` · `/workspaces/{id}/file?path` | Read-only browsing (text up to 200 KB) |
| GET | `/tasks/{id}/workspace` · `/tasks/{id}/tool-calls` | A task's workspace; its tool calls (decision, status, args preview, result) |
| GET | `/audit?action&outcome&cursor&limit` | Audit journal, newest first (`action` is a prefix, e.g. `tool.`) |
| POST / PATCH | `/agents` · `/agents/{id}` | now also `allowed_tools` (validated), `tool_overrides {name: approve\|deny}`, `workspace_id` |

Realtime: `approval.required` / `approval.resolved` with `{approval}`; `agent.message` with `kind: "tool_call"` for each finished call.

## Endpoints — Sprint 8

| Method | Path | Description |
|---|---|---|
| POST | `/chats/{id}/attachments` | multipart `file` (UTF-8 text) → `{id, filename, content_type, size, created_at}` |
| POST | `/chats/{id}/messages` | now also `attachment_ids[]` (≤ 5, uploaded to this chat, not yet sent); messages carry `attachments[]` |
| GET | `/push/key` | VAPID public key for `PushManager.subscribe` (created on first use; `409 push_unavailable` without `APP_ENCRYPTION_KEY`) |
| GET / POST / DELETE | `/push/subscriptions` | This owner's devices; POST `{endpoint, keys {p256dh, auth}, kinds[], locale, label}` adds/updates (`422 invalid_subscription` for a host outside `PUSH_ALLOWED_HOSTS` or bad keys); DELETE `?endpoint=` |
| POST | `/mcp-servers/github` | `{readonly = true, toolsets = [repos, issues, pull_requests]}` — the official GitHub MCP server with the Integrations → GitHub token (`409 github_not_connected`); calling again updates the options (tools off again) |
| GET | `/runs/{id}` | now also `team[]`: the owner's own agents that took parts of the plan |
| GET | `/system/storage` | `{backups: {configured, last, age_hours, drill, files[], same_disk_as_data}, disks[], warnings[]}` |

## Endpoints — owner requests (2026-11-01)

| Method | Path | Description |
|---|---|---|
| GET | `/agents/templates?locale` | Ready-made agents: `{key, name, description, specialization, allowed_tools}` |
| POST | `/agents/from-template` | `{template, name?, locale}` → a new idle persistent agent (404 for an unknown template) |
