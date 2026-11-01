# Architecture

Status: **Sprint 4** (orchestrator & subagents) done. See `shvluup-spec.md` §5 for the target
architecture; this file describes what exists now and the conventions to follow.

## Runtime topology

```
Phone / laptops ──(tailnet, HTTPS)──► Tailscale Serve on the server
                                          │ http://127.0.0.1:8080
                                          ▼
                                   caddy (Docker, :80)
                         /api/*, /ws/* │            │ everything else
                                       ▼            ▼
                                 backend:8000   frontend:3000
                                 (FastAPI)      (Next.js standalone)
                                   │     │
                     internal net  ▼     ▼
                             postgres   redis
```

- Only Caddy publishes a port, bound to loopback. TLS is Tailscale's.
- `internal` Docker network (`internal: true`): PostgreSQL, Redis, backend. No route to the outside.
- `edge` network: Caddy, frontend, backend (backend needs egress for AI providers from Sprint 2).
- One origin: the browser never talks cross-origin, so cookies are first-party and CORS stays off.
- The ARQ **worker** (same image, `arq app.workers.main.WorkerSettings`) executes agent runs; it is on `internal` + `edge`.

## Backend (`apps/api`)

Layering (spec §5.1): **router → service → repository → model**.

| Path | Role |
|---|---|
| `app/main.py` | `create_app(settings)` factory: lifespan (DB engine, Redis), routers, middleware, error handlers. Run with `uvicorn app.main:create_app --factory`. |
| `app/core/config.py` | All settings (Pydantic Settings, env vars). |
| `app/core/db.py` | Async SQLAlchemy engine/sessionmaker; lazy connections, `pool_pre_ping`. |
| `app/core/security.py` | argon2id, session tokens, CSRF tokens. |
| `app/core/middleware.py` | Pure-ASGI middlewares (safe for SSE/WebSockets): request id + `Cache-Control: no-store`; global CSRF check. |
| `app/core/errors.py` | Error envelope, exception handlers, dependency-outage classification. |
| `app/core/openapi.py` | Makes the published schema match the real error envelope. |
| `app/api/v1/` | Routers only (no business logic). `router.py` splits `public` vs `protected`. |
| `app/services/` | Business logic (`auth`, `users`, `audit`, `health`). Services commit transactions. |
| `app/repositories/` | DB queries per table. |
| `app/models/` | ORM models; every model must be imported in `app/models/__init__.py`. |
| `app/cli.py` | Admin CLI: `create-owner`, `reset-password`, `wait-for-db`. |
| `migrations/` | Alembic (async). Initial revision `0001`. |

Module rule: other modules call a module's **service**, never its repositories/tables.

Request pipeline (outermost first): `RequestContextMiddleware` → (CORS, only if configured)
→ `CSRFMiddleware` → router dependencies (`require_auth` for protected routes) → handler.

## Frontend (`apps/web`)

| Path | Role |
|---|---|
| `app/` | Routes. `(app)/` = authenticated area (wrapped by `AppShell`); `login/`; `healthz/` (container health). |
| `components/ui/` | shadcn/ui-style primitives. |
| `components/layout/` | `AppShell` (sidebar on ≥md, top bar + bottom tabs on phones), nav, page header. |
| `components/brand/logo.tsx` | The only place the brand mark is drawn (placeholder until the owner's PNG lands). |
| `features/` | Feature components and hooks (auth, preferences, system). |
| `lib/api/` | The only place that calls `fetch`. `client.ts` adds CSRF, retries once on `csrf_failed`, turns failures into `ApiError`. |
| `i18n/`, `messages/` | next-intl, no locale in URLs. `ru` (default) and `en`, identical keys (tested). |

State: server data via TanStack Query (`authKeys.me`, `systemKeys.health`). A global
`QueryCache`/`MutationCache` handler sends any `401` to `/login?next=…`. Zustand arrives
with the realtime store in Sprint 3. Auth is decided by the backend (`GET /auth/me`);
the UI only reflects it — there is no server-side redirect in Next.js (see decisions).

## Shared contracts

`packages/shared-types`: `openapi.json` (exported from FastAPI) → `src/api.gen.ts`
(openapi-typescript). Both committed; CI fails if either is stale.

## Model Gateway & chat (Sprint 2)

```
ChatService.send ──► ModelGateway.resolve (model → provider, decrypt key)
       │                     │
       │                     ▼
       │          provider adapter (openai_provider / anthropic_provider / mock_provider)
       ▼                     │  official SDK, base URL pinned, SDK retries off
ChatStreamManager ◄──────────┘  stream() → ChatChunk(text…) … ChatChunk(result)
  background task per answer: fan-out to SSE subscribers, persist final message
```

- `app/providers/` is the only place that imports a provider SDK (invariant 7). The shared types (`ChatRequest`, `ChatMessage`, `ToolCall`, `ToolSpec`, `ChatResult`) already carry tool calls for the agent runtime.
- Frontend: `features/chat/` — `useChatThread` mirrors server state (TanStack Query cache + SSE), `ChatThread` renders it with assistant-ui primitives via `useExternalStoreRuntime`; `lib/api/sse.ts` parses the stream.

## Agent engine (Sprint 3)

```
POST /agents/{id}/run ─► TaskService.start: task created→queued, run row, agent reserved ─► COMMIT ─► ARQ enqueue(task_id)
                                                                                                │
worker: Executor.execute(task_id) ─ claim (row lock, queued→running) ─► runtime.start(ctx) ◄────┘
        NativeRuntime: [control.check → model step (guarded) → checkpoint + agent.message] × n → reviewing → completed
```

- `app/agents/state.py` — state machines; `app/agents/engine.py` — the only code that changes statuses (each change = event in the same transaction).
- `app/events/bus.py` — ordered event log + publish-after-commit; `app/events/ws.py` — WS gateway; `app/events/snapshot.py`.
- `app/agents/control.py` — cooperative cancel/pause; `app/runtimes/` — runtime contract + native runtime; `app/workers/` — ARQ settings, jobs, restart recovery, sweeper.
- Frontend: `lib/realtime/` — `RealtimeClient` (resume, heartbeat, backoff, watchdog), Zustand store (mirror of server state), provider (events → TanStack Query invalidation). Pages: Tasks (list/detail with live history), Agent Office (cards with live status; Pixel Office in Sprint 5), Settings → kill switch.

## Orchestrator (Sprint 4)

`app/orchestrator/`: `plan.py` (schema + validation), `prompts.py`, `subagents.py` (creation with limits), `scheduler.py` (start ready subtasks within the active limit, pass results along dependencies, wake orchestrators), `messaging.py` (agent↔agent), `runtime.py` (`OrchestratorRuntime`, `SubagentRuntime`), `service.py` (start runs, chat hand-off, run trees), `mock_script.py` (scripted offline replies for tests). The executor's `after_task` hook runs a scheduling pass after every job.
Frontend: `features/runs/subagent-office.tsx` (runs, live subagents, messages, result); chat "Agents" mode and hand-off suggestion.

## Pixel Office (Sprint 5)

```
realtime store (Zustand) ─► OfficeView (React) ─► OfficeBus ─► OfficeScene (Phaser 3)
        ▲                        │ Agent Inspector (React) ─► REST (pause/resume/stop/logs)
        └── WebSocket events ────┘
```

`apps/web/features/office/engine/`: `map.ts` (640×360 floor plan, 16 px tiles, desks and zones), `pathfinding.ts` (A*), `behavior.ts` (status → place/pose/indicator, spec 18.4), `assign.ts` (stable desk/spot assignment), `sprites.ts` (original pixel art drawn in code), `bus.ts` (typed React ⇄ Phaser bus), `OfficeScene.ts` (rendering, movement, camera), `createGame.ts`. `office-view.tsx` loads Phaser only in the browser (dynamic import), filters agents by mode and feeds the bus; `agent-inspector.tsx` shows details and actions. The scene only renders: it never changes agent state.

## Autonomous agents & memory (Sprint 6)

`app/memory/context.py` builds the memory block for one agent (scope, order, size budget, data fence); `app/services/memories.py` is CRUD + history + scope rules; `NativeRuntime.setup` adds the block to the system prompt (`RunSetup.memory`), and the Orchestrator adds it to its planning and synthesis prompts. Subagents get none.
Frontend: `features/agents/agent-form.tsx` (+ `agent-form-model.ts`, pure and unit-tested), `features/agents/agent-detail.tsx` (`/office/agents/[id]`), `features/memory/memory-panel.tsx` (agent memory with a "what the model sees" preview; shared memory in Settings).

## Tools, approvals, sandbox (Sprint 7)

```
model → tool call → ToolRunner ─ authorize() ─┬─ DENY ──────────────► result "denied"
                    (tool_calls row)          ├─ REQUIRE_APPROVAL ─► approvals row, task waiting_approval,
                                              │                      approval.required → owner decides → re-queue
                                              └─ ALLOW ─► tool.run() ─► fenced result → model
terminal_run ─► RunnerSandbox (worker) ─HTTP+token─► sandbox runner ─docker.sock─► fresh locked-down container
```

`app/tools/`: `base.py` (tool contract, categories, `args_hash`), `policy.py` (`authorize`), `registry.py` (catalog), `runner.py` (`ToolRunner`: records, approvals, execution, fencing), `mcp.py`, `builtin/` (files, terminal, web, github, memory). `app/sandbox/`: `base.py` (`Sandbox` interface), `client.py` (worker side), `runner.py` + `docker_api.py` (runner service). `app/workspaces/paths.py` (safe paths), `app/services/{approvals,tools,integrations,mcp,workspaces}.py`.
Frontend: `features/approvals/` (card, badge, page), `features/integrations/` (tools, sandbox, GitHub, MCP, workspaces), `features/tasks/tool-calls.tsx` (actions + workspace files on the task page), `features/agents/agent-tools-field.tsx`, `features/settings/audit-log.tsx`. The realtime store keeps approvals from the snapshot and `approval.*` events.

## Stabilization (Sprint 8)

- `apps/web/proxy.ts` — CSP nonce per request; `app/manifest.ts`, `public/sw.js`, `public/offline.html`, `public/icons/` — PWA; `features/notifications/` + `lib/notifications/rules.ts` — which events notify.
- `backup` service: `infrastructure/backup/{loop,backup,restore-check}.sh`; `app/services/storage.py` reads its status (`/system/storage`) for Settings → Backups.
- `e2e/` — Playwright suite; `infrastructure/scripts/e2e.sh` — throwaway stack (`-p moloko-e2e`, own port and volumes) + owner + tests.

