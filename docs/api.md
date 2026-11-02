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
| 403 | `invalid_password` | A change confirmed with the wrong password (counts toward the login lockout) |
| 404 | `not_found` | Unknown route |
| 405 | `method_not_allowed` | |
| 422 | `validation_error` | Body/params failed validation |
| 422 | `limit_too_high` | A per-agent limit above the global one (`details: {field, max}`) |
| 422 | `invalid_profile_text` / `profile_text_too_long` | A profile text with line breaks, tabs or other control/invisible characters (`details: {field}`) / longer than `ADDRESS_AS_MAX_CHARS` (form of address) or 128 (display name) (`details: {field, max}`) |
| 409 | `agent_not_archived` / `agent_not_restorable` / `agent_name_taken` | Restoring an agent that is already in the office / a subagent or the Orchestrator / under a name another agent in the office has (`details: {field, name, agent_id}`) |
| 422 | `session_ttl_out_of_range` | Session lifetime outside `SESSION_TTL_MIN_HOURS..SESSION_TTL_MAX_HOURS` (`details: {field, min, max}`) |
| 422 | `invalid_memory` / `memory_too_long` | Memory scope rules broken / entry longer than `MEMORY_ENTRY_MAX_CHARS` |
| 409 | `approval_not_pending` | The approval was already answered or expired |
| 422 | `unknown_tool` / `invalid_path` / `category_fixed` | Unknown tool name; workspace path outside the workspace; category of a built-in tool |
| 422 | `invalid_attachment` / `attachment_too_large` | Not a UTF-8 text file / larger than `CHAT_ATTACHMENT_MAX_BYTES` |
| 404 | `passkeys_disabled` | Passkeys are off on this server (`WEBAUTHN_RP_ID` / `WEBAUTHN_ORIGINS` unset) |
| 401 | `passkey_rejected` | Passkey sign-in failed (unknown passkey, bad signature, other site, no user verification…) — one answer for every reason |
| 401 / 400 | `passkey_expired` | The passkey prompt's challenge is gone (too old, already used, other browser/session); 401 at sign-in, 400 when adding |
| 400 | `passkey_invalid` | A new passkey could not be verified |
| 409 | `passkey_limit_reached` / `passkey_already_registered` | `WEBAUTHN_MAX_CREDENTIALS` reached (`details: {max}`) / that credential is already saved |
| 429 | `too_many_attempts` | Login (or a password confirmation) locked out; see `Retry-After` |
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
| GET | `/auth/me` | session | `{"user":{"id","username","display_name","address_as"},"session":{"id","created_at","expires_at"}}` — `address_as`: how moloko addresses the owner (null = no particular form) |
| PATCH | `/auth/profile` | session + CSRF | Body `{"address_as"?: string\|null, "display_name"?: string\|null}` — only the fields sent change → `UserOut` `{"id","username","display_name","address_as"}`. Text is trimmed and inner whitespace collapsed; blank or null clears; line breaks/control/invisible characters → `422 invalid_profile_text`; longer than `ADDRESS_AS_MAX_CHARS` (default 80) / 128 → `422 profile_text_too_long`. No password. A real change is audited (`user.profile_updated`, old and new values). When set, the chat, agent runs and the Orchestrator get the instruction "Always address the owner as «…»". CLI: `python -m app.cli set-address --username me --address "…"` / `--clear` |
| GET | `/auth/session-settings` | session | `{"ttl_hours","default_ttl_hours","min_hours","max_hours","uses_default","current_session_expires_at"}` — `ttl_hours` is the effective lifetime of sign-ins |
| PUT | `/auth/session-settings` | session + CSRF | Body `{"ttl_hours": int\|null, "password"}` (`null` = back to `SESSION_TTL_HOURS`) → same shape. The current session lasts the new lifetime from now (cookies re-issued); the user's other sessions are only shortened to it, never extended. Wrong password → `403 invalid_password`, counted toward the login lockout (`429 too_many_attempts`); out of bounds → `422 session_ttl_out_of_range`. Audited (`auth.session_ttl_changed` / `auth.password_confirm_failed`) |

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
| GET | `/system/limits` | Global limits: `max_steps_per_run, run_timeout_seconds, max_active_parts_per_run, orchestrator_max_new_agents, memory_context_max_chars, memory_entry_max_chars` |
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
| GET | `/costs?month=YYYY-MM` | `{month, spent_usd, input_tokens, output_tokens, calls, unpriced_calls, budget {monthly_limit_usd, warn_percent, hard_stop, percent}, by_agent[], by_model[], by_day[]}` |
| PUT | `/costs/budget` | `{monthly_limit_usd?, warn_percent, hard_stop}`; `409 budget_exceeded` is returned by model calls when "stop at the limit" is on and the month is used up |
| POST | `/chats/{id}/attachments` | now also pictures (PNG/JPEG/WebP/GIF) and PDFs; `{…, kind: text\|image\|pdf, pages?}` |
| GET | `/chats/{id}/attachments/{aid}/content` | The file (pictures inline, other files as a download) |
| POST | `/chats/{id}/attachments` | (2026-11-02) **any type, size and number**: the body is streamed to disk; `kind: text\|image\|pdf\|file` (`file` = any other type, described to the model by name/type/size); optional limits `CHAT_ATTACHMENT_MAX_BYTES` → `413 attachment_too_large`, `CHAT_ATTACHMENTS_PER_MESSAGE` (0 = none); `507 insufficient_storage` when the disk would fall below `CHAT_UPLOAD_MIN_FREE_BYTES` |

Realtime: `budget.warning` with `{month, percent, spent_usd, limit_usd, hard_stop}`.
| GET / PUT | `/ai/settings` | Voice & search: `{provider_id?, transcription_model?, embedding_model?, embedding_dimensions?, semantic_search}`; GET also `{active_provider_id, active_provider_name, available}` |
| POST | `/ai/transcribe` | multipart `audio` (+ `language`) → `{text}`; `409 ai_service_unavailable` without an OpenAI-type provider, `413 audio_too_large` |
| GET | `/ai/settings` | (2026-11-02) also `voice_available`, `voice_engine: local\|provider\|null`, `voice_model`, `local_stt_status: off\|ready\|loading\|missing\|error\|unreachable`, `local_stt_model`; `available` is for search by meaning |
| POST | `/ai/transcribe` | (2026-11-02) the local Whisper service first (`STT_URL`), then the provider; `language` "" = detect, `ru`/`en` = hint; ≤ `VOICE_UPLOAD_MAX_BYTES`; the provider path also ≤ `TRANSCRIPTION_PROVIDER_MAX_BYTES` (25 MB); `503 voice_unavailable` when the local model is still loading and there is no provider; `422 audio_unreadable` |
| GET | `/search?q&types=memory,file,attachment,task,agent_message,chat_message&limit` | `{query, hits[{source_type, source_id, title, snippet, score, mode: semantic\|words, agent_id?, workspace_id?, conversation_id?, peer_agent_id?, run_id?, source_at?, status?, role?, message_type?, task_id?, agent_name?, peer_agent_name?}]}` (default types: memory, file, attachment) |
| GET | `/search/status` | `{chunks, with_vectors, sources}` |
| GET | `/tasks/{id}/export.md` | The task and its result as Markdown (download) |
| POST | `/tasks/{id}/export.pdf` | PDF of the result (`409 pdf_unavailable` without the sandbox browser, `409 nothing_to_export`) |
| GET | `/workspaces/{id}/raw?path` | A screenshot (inline) or PDF (download) from a workspace |

Sandbox runner (internal, token): `POST /v1/browse` `{workspace_id, mode: page\|pdf, url?, source?, screenshot?, dom?, pdf?, width, height}`.

## Endpoints — owner requests (2026-11-02)

| Method | Path | Description |
|---|---|---|
| GET | `/agents/archived` | Agents removed from the office that can be brought back: the owner's persistent (`autonomous`) agents with `archived_at` set, newest removal first → `AgentOut[]`. Subagents and the Orchestrator are never listed |
| POST | `/agents/{id}/restore` | Optional body `{"name"?: string}` (1–100 chars; come back under a new name) → `AgentOut`: `archived_at: null`, `status: "idle"`, `current_task_id: null`; settings, memory and history unchanged (`config_version` +1 only when renamed). Events: `agent.status_changed` (reason `restored`, only if it was `completed`/`failed`) and `agent.updated` `{changed: ["archived_at"(, "name")], agent}`; audit `agent.restored` `{name, renamed_from?}`. Errors: `404 not_found` (not the owner's), `409 agent_not_restorable` (subagent or Orchestrator), `409 agent_not_archived` (already in the office), `409 agent_name_taken` (another agent in the office has the name; retry with `name`) |
| POST | `/agents/{id}/save-template` | Optional body `{"name"?: string}` (default: the agent's name) → `201 AgentTemplateOut` (`source: "own"`). Copies name, description, specialization, instructions, model, autonomy, tools + per-tool rules, limits, memory settings and the monthly budget — **not** memory entries, history or the project workspace. Audit `agent_template.saved` `{name, agent_id}`. Errors: `404` (not the owner's / archived), `409 agent_not_templatable` (Orchestrator or subagent), `409 template_name_taken` (`details.name`), `409 template_limit_reached` (`details.max` = `AGENT_TEMPLATES_MAX`) |
| GET | `/agents/templates?locale` | Built-in templates, then the owner's own (newest first): `{key, source: builtin\|own, id?, name, description, specialization, allowed_tools, autonomy_level, model_config_id?, monthly_budget_usd?, created_at?}`. `key` is what `from-template` takes: the built-in key or the own template's id |
| POST | `/agents/from-template` | `template` may now be an own template's id. Tools that no longer exist are left out and limits above today's global ones are lowered to them; the name gets " 2", " 3"… when taken. Audit `agent.created` carries `{template, template_source}` |
| DELETE | `/agents/templates/{id}` | `204`; own templates only (`404` otherwise). Agents made from it stay. Audit `agent_template.deleted` `{name}` |
| GET | `/agents/{id}/budget` | `{agent_id, budget_agent_id, budget_agent_name, month, spent_usd, monthly_budget_usd?, warn_percent, percent?, exceeded}` — this month (UTC) against the budget that applies: the agent's own, or for a subagent the one of the agent above it |
| POST / PATCH | `/agents`, `/agents/{id}` | now also `monthly_budget_usd` (USD, > 0, ≤ 1 000 000, 2 decimals; `null` = no own limit; a live subagent cannot get one: `409 invalid_transition`). Lowering it below this month's spending warns at once |
| GET | `/costs` | `by_agent[]` now has one row per budget holder (an agent with its subagents' calls): `{…, subagents_cost_usd, monthly_budget_usd?, percent?}` (`percent` only for the current month); new top-level `agent_warn_percent` |

Per-agent budgets: model calls of an agent (and of its subagents) are refused with `agent_budget_exceeded` once its month is used up (always, independent of the global "stop at the limit"); its task fails with that code and a message naming the agent and the amounts. Realtime: `budget.warning` with `{scope: "agent", agent_id, agent_name, month, percent, spent_usd, limit_usd, hard_stop: true}` at `AGENT_BUDGET_WARN_PERCENT` and at 100 % (once per month and limit; a changed limit starts over); push title "«name»: N% бюджета агента на месяц", link `/office/agents/{id}`.

## Endpoints — scheduled tasks (owner request, 2026-11-02)

A schedule starts a task like `POST /runs` (`target: "orchestrator"`) or `POST /agents/{id}/run` (`target: "agent"` + `agent_id` of a persistent agent). The rule is local time in `timezone` (IANA). `recurrence`: `{kind: "once", run_at}` (a date-time without offset is read in `timezone`) · `{kind: "hourly", interval_hours: 1|2|3|4|6|8|12, time?}` (the same times every day, from `time`, default 00:00) · `{kind: "daily", time}` · `{kind: "weekly", weekdays: [1…7] (1 = Monday), time}` · `{kind: "monthly", day_of_month: 1…31, time}` (shorter months: last day); `time` is `"HH:MM"`.

| Method | Path | Description |
|---|---|---|
| GET | `/schedules` | `{items: ScheduleOut[], max_schedules, min_interval_minutes}` (oldest first) |
| POST | `/schedules` | `{title, description?, target?, agent_id?, recurrence, timezone, enabled?}` → `201 ScheduleOut` with the computed `next_run_at` |
| POST | `/schedules/preview` | `{recurrence, timezone}` → `{next_runs: [3 × UTC]}`; nothing is saved |
| GET | `/schedules/{id}` | `ScheduleOut` |
| PATCH | `/schedules/{id}` | Any of the create fields; `recurrence` is replaced as a whole; switching on re-plans from now |
| DELETE | `/schedules/{id}` | `204`; tasks it started stay |
| POST | `/schedules/{id}/run-now` | Start now (`Idempotency-Key` supported); `next_run_at` is unchanged → `{schedule, task, run}` |

`ScheduleOut`: `{id, title, description, target, agent_id, recurrence{kind, time, weekdays, day_of_month, interval_hours, run_at}, timezone, enabled, next_run_at, busy_since, last_run_at, last_task_id, last_task_status, last_outcome: started|skipped|failed|null, last_reason, created_at, updated_at}`. Tasks it starts have `created_by: "schedule"` and `extra.schedule_id`.

Errors: `422 invalid_recurrence` (`details.field`: kind, time, weekdays, day_of_month, interval_hours, run_at) · `422 invalid_timezone` · `422 interval_too_short` (below `SCHEDULE_MIN_INTERVAL_MINUTES`) · `422 schedule_in_past` (a one-off whose moment passed) · `422 invalid_schedule_target` · `404` agent · `409 agent_archived` · `409 too_many_schedules` (`SCHEDULES_MAX_PER_USER`). Run-now refusals are the ones of a manual start: `409 agent_busy`, `409 engine_stopped`, `409 budget_exceeded`.

Realtime (payload `{schedule_id, title, enabled, next_run_at, …}`, never `task`): `schedule.created`, `schedule.updated` (`changed[]` or `reason: "waiting_for_agent"`), `schedule.deleted`, `schedule.fired` (`trigger: schedule|run_now`, with `task_id`/`run_id`), `schedule.skipped` (`reason`: agent_busy, engine_stopped, budget_exceeded, agent_archived, start_failed).

## Endpoints — passkeys (sign in with Face ID / Touch ID, owner request 2026-11-02)

Off (`404 passkeys_disabled`, list says `enabled: false`) until `WEBAUTHN_RP_ID` and `WEBAUTHN_ORIGINS` are set. Options are WebAuthn's JSON form (binary values base64url); credentials are the browser's `RegistrationResponseJSON` / `AuthenticationResponseJSON` (`PublicKeyCredential.toJSON()` shape). All POST/PATCH/DELETE need CSRF.

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/auth/passkeys` | session | `{"enabled", "rp_id", "max_passkeys", "passkeys": [{"id","name","created_at","last_used_at","backed_up","transports"}]}` |
| POST | `/auth/passkeys/register/options` | session | Body `{"password"}` → `{"options": PublicKeyCredentialCreationOptionsJSON, "expires_in_seconds"}` (resident key + user verification required, attestation `none`, the owner's passkeys in `excludeCredentials`). Wrong password → `403 invalid_password` (counts toward the login lockout, audit `auth.password_confirm_failed` purpose `passkey_register`); `429`; `409 passkey_limit_reached` |
| POST | `/auth/passkeys/register/verify` | session | Body `{"credential", "name"}` (1–64 chars, one line) → `201 PasskeyOut`. Challenge from this session only; `400 passkey_expired` / `passkey_invalid` (audit `auth.passkey_add_failed`), `409 passkey_already_registered`. Audit `auth.passkey_added` |
| PATCH | `/auth/passkeys/{id}` | session | Body `{"name"}` → `PasskeyOut`; audit `auth.passkey_renamed` |
| DELETE | `/auth/passkeys/{id}` | session | Body `{"password"}` → `204`; wrong password → `403 invalid_password` (counts toward the lockout); audit `auth.passkey_deleted` |
| POST | `/auth/passkeys/login/options` | **public** | No body → `{"options": PublicKeyCredentialRequestOptionsJSON, "expires_in_seconds"}` (no `allowCredentials`: the device offers its passkeys; user verification required). Sets the `moloko_passkey` flow cookie (HttpOnly, SameSite=Strict, path `/api/v1/auth/passkeys/login`) that the challenge is bound to |
| POST | `/auth/passkeys/login/verify` | **public** | Body `{"credential"}` → `{"user","session"}` exactly like `/auth/login` (session cookie with the owner's lifetime, CSRF rotated, audit `auth.login` `{method: "passkey", passkey_id}`). `401 passkey_rejected` / `401 passkey_expired` (audit `auth.login_failed` with `method: passkey`, counted toward the lockout), `429 too_many_attempts` |
