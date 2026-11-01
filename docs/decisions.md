# Decisions

Choices made where the spec (`shvluup-spec.md`) is silent or leaves an option open,
plus every deviation from it. Newest last within each sprint. Format: date — decision — reason.

## Owner decisions

| Date | Decision |
|---|---|
| 2026-10-31 | The product is named **moloko** (lowercase), not "shvluup". Applies to UI, code, packages, Docker, docs. The spec file keeps its name `shvluup-spec.md` so existing references still work; a note at its top records the rename. |
| 2026-10-31 | Brand mark = the owner's pixel-art logo (cow in a meadow + "moloko" wordmark, navy background). The owner uploads the original PNG to `apps/web/public/brand/`; until then `components/brand/logo.tsx` draws a placeholder in the same palette. |

## Sprint 1 — Infrastructure foundation

| Date | Decision | Reason |
|---|---|---|
| 2026-10-31 | **Caddy** (not Nginx) as the reverse proxy; config in `infrastructure/caddy/` instead of `infrastructure/nginx/`. | Tiny config, WebSockets/SSE work without extra directives. |
| 2026-10-31 | **TLS via Tailscale Serve**; Caddy listens on plain HTTP bound to `127.0.0.1:8080` only. | Spec 20: HTTPS via Tailscale Serve/MagicDNS, nothing on the LAN or internet. Binding to loopback means the only way in is the tailnet. |
| 2026-10-31 | **Same origin for UI and API**: Caddy routes `/api/*` and `/ws/*` to the backend, everything else to Next.js. CORS is off unless `CORS_ALLOWED_ORIGINS` is set. | No CORS surface, cookies stay first-party. |
| 2026-10-31 | **Server-side sessions** in PostgreSQL (`sessions` table). Cookie holds a 256-bit random token; DB stores only its SHA-256. Absolute expiry `SESSION_TTL_HOURS` (168), `last_seen_at` touched at most every 5 min. Cookie: `HttpOnly`, `Secure`, `SameSite=Lax`. | Spec 20. Revocable (logout, password reset), survives restarts, a DB leak exposes no usable tokens. |
| 2026-10-31 | **CSRF = signed double-submit token bound to the session.** Token `nonce.HMAC(SECRET_KEY, nonce‖sha256(session cookie) or "anon")` in a JS-readable `SameSite=Strict` cookie, echoed in `X-CSRF-Token`. Enforced by a global pure-ASGI middleware for every non-GET `/api/*` request, including login. Rotated on login/logout. | Stateless, cannot be forged without the key, a token from one session is useless in another, and no endpoint can forget it. |
| 2026-10-31 | **Owner account created via CLI only** (`python -m app.cli create-owner`); refuses if any user exists. Password reset also via CLI and revokes all sessions. | Spec 25.2: no public registration. A first-run web setup page could be claimed by anyone on the tailnet. |
| 2026-10-31 | **Login brute-force protection counts failures in `audit_logs`** (per hashed username, `LOGIN_MAX_FAILURES`=5 per `LOGIN_LOCKOUT_SECONDS`=900; a successful login resets the window) and returns `429` + `Retry-After`. | Durable, no dependency on Redis being up, and the audit trail is needed anyway. Per-username (not per-IP) because behind Tailscale + proxies IPs are not a reliable key. |
| 2026-10-31 | Failed logins store **only a SHA-256 of the submitted username** (`subject_key`), never the raw value. | People sometimes type their password into the username field. |
| 2026-10-31 | **`audit_logs` is append-only at the database level**: a trigger rejects UPDATE and DELETE. No FK to `users`. | Spec 20 / invariant 11. Survives application bugs; history survives account deletion. Retention, when needed, will be an explicit migration. |
| 2026-10-31 | **Migrations run in the backend container entrypoint** (`wait-for-db` → `alembic upgrade head` → uvicorn). | Simplest correct option for a single backend instance; after a host reboot Docker restarts the container until PostgreSQL is up. Revisit when the worker (Sprint 3) also needs the schema — it will wait, not migrate. |
| 2026-10-31 | **Health**: `GET /api/v1/health` (readiness: DB + Redis, `503` when degraded) and `/api/v1/health/live` (liveness). The Docker health check uses readiness so `docker compose ps` shows real state. | Spec 21.1. |
| 2026-10-31 | Dependency outages surface as **`503 database_unavailable` / `redis_unavailable`** with an error id, not a generic 500. | Spec 22: clear user-facing message, technical details only in the server log. |
| 2026-10-31 | Uniform **error envelope** `{"error":{"id","code","message","details?"}}` for every error, including validation (which never echoes submitted values) and 404/405. The OpenAPI schema is patched to document it instead of FastAPI's default `HTTPValidationError`. | Spec 12; generated TS types must match reality. |
| 2026-10-31 | **Every API route requires a session unless allow-listed** (`PUBLIC_ROUTES` in `app/api/v1/router.py`); a test enumerates all routes from the OpenAPI schema and checks each returns 401 anonymously. Rule: never use `include_in_schema=False`. | Spec 20 "all API routes protected", enforced by a test rather than by memory. FastAPI 0.162 mounts routers lazily, so the schema is the stable way to enumerate routes. |
| 2026-10-31 | **No server-side auth redirect in Next.js** (`proxy.ts` removed). The client shell checks `GET /auth/me` and navigates with relative URLs. | Verified: Next 16 standalone builds absolute redirect URLs from its own bind address (`0.0.0.0:3000`), ignoring `Host`/`X-Forwarded-*`, which breaks behind Tailscale Serve → Caddy. The backend is the source of truth anyway. |
| 2026-10-31 | **i18n: next-intl without locale routing.** Locale from cookie `moloko_locale` → `Accept-Language` → default **`ru`**. Both `ru` and `en` complete; a test enforces identical keys. | Spec 26.6 leaves the default to the owner; the owner works in Russian. Change `defaultLocale` in `apps/web/i18n/config.ts` if needed. |
| 2026-10-31 | Docs language: owner-facing docs (`README.md`, `docs/deployment.md`) in **Russian**; agent-facing docs (spec, architecture, API, DB, security, decisions) in **English**. | Matches who reads them. |
| 2026-10-31 | **API types**: `scripts/export_openapi.py` writes `packages/shared-types/openapi.json`; `openapi-typescript` generates `src/api.gen.ts`. Both are committed; CI fails on drift. | Spec 12 conventions. Committing generated files keeps the web build independent of Python. |
| 2026-10-31 | **npm workspaces** (not pnpm) for the JS monorepo; **uv** for Python. Lockfiles committed. | npm ships with Node; uv gives a fast, reproducible lockfile. |
| 2026-10-31 | `packages/agent-contracts` and `packages/ui` are README-only placeholders. | Spec layout; contents arrive in Sprints 3–4. UI components live in `apps/web/components/ui` until a second consumer exists. |
| 2026-10-31 | **No worker container yet.** | ARQ worker is a Sprint 3 task; a stub would be dead code. |
| 2026-10-31 | **Redis without a password**, on the internal Docker network only (no host port, no route out). | Not reachable from anything but the backend. Revisit in Sprint 7 when sandbox containers exist. |
| 2026-10-31 | **Container hardening**: backend runs as uid 10001 with a read-only root FS, `cap_drop: ALL`, `no-new-privileges`; frontend non-root with `cap_drop: ALL`; Caddy keeps only `NET_BIND_SERVICE`. Image tags pinned to exact versions. | Spec 16/20 spirit; cheap to do from day one. |
| 2026-10-31 | `FORWARDED_ALLOW_IPS="*"` for uvicorn. | The backend has no published port; only Caddy can reach it. Client IPs are informational (audit), never used for authorization. |
| 2026-10-31 | **Redis 8 image** (tri-licensed RSALv2 / SSPLv1 / **AGPLv3**). | AGPLv3 is OSI-approved; we run the unmodified upstream image as a separate service, so no obligations arise for our code. Valkey (BSD) is a drop-in alternative if the owner prefers — tell the agent. |
| 2026-10-31 | Content-Security-Policy **not set yet**. | Next.js inline scripts need nonces; a weak CSP is noise. Scheduled for the Sprint 8 security review. |
| 2026-10-31 | Dev-only npm tooling (ESLint plugins, openapi-typescript) pulls a `minimatch` version with a moderate ReDoS advisory. `npm audit --omit=dev` is clean. | Not shipped, not exposed to input. Upgrade when the ESLint 9 ecosystem moves. |
| 2026-10-31 | ESLint **9** (not 10) and TypeScript **5.9** (not 7). | `eslint-plugin-react`/`-import` support ESLint ≤9; `openapi-typescript` and `typescript-eslint` require TypeScript <6.1. |

## Sprint 2 — Chat system

External repositories checked at sprint start (per `docs/external-repositories.md`):
**assistant-ui** (USE, conditional) — LICENSE verified MIT (github.com/assistant-ui/assistant-ui, "Copyright (c) 2026 AgentbaseAI Inc."), releases every few days (0.15.32 on 2026-10-28), no Vercel AI SDK dependency; its `useExternalStoreRuntime` drives it from our own state → **adopted** as the chat UI layer. **LibreChat / Open WebUI** (AVOID) — not used. **litellm** — not added (official SDKs only).

| Date | Decision | Reason |
|---|---|---|
| 2026-10-31 | **SSE for chat token streaming** (spec 26.2). `POST /chats/{id}/messages` answers with `text/event-stream`; `GET …/messages/{mid}/stream` re-attaches. | Plain HTTP, works through Caddy and Tailscale Serve, trivial to resume. WebSockets arrive in Sprint 3 for events. |
| 2026-10-31 | **Generations run as background asyncio tasks owned by the API process**, not by the request. Closing the browser doesn't stop or lose an answer; any device can re-attach. On startup, leftover `streaming` messages become `failed: interrupted`; on shutdown running ones are marked the same. | Spec invariants 3, 9, 10. Verified in Docker: a client disconnecting mid-stream still gets a completed, saved answer. |
| 2026-10-31 | The API must run as **one uvicorn process** (the stream registry and cancel are in-process). | Single-user server; revisit with Redis-backed cancellation if we ever scale out. |
| 2026-10-31 | **One running answer per conversation**, enforced with a row lock (`SELECT … FOR UPDATE`) → `409 generation_in_progress`. | Keeps history linear and context well-defined. |
| 2026-10-31 | OpenAI via the **Chat Completions API**, Anthropic via the **Messages API**, both through the official SDKs (openai 3.x, anthropic 2.x) with **SDK retries disabled**; the gateway retries retryable errors (rate limit, timeout, unavailable) with exponential backoff **only before the first streamed token**. | One retry policy for all providers; a half-streamed answer is never silently restarted. |
| 2026-10-31 | **Official base URLs are always passed explicitly.** | Verified: with `base_url=None` the SDKs read `OPENAI_BASE_URL` / `ANTHROPIC_BASE_URL` (and Anthropic also profile files) from the environment, which could redirect API keys. A test sets those vars to an attacker URL and checks the official host is used. |
| 2026-10-31 | Provider error messages are **redacted** (anything key-like) before logging; adapters normalise errors to `auth_failed / rate_limited / timeout / unavailable / bad_request / model_not_found / unknown`, surfaced as `provider_<kind>`. | Spec 13.1, 20 (secrets never logged). |
| 2026-10-31 | **Provider secrets encrypted with Fernet** (from `cryptography`), key = SHA-256 of `APP_ENCRYPTION_KEY` with a domain prefix, ciphertext versioned `v1:`. The UI only ever sees `…last4`. Without `APP_ENCRYPTION_KEY`, storing a key is refused (`503 encryption_unavailable`). Env `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` act as fallback for providers saved without a key. | Spec 7.1, 20. |
| 2026-10-31 | `base_url` (optional, for the provider's own alternative endpoints) must be `https://`. | No plaintext key transport. |
| 2026-10-31 | **Models come from the provider's model list** ("Import models") or are typed in; all imported models start enabled, the first becomes default. Prices are **owner-entered** per model (USD per million tokens) → `cost_usd` per message when both prices and usage are known. | Spec 13.1: never hardcode model names or prices. |
| 2026-10-31 | **Mock provider** (`ENABLE_MOCK_PROVIDER=true`, off by default) for tests, CI and demos. Directives in the message (`[[mock:slow]]`, `[[mock:error:<kind>]]`) steer it. | Spec 23: tests must not spend money or need network. |
| 2026-10-31 | Context = the last `CHAT_CONTEXT_MAX_MESSAGES` completed messages; failed/cancelled answers are excluded. Title = first message, trimmed (no extra LLM call). | Predictable cost. |
| 2026-10-31 | Markdown via react-markdown + remark-gfm + rehype-highlight; **raw HTML in model output is not rendered**; links open with `rel="noopener noreferrer nofollow"`. Code colours are our own CSS (no highlight.js theme dependency). | Model output is untrusted (invariant 13). |
| 2026-10-31 | **Chat file attachments deferred to Sprint 7**, together with file storage and workspaces. | Sprint 2's task list doesn't include them and they need the file storage/permission design first. |
| 2026-10-31 | `openapi-typescript --default-non-nullable=false`. | Otherwise request fields that have server defaults become mandatory in TS. |
| 2026-10-31 | Caddy compresses only listed document types; `text/event-stream` is never compressed. | Verified: tokens arrive every 250 ms through Caddy, not in one buffered burst. |

## Sprint 3 — Agent engine

External repositories checked (REFERENCE only, read as untrusted data): **slopus/happy** (MIT) and **Sunwood-ai-labs/codex-remote-control-lab** (ISC). Ideas applied: the server owns the session and every device is a thin replica that catches up from a snapshot or event stream; secrets never leave the host. Not applied: Happy's "reuse your subscriptions" (forbidden by spec 13.5) and the lab's token-in-URL access (leaks via history/logs — we use the session cookie + CSRF).

| Date | Decision | Reason |
|---|---|---|
| 2026-10-31 | **ARQ** worker (`arq app.workers.main.WorkerSettings`), same image as the backend. ARQ 0.28 requires **redis-py < 6**, so redis-py is pinned to 5.3.x (works with the Redis 8 server). | Spec 4.2 stack. |
| 2026-10-31 | **The job only carries a task id; PostgreSQL is the queue's source of truth.** A job atomically claims `queued → running` under a row lock, so duplicate jobs are harmless; a cron sweeper re-enqueues `queued` tasks older than `WORKER_REQUEUE_AFTER_SECONDS`. ARQ `max_tries=1` — retries/recovery are ours, not ARQ's. | Invariant 2; a lost enqueue (Redis down) delays a task but never loses it. |
| 2026-10-31 | **Event ordering**: writers take `pg_advisory_xact_lock` before inserting into `agent_events`, so events commit in `seq` order and "resume after seq N" can never skip one. Events are published to Redis only **after** commit; events of rolled-back transactions are dropped. `agent_events` is append-only (DB trigger). | Spec 10, invariant 4/9. Proven by a concurrency test. |
| 2026-10-31 | Event payloads for `agent.*` / `task.*` carry the **full entity** (`agent` / `task`) besides `old_status`/`new_status`. | The client reducer stays trivial and can't drift from the server. |
| 2026-10-31 | `chat.message_delta` is stream-only (published, not stored); `chat.message_completed` is stored in the same transaction as the final message. | Spec 10.3. |
| 2026-10-31 | **WebSocket protocol details** (spec 11 left open): the `hello` must carry the CSRF token (blocks cross-site WebSocket hijacking without relying on Host/Origin headers that proxies may rewrite); event frames are `{"type":"event","event":{envelope}}` (the spec's `{"type":"event", ...envelope}` collides on `type`); after a replay the server always sends `{"type":"resumed","seq":N}` — found by E2E: without it a client that missed nothing could not tell "caught up" from "stuck". Snapshot when `last_seq` is missing/invalid or more than `REALTIME_MAX_REPLAY` behind. | Correctness under reconnects; contracts in `packages/agent-contracts`. |
| 2026-10-31 | **Redis is only an accelerator for realtime**: the WS gateway also reads new events from PostgreSQL every 2 s and fills `seq` gaps from the DB. | Spec 22 (Redis down): events are delayed, never lost — tested with Redis unreachable. |
| 2026-10-31 | The WS gateway re-checks the session every 60 s and closes with 4401 after logout/expiry. The client also has a 10 s first-frame watchdog (a handshake started while the server was shutting down can otherwise hang forever — found by E2E). | Security + resilience. |
| 2026-10-31 | **State-machine additions** where the spec is silent: agent `<active> → idle` = stop; persistent agents `completed → idle` immediately after a task and `failed` stays until the next run (so the office can show the error); task `running → queued` (recovery / worker shutdown) and `waiting → queued` (resume). Pausing an agent moves its task to `waiting` (reason `paused`). | Spec 8.5 + 9.1. All transitions go through `app/agents/engine.py` and are rejected with `409 invalid_transition` otherwise. |
| 2026-10-31 | **Cooperative cancel/pause**: the runtime re-reads task/agent status between steps and every `WORKER_CONTROL_POLL_SECONDS` while a model call is in flight, abandoning the call. On SIGTERM a running task goes back to `queued` and resumes from its checkpoint. | DB stays the source of truth; no Redis-only flags. |
| 2026-10-31 | **Checkpoint after every model step** (`agent_runs.state.messages`, steps, usage, elapsed time). Recovery treats a run with `state.in_flight.side_effects` as **unknown outcome → `waiting`**; everything else is resumed. | Spec 9.1: never auto-repeat an operation with unknown outcome (the in-flight marker is written by tools in Sprint 7). |
| 2026-10-31 | Limits enforced in code: steps (`MAX_STEPS_PER_RUN`), wall-clock (`RUN_TIMEOUT_SECONDS`, measured across resumes). Per-agent limits can only be stricter. | Spec 7.2, 14.5. |
| 2026-10-31 | **Runtime adapters**: one **native runtime** (our loop over the Model Gateway, provider-neutral) behind the `AgentRuntime` contract. The official Claude Agent SDK / OpenAI Agents SDK are not adopted: both keep their own run state and tool permission model, which conflicts with invariants 1, 2 and 5; they can be added later as adapters. | Spec 13.3, external-repositories note ("not yet verified"). |
| 2026-10-31 | One task at a time per agent (`409 agent_busy`); `DELETE /agents/{id}` **archives** (history kept) and refuses while the agent is busy. | Simple, predictable office view. |
| 2026-10-31 | `Idempotency-Key` supported on `POST /tasks`, `POST /agents/{id}/run`, `POST /tasks/{id}/retry` (stored response; different body → 422; concurrent duplicate → 409). | Spec 12. |
| 2026-10-31 | Kill switch: `POST /system/stop-all` cancels every active task tree and blocks new runs until `POST /system/start`. | Spec 7.2. |
| 2026-10-31 | The worker container waits for the backend's migrations (`app.cli wait-for-migrations`) instead of running them. Health: `arq --check`. | No concurrent migrations. |
| 2026-10-31 | Subtasks use `tasks.parent_task_id` (spec 26.3). | One table, simple queries. |

## Sprint 4 — Orchestrator & subagents

External repository checked: **FoundationAgents/AOrchestra** (REFERENCE, Apache-2.0). Idea applied (re-implemented, nothing copied): each subagent is concretised by the orchestrator as ⟨Instructions, Context, Tools, Model⟩ — instructions = the plan's `instructions`; context = the root task plus results of `depends_on` passed as agent messages; tools = the plan's tools **∩** the orchestrator's own tools; model = the orchestrator's model. No heavy agent framework adopted (our state machines/event log stay the source of truth).

| Date | Decision | Reason |
|---|---|---|
| 2026-10-31 | **Plan = one JSON object** (`mode: direct\|delegate`, `subtasks[{key,title,specialization,instructions,depends_on,tools,delegate}]`, `review`), validated in code: unique slugs, known dependencies, no cycles, ≤ `MAX_SUBTASKS_PER_PLAN` (8). An invalid plan is retried with the error as feedback up to `MAX_RETRIES_PER_STEP`, then the run fails `invalid_plan`. | Spec 14.3; never trust model output structurally. |
| 2026-10-31 | **Simple requests get a direct answer** (`mode: direct`) — the planning prompt tells the model subagents cost time and money. | Spec 14.3 step 2. |
| 2026-10-31 | A plan can **never choose a model name**; subagents use the orchestrator's model. | Spec 13.1 (no hardcoded/hallucinated model names). Per-specialisation defaults can come in Sprint 6. |
| 2026-10-31 | **Limits in code**: `MAX_ACTIVE_SUBAGENTS_PER_RUN` (5) is counted over the whole run tree and enforced by a scheduler that serialises on the root run's row lock; the limit is snapshotted into the root run at delegation. `MAX_SUBAGENT_DEPTH` (2) is enforced when a subagent is created (`DepthLimitExceeded`) and by refusing `delegate` in plans at the last level (recorded as a plan warning). Tests replay the ordered event log to prove the peak of active subagents equals the limit under parallel completions. | Spec 7.2, 14.5, Sprint 4 "Done when". |
| 2026-10-31 | "Active" = subtask `queued` or `running`. An orchestrating subagent waiting for its own children does **not** hold a slot. | Otherwise five waiting orchestrators could deadlock the tree. |
| 2026-10-31 | The orchestrator's task goes to `waiting` (`waiting_for_subtasks`) while subagents work; the scheduler re-queues it when all its subtasks are finished (aggregation phase). The worker slot is free while waiting, and waiting time doesn't count towards the orchestrator's run timeout. | No worker blocked on children; restart-safe. |
| 2026-10-31 | Dependants of a failed/cancelled subtask are cancelled (`dependency_failed`). The synthesis reports failed parts as `error` inputs; if **no** subtask succeeded the run fails `subtasks_failed`. | Spec invariant 10: never present a partial failure as success. |
| 2026-10-31 | **Reviewer step**: when the plan sets `review`, a Reviewer subagent checks the completed results before synthesis. | Spec 14.3 step 9. |
| 2026-10-31 | **Agent↔agent messages** (`agent_messages`): delivered only when both agents belong to the same run tree (`agents.run_id` = root run); otherwise stored as `refused` (without the content) and audited. Inputs are injected into prompts fenced as `<input …>` data. | Spec 14.4, invariant 13. |
| 2026-10-31 | Subagents are **archived** when their root run ends (completed, failed or cancelled); their tasks, messages and events stay. | They leave the office, history stays. |
| 2026-10-31 | **Chat hand-off**: `POST /chats/{id}/handoff` saves the question in the chat with `agent_run_id`, starts an Orchestrator run, and the run posts its result (or failure) back into the conversation as an assistant message. The chat suggests hand-off for long / list-like requests and has an explicit "Agents" mode. | Spec 2.1, 14.3 (chat integration). |
| 2026-10-31 | One **Orchestrator** agent per user is created on first use (`ensure_orchestrator`). | Zero setup for the owner; configurable in Sprint 6. |
| 2026-10-31 | **Realtime fix**: the "too far behind → snapshot" rule now counts the user's *missed events*; subtracting `seq` values was wrong (global sequence with gaps) and was caught by the full test suite. | Correct resume. |
| 2026-10-31 | ORM timestamps are set on the Python side (DB defaults stay). | A DB-side `onupdate` expires the attribute after a flush and reading it would need lazy I/O, which async SQLAlchemy forbids. |

## Sprint 5 — Pixel Office

External repositories checked (only at this sprint, as instructed):
- **phaserjs/template-nextjs** (USE, MIT). Adopted its architecture *inside* `apps/web` (not as a separate app): a client-only component dynamically imports the game, and React and Phaser talk only through an event bus. Our bus is typed (`features/office/engine/bus.ts`) and one-directional for agent data: store → bus → scene. Notice in `THIRD_PARTY_NOTICES.md`.
- **pablodelucca/pixel-agents** (REFERENCE, MIT) and **neomatrix25/pixel-office-openclaw** (REFERENCE, MIT): ideas only, re-implemented, nothing copied — a single status → animation table, stable desk assignment, A* movement on a tile grid, secrets stay on the server (the office only reads the store).
- **fumeilab/pixelfloor** (REFERENCE): only the idea of pushing state over the WebSocket — we already have it (spec 11). Not used.
- Canvas 2D (used by the references) was **not** adopted; Phaser stays as the spec requires.

| Date | Decision | Reason |
|---|---|---|
| 2026-10-31 | **Phaser 3.90.0**, not the template's version. ⚠ Conflict for the owner: `template-nextjs` `main` now ships **Phaser 4.0.0**; the spec (4.1, 18.6) and `docs/external-repositories.md` say Phaser 3. We follow the spec and use the latest Phaser 3 with the template's pattern. Moving to Phaser 4 later is a contained change (only `features/office/engine/`). | Spec wins over a template's moving `main`. |
| 2026-10-31 | **All art is original and drawn in code** (16×16 characters with 17 frames, 8×8 status icons, furniture with Phaser Graphics). No external asset pack. Listed in `apps/web/assets/MANIFEST.md`. | Spec 18.2 (unified style, every asset's license known); no REFERENCE assets copied. |
| 2026-10-31 | World **640×360**, 16 px tiles (40×22), `pixelArt`, `roundPixels`, **integer camera zoom only** (1–6). Default = the largest integer zoom that shows the whole office, centred; narrow screens stay at zoom 1 and pan by drag; pinch / wheel / buttons change zoom by whole steps. | Spec 18.6 pixel-perfect rendering. |
| 2026-10-31 | **Status → behaviour table** (`engine/behavior.ts`) is the only place that maps agent status to place, pose, indicator and animation (spec 18.4): idle → lounge, planning → task board, working → own desk (monitor lights up), waiting → waiting area with hourglass, reviewing → review corner, paused → frozen where it stands, completed → desk + check, failed → desk + alert. Unknown statuses fall back to idle. | One table, tested; no state logic in the scene. |
| 2026-10-31 | **Desks are assigned stably** per agent (hash + first free desk, kept while the agent exists), so a reload puts everyone back at the same desk. | Office matches reality after reload. |
| 2026-10-31 | Phaser **never changes agent state**: the scene receives the agents list from the realtime store, actions (pause, resume, stop, logs, open task) go through the Agent Inspector, which is React and calls the REST API. | Spec 18.7 one-way data flow. |
| 2026-10-31 | Agents mode shows persistent agents; Subagents mode shows the live subagents plus the Orchestrator. Subagents walk in through the door when created and leave when archived (end of the run). `agent.message` events between agents animate an envelope. | Spec 18.3, 18.5. |
| 2026-10-31 | Name labels are shown on hover and for the selected character only. A plain list of agents with statuses sits under the canvas (accessible and readable on a phone). | Labels overlapped in the lounge; canvas content is invisible to screen readers. |
| 2026-10-31 | **Test hook**: the canvas carries `data-agents` (id, status, pose, screen position) refreshed every 300 ms. Browser tests read it to check that the office matches the backend and to click characters. No secrets in it — only what the page already shows. | Phaser draws to a canvas; tests need a reliable view of it. |
| 2026-10-31 | `GET /events` gained `latest=true` (the newest `limit` events, still returned oldest → newest) for the inspector's recent-events log. | Avoid paging through the whole history. |
| 2026-10-31 | Mock provider: `[[mock:sleep:N]]` makes a non-streaming answer take N seconds (max 60), so browser tests can watch a character work. Mock provider stays disabled by default. | Deterministic E2E without a real key. |

## Sprint 6 — Autonomous agents

No external repository is assigned to this sprint in `docs/external-repositories.md`; none used. No new dependencies.

| Date | Decision | Reason |
|---|---|---|
| 2026-11-01 | **Agent settings page** `/office/agents/{id}` (tabs: settings, memory, task history) and `/office/agents/new`. The Agent Inspector's "Settings" opens it. Run / pause / resume / stop / delete are on the page too. | Spec 19 Agent Office "create/manage agents"; Sprint 6 Done-when. |
| 2026-11-01 | **Delete = archive**: the agent leaves the office and all lists, its task history and memory stay; its page shows "deleted" with the history only. Refused while the agent is busy. | Spec 1.1: no silent data deletion; history is evidence. |
| 2026-11-01 | **Per-agent limits may only be stricter** than the global ones: the API now rejects higher values (`422 limit_too_high`, with `details.max`); the runtime still caps at the global value (for agents saved before the owner lowered a global limit). `GET /system/limits` lets the UI show the caps. | Spec 7.2, 14.2. |
| 2026-11-01 | `memory_settings` is a validated object (`enabled`, `include_shared`, `projects[]`, `max_context_chars`), stored compactly (defaults omitted). | Free-form JSON would let a typo silently disable memory. |
| 2026-11-01 | **Memory = plain rows** (`memories`) + **change history** (`memory_revisions`, one row per saved version). No vectors, no semantic search. | Spec 17 MVP. |
| 2026-11-01 | **Scopes**: `user` (facts about the owner) is always shared (no agent); `project` needs a project name (shared or one agent's); `agent`, `task_context`, `conversation_context` belong to one agent. Subagents have no memory of their own — the Orchestrator passes them their context. | Clear rules; spec 17 "scope to an agent or project, access control". |
| 2026-11-01 | **What reaches the prompt**: the agent's own entries, shared `user` entries (unless `include_shared` is off) and shared notes of the projects it lists; pinned first, then newest; added while they fit `max_context_chars` (≤ `MEMORY_CONTEXT_MAX_CHARS`, default 8000), the rest is reported as omitted. Each entry ≤ `MEMORY_ENTRY_MAX_CHARS` (4000). The Orchestrator gets memory when planning and when writing the final answer. `GET /agents/{id}/memory-context` returns exactly the injected text (shown in the UI). | Spec 17 "context-size limiting"; the owner can see what the model sees. |
| 2026-11-01 | **Memory is data, never instructions**: it goes at the end of the system prompt inside `<memory …>` blocks under a header that says so; text that imitates the fence (`<memory`, `</memory`) is neutralised to `&lt;memory`, titles can't break out of their attribute. | Spec 17, invariant 13 (prompt injection). |
| 2026-11-01 | **Forgetting deletes** the entry and its history (the owner asked to forget it); the audit log records create/update/delete with type and agent only — never the content. | Privacy: a "deleted" memory must not survive in a history table or the audit log. |
| 2026-11-01 | Memory is written by the owner (UI/API) in this sprint. Agents saving memory themselves comes with tools (Sprint 7, a `write` tool that goes through the permission check and approvals). | Spec 15: every agent action through the permission system. |
| 2026-11-01 | Autonomy levels are stored, explained in the UI and enforced by the permission check in Sprint 7 (there are no tools yet, so nothing to enforce). | Spec 14.2, 15.2. |
| 2026-11-01 | ⚠ **Deferred**: the Orchestrator giving subtasks to existing autonomous agents (spec 14.1 "receive tasks from the Orchestrator"). It needs busy-agent queuing across run trees and cross-run context passing (agent messages are same-run only by design). Today the Orchestrator creates subagents. Proposed for after Sprint 7. | Not in the Sprint 6 task list; risky to rush. Flagged for the owner. |
| 2026-11-01 | Test isolation fix: `tests/conftest.py` imports the scripted orchestrator replies up front; a test that patched the mock handler list could otherwise swallow their registration for every later test. | Found while adding memory tests. |

## Sprint 7 — Tools & integrations

External repositories checked (only at this sprint, as instructed):
- **modelcontextprotocol/python-sdk** — the official MCP SDK, PyPI `mcp` 2.3.0 (MIT, released 2026-10-02, uses `httpx2`, which we already had). USED as a dependency for the MCP Manager (Streamable HTTP client).
- **modelcontextprotocol/servers** (USE selectively): its reference servers (Filesystem, Git, Fetch, Memory, Time) speak stdio. moloko connects MCP servers over **Streamable HTTP**; running a reference server for moloko means putting it behind an HTTP transport in its own container. None is bundled; archived servers are not used.
- **github/github-mcp-server** (official GitHub MCP server): MIT, not archived, latest release v2.0.3 (Oct 21); offers a hosted HTTP endpoint and the image `ghcr.io/github/github-mcp-server`; auth by OAuth or PAT. ⚠ **Not added — needs the owner's confirmation** (docs/external-repositories.md). The GitHub integration uses our own small REST client instead; once confirmed, the server can be connected through the MCP Manager without code changes.
- **e2b-dev** (REFERENCE / upgrade path): not integrated. Our `Sandbox` interface (`app/sandbox/base.py`) is where an E2B backend would go. E2B self-hosting needs KVM: check the home server with `ls -l /dev/kvm` (or `kvm-ok`) before proposing it — not checked yet (no access to the server).
- **matuscvengros/agent-sandbox**: AVOID — not used.

| Date | Decision | Reason |
|---|---|---|
| 2026-11-01 | **Tool Registry**: built-in tools are defined in code (`app/tools/builtin/`), MCP tools live in the `tools` table; a `tools` row also stores the owner's on/off switch for a built-in tool. Each tool declares name, description, JSON input schema, category, scope check, timeout and how to describe an operation for approval. | Spec 15.1. |
| 2026-11-01 | **`authorize()` runs before every call** (`app/tools/policy.py`): enabled + available + in `allowed_tools` → schema + scope (paths, repositories, URLs) → category (may depend on the arguments) × autonomy → audit. Matrix: supervised = read allow / write approve / sensitive approve; balanced = read, write allow / sensitive approve; restricted = read allow / write approve / **sensitive deny**. Per-tool overrides are `approve` or `deny` only (stricter). The model is only offered allowed, enabled, available tools — and calls are authorized again anyway. | Spec 14.2, 15.2. |
| 2026-11-01 | **Approvals** bind to ONE operation: tool name + SHA-256 of the canonical JSON of the exact arguments, with `APPROVAL_TTL_MINUTES` expiry. The task goes `waiting_approval` (agent `waiting`), the worker slot is freed, `approval.required` is emitted. Approve → a fresh TTL window to execute, task re-queued; on resume the runner re-checks status, hash, `used_at`, expiry **and re-runs `authorize()`**. Reject → the agent is told and continues; Cancel task → the whole run tree is cancelled; unanswered → `expired` by the worker sweeper (the agent is told). | Spec 15.4; one approval never carries over. |
| 2026-11-01 | **`tool_calls` is the source of truth** for each call (unique per run + model call id). A finished call is never executed again on resume; a call that was running when the worker died is reported to the model as *outcome unknown* (and the task first waits for the owner, as in Sprint 3). | Spec 9.1, 16 ("record commands, files, errors, results"). |
| 2026-11-01 | Tool calls of one model step run **sequentially** (so `MAX_PARALLEL_TOOL_CALLS` is never exceeded). | Simple and safe; parallel read-only calls can come later. |
| 2026-11-01 | Every tool result is fenced as `<tool_output … trust="untrusted">` (fence-like text neutralised) and capped at `TOOL_OUTPUT_MAX_CHARS`. | Spec 20 prompt-injection defence. |
| 2026-11-01 | **Workspaces**: one per root task (shared by its subagents) or a named **project** workspace an agent can be bound to. Paths are relative, no `..`, no absolute paths, and **no symlinks anywhere on the path** (checked with `lstat`). Changes are recorded in `workspace_files` and the audit log. Task workspaces are deleted `WORKSPACE_TASK_TTL_DAYS` (14) after the task ends; project workspaces stay. | Spec 16. |
| 2026-11-01 | **Sandbox = a separate runner service**, the only one with the Docker socket; it has no database/app secrets and accepts one token-protected request type. Each command gets a fresh container: fixed image, `NetworkMode: none`, uid 10001, read-only root, `cap_drop: ALL`, `no-new-privileges`, tmpfs `/tmp`, CPU/RAM/pids limits, wall-clock timeout, only that workspace mounted (named-volume subpath; Docker Engine ≥ 26). Verified against a real daemon by `tests/test_sandbox_runner.py`. | Spec 16; the backend and worker never get the socket. |
| 2026-11-01 | Terminal commands run **without a shell** (`shlex` split, exec form) and the program must be in `SANDBOX_ALLOWED_COMMANDS`. This is intent control; the isolation is the container. No network in the MVP (no `pip install` from the internet). | Spec 16 "command allow/deny control", "controlled network". |
| 2026-11-01 | **Browser** = `web_fetch` (HTTP + readable text), not a headless browser. SSRF guard: http(s) only, ports 80/443, no credentials in URLs, every resolved address must be public, the connection goes to the checked address (no DNS re-binding, TLS name still verified), redirects re-checked per hop, size/time limits. `web_search` only with a self-hosted SearXNG (`SEARXNG_URL`) — no paid search API without the owner. | Spec 15.6; spec 1.1 (no paid services). |
| 2026-11-01 | **GitHub** via REST with a fine-grained PAT stored encrypted (Fernet), API host pinned, optional repository allow-list. Reading = `read`; branch / commit to a non-default branch = `write`; commit to the default branch and pull requests = `sensitive`. | Spec 15.6. |
| 2026-11-01 | **MCP Manager**: Streamable HTTP servers with an optional encrypted bearer token. New tools start **disabled** and classified `sensitive` until the owner enables/classifies them; a changed tool schema or a new URL/token turns its tools off again. Each call opens a short session with a timeout, so a server that is down fails only that call. | Spec 15.5. |
| 2026-11-01 | `memory_save` (agents write their own memory) is a `write` tool, so a supervised agent asks first. | Sprint 6 note. |
| 2026-11-01 | Audit log UI at Settings → Audit log (filters by area and outcome, cursor paging); anonymous entries (failed logins) are shown to the owner too. | Spec 20. |
| 2026-11-01 | Mock provider `[[mock:tools]][…][[/mock:tools]]` drives tool calls offline (browser tests); still disabled by default. | E2E without a real key. |
| 2026-11-01 | Server-generated operation texts (approval summary, consequences, reason) are English for now; the UI around them is localized. Localizing them is planned for Sprint 8. | Scope. |
| 2026-11-01 | Chat attachments (deferred from Sprint 2) are moved to Sprint 8. | Sprint 7 scope; they need upload limits and text extraction. |
| 2026-11-01 | Pixel Office: the lounge has 23 spots (3 rows on the rug) and the waiting bench 13, so idle characters no longer stack on one tile and stay clickable. | Found by the office browser test once there were more than 7 idle agents. |

## Dependency register

External repositories from `docs/external-repositories.md`: **none used in Sprint 1** (as instructed).
Versions are exact pins (npm `package.json` + `package-lock.json`; Python `uv.lock`).

| Name | Version | License | Purpose | Sprint | Date |
|---|---|---|---|---|---|
| **Backend (PyPI)** | | | | | |
| fastapi | 0.162.0 | MIT | HTTP API framework | 1 | 2026-10-31 |
| starlette (via FastAPI) | 1.10.0 | BSD-3-Clause | ASGI toolkit | 1 | 2026-10-31 |
| uvicorn[standard] | 0.54.0 | BSD-3-Clause | ASGI server | 1 | 2026-10-31 |
| pydantic | 2.14.2 | MIT | Validation | 1 | 2026-10-31 |
| pydantic-settings | 2.16.2 | MIT | Env configuration | 1 | 2026-10-31 |
| sqlalchemy[asyncio] | 2.1.6 | MIT | ORM / DB access | 1 | 2026-10-31 |
| asyncpg | 0.32.0 | Apache-2.0 | PostgreSQL driver | 1 | 2026-10-31 |
| alembic | 1.20.1 | MIT | Migrations | 1 | 2026-10-31 |
| redis (redis-py) | 5.3.1 (pinned <6 for ARQ) | MIT | Redis client | 1→3 | 2026-10-31 |
| argon2-cffi | 25.1.0 | MIT | argon2id password hashing | 1 | 2026-10-31 |
| pytest / pytest-asyncio | 9.2.0 / 1.4.1 | MIT / Apache-2.0 | Tests (dev) | 1 | 2026-10-31 |
| httpx | 0.28.1 | BSD-3-Clause | Test client (dev) | 1 | 2026-10-31 |
| ruff | 0.17.3 | MIT | Lint + format (dev) | 1 | 2026-10-31 |
| mypy | 2.4.1 | MIT | Type checking (dev) | 1 | 2026-10-31 |
| uv | 0.11.32 | MIT OR Apache-2.0 | Python package manager (build tool) | 1 | 2026-10-31 |
| openai | 3.42.0 | Apache-2.0 | Official OpenAI SDK (provider adapter) | 2 | 2026-10-31 |
| anthropic | 2.3.0 | Apache-2.0 (per PyPI metadata) | Official Anthropic SDK (provider adapter) | 2 | 2026-10-31 |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause | Fernet encryption of stored secrets | 2 | 2026-10-31 |
| httpx2 (via the SDKs) | 2.16.0 | BSD-3-Clause | HTTP client used by both SDKs | 2 | 2026-10-31 |
| **Frontend (npm)** | | | | | |
| next | 16.4.3 | MIT | App framework | 1 | 2026-10-31 |
| react / react-dom | 19.3.1 | MIT | UI | 1 | 2026-10-31 |
| @tanstack/react-query | 5.105.0 | MIT | REST data fetching | 1 | 2026-10-31 |
| next-intl | 4.14.9 | MIT | i18n | 1 | 2026-10-31 |
| next-themes | 0.4.6 | MIT | Dark/light theme | 1 | 2026-10-31 |
| tailwindcss / @tailwindcss/postcss | 4.3.3 | MIT | Styling | 1 | 2026-10-31 |
| class-variance-authority | 0.7.1 | Apache-2.0 | Component variants (shadcn/ui) | 1 | 2026-10-31 |
| clsx | 2.1.1 | MIT | Class names | 1 | 2026-10-31 |
| tailwind-merge | 3.7.0 | MIT | Class merging | 1 | 2026-10-31 |
| @radix-ui/react-slot | 1.5.0 | MIT | `asChild` for Button | 1 | 2026-10-31 |
| lucide-react | 1.66.0 | ISC | Icons | 1 | 2026-10-31 |
| typescript | 5.9.3 | Apache-2.0 | Types (dev) | 1 | 2026-10-31 |
| eslint / eslint-config-next | 9.39.5 / 16.4.3 | MIT | Lint (dev) | 1 | 2026-10-31 |
| vitest | 5.0.5 | MIT | Unit tests (dev) | 1 | 2026-10-31 |
| openapi-typescript | 7.13.0 | MIT | TS types from OpenAPI (dev) | 1 | 2026-10-31 |
| shadcn/ui (copied component patterns) | — | MIT | Button/Input/Card source patterns | 1 | 2026-10-31 |
| arq | 0.28.0 | MIT | Background job worker | 3 | 2026-10-31 |
| jsonschema (dev) | 4.26.0 | MIT | Contract tests for event schemas | 3 | 2026-10-31 |
| **Frontend (npm) — Sprint 2** | | | | | |
| @assistant-ui/react | 0.15.32 | MIT | Chat UI primitives on our own runtime | 2 | 2026-10-31 |
| react-markdown | 10.1.0 | MIT | Markdown rendering of answers | 2 | 2026-10-31 |
| remark-gfm | 4.0.1 | MIT | Tables, lists, strikethrough | 2 | 2026-10-31 |
| rehype-highlight | 7.0.2 | MIT | Code highlighting (highlight.js, BSD-3-Clause) | 2 | 2026-10-31 |
| zustand | 5.0.16 | MIT | Realtime client store | 3 | 2026-10-31 |
| **Frontend (npm) — Sprint 5** | | | | | |
| phaser | 3.90.0 | MIT | Pixel Office engine (spec 18.6) | 5 | 2026-10-31 |
| phaserjs/template-nextjs (pattern only) | main @ 2026-10-31 | MIT | React ⇄ Phaser bus architecture | 5 | 2026-10-31 |
| **Backend (PyPI) — Sprint 7** | | | | | |
| mcp | 2.3.0 | MIT | Official MCP SDK (MCP Manager client) | 7 | 2026-11-01 |
| mcp-types (via mcp) | 2.3.0 | MIT | MCP protocol types | 7 | 2026-11-01 |
| httpx2 | 2.16.0 (now a direct dependency) | BSD-3-Clause | GitHub, web fetch, sandbox runner, Docker API clients | 7 | 2026-11-01 |
| jsonschema | 4.26.0 (moved from dev to runtime) | MIT | Validating tool arguments | 7 | 2026-11-01 |
| sse-starlette / python-multipart / pyjwt / opentelemetry-api (via mcp) | 3.6.0 / 0.0.33 / 2.15.1 / 1.45.2 | BSD-3-Clause / Apache-2.0 / MIT / Apache-2.0 | MCP SDK dependencies | 7 | 2026-11-01 |
| **Optional, not bundled** | | | | | |
| SearXNG (separate service, if the owner runs it) | — | AGPL-3.0 (service, not linked) | web_search back-end | 7 | 2026-11-01 |
| **Container images** | | | | | |
| postgres | 17.11-alpine | PostgreSQL License | Database | 1 | 2026-10-31 |
| redis | 8.10.3-alpine | RSALv2 / SSPLv1 / AGPLv3 (we rely on AGPLv3) | Cache/queue/pub-sub | 1 | 2026-10-31 |
| caddy | 2.11.7-alpine | Apache-2.0 | Reverse proxy | 1 | 2026-10-31 |
| python | 3.12.16-slim | PSF-2.0 | Backend runtime | 1 | 2026-10-31 |
| node | 22.23.4-alpine | MIT | Frontend runtime | 1 | 2026-10-31 |
