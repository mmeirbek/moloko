# shvluup — Technical Specification (for coding agents)

> **Name change (owner decision, 2026-10-31): the product is now called `moloko`** (always lowercase).
> Wherever this spec says "shvluup", read "moloko" — in the UI, code, packages, Docker and docs.
> The file keeps its original name so existing references to `shvluup-spec.md` still work.
> The owner's logo (a pixel-art cow + "moloko" wordmark) is the brand mark; see `docs/decisions.md`.

> Version 1.0 · Pronounced "shalap" (after the Kazakh fermented drink) · Personal AI Platform / "AI Office"
> Audience: an AI coding agent (Claude Code, Codex, etc.) implementing this project, and the human owner reviewing it.

---

## 0. TL;DR

shvluup is a **single-user, self-hosted web app (PWA)** that combines:

1. **Chat** — a ChatGPT-style chat with streaming, history, model selection.
2. **Agent Engine** — an Orchestrator that splits complex tasks and spawns temporary **subagents**; plus persistent **autonomous agents** with their own profile, memory and tools.
3. **Pixel Office** — a 2D top-down pixel-art office (Phaser 3) where every character **is a real agent** and animates according to its **real backend state**.
4. **Multi-device realtime** — start a task on a laptop, close it, open the phone, see live state. Execution happens on the server, never in the browser.

Runs on a home Ubuntu server (Docker Compose), reachable only over **Tailscale**.

**Most important engineering priority:** build a reliable Agent Engine (tasks, events, permissions) FIRST. The Pixel Office is a *view* of that system, never a replacement for it.

---

## 1. How you (the coding agent) must work

### 1.1 Rules of engagement
- Read this entire document before writing code.
- Normative words: **MUST** / **MUST NOT** = hard requirement. **SHOULD** = default unless there is a good reason. **MAY** = optional.
- Implement **sprint by sprint, in order** (section 24). Do not start Sprint N+1 until Sprint N's "Done when" list passes.
- Do not add features outside the current sprint. Do not build items listed in section 25.2 (Out of scope).
- Where this spec is silent, choose the **simplest option that satisfies the principles in section 3**, and record the choice in `docs/decisions.md` (date, decision, reason). Do not silently invent large features.
- Items marked **(default)** are my chosen defaults for gaps in the owner's original brief; they MAY be changed if you record why.
- Commit in small, working steps. Every commit MUST leave the app buildable and tests passing.
- Never hardcode model names, API keys, hostnames or limits. Everything goes through config (section 7).
- **Stop and ask the human owner** before: adding a paid service, changing the auth model, using any provider authentication method other than an official API key (see 13.5), granting agents broader permissions than this spec allows, or deleting data.

### 1.2 Definition of Done (per feature)
A feature is done only when ALL are true:
- Business logic implemented in the backend (not only in the UI).
- Input validated (Pydantic) and authorization checked.
- DB models + Alembic migration added.
- Unit/integration tests added and passing.
- Errors handled and logged (see section 22).
- Audit/events emitted where required.
- Docs updated (`docs/*.md`).
- Verified inside the Docker Compose environment.
- UI shows correct state **after page refresh and after WebSocket reconnect**.

A working UI on top of unreliable backend logic is NOT done.

---

## 2. Product description

| Item | Value |
|---|---|
| Name | **shvluup** (always lowercase) |
| Type | Personal AI platform, web app + PWA |
| Users | One owner (MVP). Architecture must allow multi-user later. |
| UI language | English or Russian, i18n-ready (use an i18n library from day one) |
| Server | Home Ubuntu Server (Huawei MateBook D16, i5-12450H, 16 GB RAM) |
| Network | Tailscale private network only. No public exposure, no Funnel in MVP. |
| Architecture | Modular monolith + background worker process |
| LLMs | External providers only (OpenAI, Anthropic). No local LLMs in MVP. |

### 2.1 Three interface spaces
1. **Chat** — conversations, history, streaming, markdown + code highlighting, file attachments, provider/model picker, "hand off to agents" action, link to related Agent Run, task status indicator.
2. **Subagent Office** — shows temporary subagents spawned by the Orchestrator for one Agent Run (names, specialization, task, status, progress, interactions, results, errors, approval requests).
3. **Agent Office** — shows persistent autonomous agents (profile, workstation, current task, controls).

MVP allowance: ONE Phaser map with a mode/filter switch (Subagents / Agents). A second dedicated map comes after the Agent Engine is stable.

---

## 3. Architectural invariants (never violate)

1. The **backend is the single source of truth** for agent/task state. The frontend and Phaser only render it.
2. **PostgreSQL** holds all durable state. **Redis** is for queues, caches, pub/sub only — never the sole store of run state.
3. Agent execution is **independent of any browser session**.
4. Every significant state change writes an **event** to the event log (section 10) in the same DB transaction.
5. Every tool call is checked by the **backend permission system** before execution. A model's decision is not a permission.
6. Agents have **no unrestricted access** to the host OS. Code/terminal runs in isolated containers.
7. Each AI provider is connected through its **own adapter** behind the Model Gateway. No provider-specific code outside adapters.
8. The UI does not depend on a specific agent runtime.
9. After a lost connection, a client MUST be able to recover correct state (resume by sequence number or fresh snapshot).
10. Errors MUST NOT be masked as success. A task is `completed` only if it actually completed.
11. All sensitive operations have an **audit trail**.
12. New integrations/tools MUST NOT require changing the Orchestrator.
13. **External content is untrusted** (web pages, files, tool output, MCP output). It can never act as system instructions or grant permissions.

---

## 4. Tech stack (decided)

### 4.1 Frontend (`apps/web`)
| Tech | Purpose |
|---|---|
| Next.js (App Router) + React + TypeScript | App framework |
| Tailwind CSS + shadcn/ui | Styling / components |
| Zustand | Client state (realtime store) |
| TanStack Query | REST data fetching/caching |
| Phaser 3 | Pixel Office (mounted as a React component) |
| Native WebSocket (+ SSE for chat streaming) | Realtime |
| PWA (manifest + service worker) | Mobile install |

Requirements: responsive (desktop/tablet/mobile), dark + light theme, UI logic separated from business logic, centralized API error handling, fast load.

### 4.2 Backend (`apps/api`)
Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic, ARQ (Redis queue) for background worker, Redis, WebSockets, SSE for token streaming.

### 4.3 Data & infra
PostgreSQL (primary DB), Redis, Docker + Docker Compose, Caddy or Nginx (reverse proxy), Tailscale, GitHub.

### 4.4 Game engine
Phaser 3 only renders. It MUST NOT contain agent business logic or decide statuses.

---

## 5. Architecture

```
User devices (MacBook / Huawei / Phone)
        │  Tailscale private network
        ▼
   Caddy/Nginx ──► Next.js frontend
        │                │ REST / WS / SSE
        ▼                ▼
      FastAPI backend ───────────────┐
        │        │                   │
        ▼        ▼                   ▼
   PostgreSQL   Redis ───► ARQ Worker ──► Agent Orchestrator
                                              │
                        ┌─────────────────────┼──────────────────┐
                        ▼                     ▼                  ▼
                  Model Gateway        Runtime Adapters    Tool Registry / MCP Manager
                  (OpenAI, Anthropic)                       (+ Permission & Approval)
                                                                 │
                                                          Docker sandbox / File storage
```

### 5.1 Backend modules (modular monolith)
`auth, users, chats, messages, models, agents, agent_runs, tasks, orchestrator, tools, mcp, integrations, memory, approvals, events, files, settings`

Rules:
- Each module exposes a service layer; other modules call the service, not its repository/tables directly.
- API (FastAPI routers) → services → repositories → DB. No business logic in routers.
- The **worker** is a separate process (same codebase). API and worker restart independently.
- Do NOT split into microservices.

---

## 6. Repository layout (monorepo)

```
shvluup/
├── apps/
│   ├── web/                    # Next.js
│   │   ├── app/  components/  features/  hooks/  lib/  stores/  public/
│   └── api/                    # FastAPI
│       ├── app/
│       │   ├── api/  core/  models/  schemas/  services/  repositories/
│       │   ├── agents/  orchestrator/  runtimes/  providers/
│       │   ├── tools/  mcp/  memory/  tasks/  events/  workers/
│       ├── migrations/
│       └── tests/
├── packages/
│   ├── shared-types/           # TS types mirrored from API schemas / event types
│   ├── ui/
│   └── agent-contracts/        # JSON schemas for agent messages & events
├── infrastructure/
│   ├── docker/  nginx/  scripts/  backup/
├── docs/
│   ├── architecture.md  api.md  database.md  security.md  deployment.md  decisions.md
├── docker-compose.yml
├── .env.example
├── .gitignore
└── README.md
```

Keep frontend / backend / infrastructure / shared contracts separated. `.env` MUST be git-ignored; only `.env.example` is committed.

---

## 7. Configuration

All via environment variables / settings object (Pydantic Settings). Nothing hardcoded.

### 7.1 Env vars (names are (default))
```
DATABASE_URL, REDIS_URL
SECRET_KEY                      # session signing
APP_ENCRYPTION_KEY              # encrypting provider secrets at rest
OPENAI_API_KEY, ANTHROPIC_API_KEY   # optional; can also be set via Settings UI (encrypted)
SESSION_TTL_HOURS=168
CORS_ALLOWED_ORIGINS
WORKSPACE_ROOT=/data/workspaces
FILE_STORAGE_ROOT=/data/files
```

### 7.2 Execution limits (all configurable; values are (default) unless stated by the owner)
| Setting | Default | Source |
|---|---|---|
| `MAX_ACTIVE_SUBAGENTS_PER_RUN` | 5 | owner |
| `MAX_SUBAGENT_DEPTH` | 2 | owner |
| `MAX_STEPS_PER_RUN` | 50 | default |
| `RUN_TIMEOUT_SECONDS` | 1800 | default |
| `MAX_RETRIES_PER_STEP` | 2 | default |
| `MAX_PARALLEL_TOOL_CALLS` | 3 | default |
| `SANDBOX_CPU_LIMIT` / `SANDBOX_MEM_LIMIT` / `SANDBOX_TIMEOUT_SECONDS` | 1 CPU / 512 MB / 120 s | default |
| `APPROVAL_TTL_MINUTES` | 60 | default |

A **global kill switch** (stop all active runs) and per-agent cancel MUST exist.

---

## 8. Domain model

All PKs are UUIDs. All timestamps are `timestamptz` (UTC). Every table has `created_at`, `updated_at` unless it is append-only (events, audit_logs).

### 8.1 Tables
| Table | Purpose |
|---|---|
| users | Owner account (design for multi-user later: all owned tables have `user_id`) |
| sessions | Auth sessions |
| conversations | Chats |
| messages | Chat messages (role, content, model, tokens, status) |
| model_providers | Provider configs (type, encrypted credentials, enabled) |
| model_configs | Model entries per provider (name from config/API, params) |
| agents | Agent profiles (autonomous, orchestrator, subagent) |
| agent_runs | One execution of an Orchestrator/agent for a goal |
| tasks | User/agent/subtask/review tasks |
| subtasks | Decomposed work items (may be modeled as `tasks.parent_task_id`; record in decisions.md) |
| agent_events | Append-only event log (section 10) |
| agent_messages | Structured agent↔agent messages |
| tools | Tool registry entries |
| mcp_servers | Registered MCP servers |
| integrations | GitHub, browser, file system config |
| memories | Structured memory records |
| workspaces / workspace_files | Sandbox workspaces and file metadata |
| approvals | Pending/resolved approval requests |
| audit_logs | Append-only security/audit journal |

### 8.2 Key relations
User→Conversations, Conversation→Messages, User→Agents, Agent→AgentRuns, AgentRun→Tasks, Task→Subtasks, AgentRun→AgentEvents, Agent→AgentMessages, Agent→Memories, Agent↔Tools (many-to-many), Workspace→WorkspaceFiles.

### 8.3 Agent profile fields
```
id, user_id, name, description, agent_type (orchestrator|subagent|autonomous),
provider, model, system_prompt, autonomy_level (supervised|balanced|restricted),
allowed_tools[], permissions{}, status, current_task_id, parent_agent_id,
limits{}, memory_settings{}, runtime, config_version, created_at, updated_at
```

### 8.4 Enums
- **AgentStatus:** `idle, planning, working, waiting, reviewing, paused, completed, failed`
- **TaskStatus:** `created, queued, running, waiting_approval, waiting, completed, failed, cancelled`
- **TaskType:** `user, agent, subtask, scheduled (future, do not implement), review`
- **ToolCategory:** `read, write, sensitive`
- **ApprovalStatus:** `pending, approved, rejected, expired, cancelled`
- **MemoryType:** `user, agent, project, task_context, conversation_context`

### 8.5 State machines (MUST be enforced in code, invalid transitions rejected)
**Agent:**
```
idle → planning → working → reviewing → completed
working ↔ waiting          (waiting = external answer/resource/approval)
any active → paused → (resume) previous active state
any → failed
completed/failed are terminal for subagents; autonomous agents return to idle after a task.
```
**Task:**
```
created → queued → running → completed
running → waiting_approval → running | cancelled
running → waiting → running
running → failed
created|queued|running|waiting* → cancelled
failed → (retry creates a NEW attempt; keep history)
```
Every transition writes an `agent.status_changed` / `task.updated` event.

---

## 9. Task management

Capabilities: create, edit description, assign agent, priority, deadline, subtasks, progress, event history, results, file attachments, cancel, retry, approval handling.

### 9.1 Restart recovery (MUST implement)
On API/worker start:
1. Find tasks/runs in `running`/`queued`/`waiting*`.
2. Inspect last recorded step/event.
3. If safe to resume → re-enqueue. Otherwise → set `waiting` (needs user decision).
4. **Never auto-repeat an operation whose outcome is unknown** (e.g., a write/publish/send). Surface it to the user.
5. External side-effecting calls MUST carry an operation/idempotency ID, stored before the call is made.

---

## 10. Event system

The event log is both the audit history and the realtime feed.

### 10.1 Event envelope
```json
{
  "id": "uuid",
  "seq": 12345,
  "type": "agent.status_changed",
  "version": 1,
  "timestamp": "2026-10-31T12:00:00Z",
  "agent_id": "uuid|null",
  "task_id": "uuid|null",
  "run_id": "uuid|null",
  "payload": { "old_status": "planning", "new_status": "working" }
}
```
- `id` = unique UUID; `seq` = monotonically increasing bigint (identity column) used for resume (default).
- Events are immutable and append-only.

### 10.2 Event types (v1)
```
agent.created  agent.updated  agent.status_changed  agent.message
agent.task_started  agent.task_completed  agent.task_failed
task.created  task.updated  task.completed  task.failed  task.cancelled
approval.required  approval.resolved
chat.message_delta  chat.message_completed
```

### 10.3 Write path
`state change + event INSERT` in ONE DB transaction → after commit, publish to Redis pub/sub → WS gateway fans out to connected clients. `chat.message_delta` MAY skip persistence (stream only), but `chat.message_completed` MUST persist the final message.

---

## 11. Realtime protocol

- **WebSocket:** `/ws/v1/events` (auth via the session cookie; reject unauthenticated).
- **Chat token streaming:** SSE (simpler/more reliable) or WS — choose one and record it.

Handshake (default):
```
client → {"type":"hello","last_seq": 12000 | null}
server → {"type":"snapshot","seq": 12345, "agents":[...], "tasks":[...], "approvals":[...]}   # if last_seq null or too old
server → {"type":"event", ...envelope}                                                        # replayed missed events, then live
client ↔ ping/pong heartbeat every ~25s
```
- Client reconnects with exponential backoff and resends `last_seq`.
- Client dedupes by `id`/`seq` (no double-processing).
- Missed-event window: if `last_seq` is older than retained history, send a fresh snapshot.
- Minimum 3 simultaneous devices must work.

**Multi-device scenario that MUST work:** start task on laptop → close laptop → open phone → latest state loads → execution continued on the server → live updates continue.

---

## 12. REST API

Prefix `/api/v1`. All inputs validated. State-changing endpoints require auth and (for cookie auth) a CSRF token. Mutating endpoints that start work SHOULD accept an `Idempotency-Key` header.

**Conventions (default):** JSON; errors as `{"error":{"id","code","message","details?"}}`; list endpoints paginated (`limit`, `cursor`); OpenAPI auto-generated; TS types generated into `packages/shared-types`.

```
# Auth
POST /auth/login   POST /auth/logout   GET /auth/me

# Chats
GET /chats   POST /chats   GET /chats/{id}   PATCH /chats/{id}   DELETE /chats/{id}
GET /chats/{id}/messages   POST /chats/{id}/messages

# Models / providers
GET /models   GET /providers   POST /providers   PATCH /providers/{id}

# Agents
GET /agents   POST /agents   GET /agents/{id}   PATCH /agents/{id}   DELETE /agents/{id}
POST /agents/{id}/run   POST /agents/{id}/pause   POST /agents/{id}/resume   POST /agents/{id}/stop

# Tasks
GET /tasks   POST /tasks   GET /tasks/{id}   PATCH /tasks/{id}
POST /tasks/{id}/cancel   POST /tasks/{id}/retry

# Approvals
GET /approvals   POST /approvals/{id}/approve   POST /approvals/{id}/reject

# Tools
GET /tools   GET /tools/{id}   POST /tools/{id}/enable   POST /tools/{id}/disable

# Events
GET /events   GET /events/{id}
WS  /ws/v1/events
```
Also needed (default): `POST /system/stop-all` (kill switch), `GET /health`.

---

## 13. Model Gateway & Runtime Adapters

### 13.1 Model Gateway
Single interface used by the rest of the app. Requirements:
- Unified call interface incl. **streaming**.
- Provider errors normalized (rate limit, auth, timeout, provider down).
- Timeouts, bounded retries with backoff, cancellation support.
- Token usage + approximate cost tracking where the provider returns data.
- Model chosen **per agent**; changing provider MUST NOT require changing agent logic.
- Model names come from config / provider model lists — never hardcoded.

### 13.2 Provider contract (Python sketch)
```python
class ModelProvider(Protocol):
    name: str
    async def list_models(self) -> list[ModelInfo]: ...
    async def complete(self, req: ChatRequest) -> ChatResult: ...
    async def stream(self, req: ChatRequest) -> AsyncIterator[ChatChunk]: ...
```
Adapters: `providers/openai_provider.py`, `providers/anthropic_provider.py`, later others.

### 13.3 Runtime adapter contract
```
apps/api/app/runtimes/
    base.py  openai_runtime.py  anthropic_runtime.py  custom_runtime.py
```
```python
class AgentRuntime(Protocol):
    async def start(self, ctx: RunContext) -> None: ...      # run a task with context
    async def cancel(self, run_id: UUID) -> None: ...
    # During execution the runtime reports via ctx.emit(event) :
    #   intermediate results, tool calls, final answer, errors → common event system
```
Required: start task, pass context, receive intermediate + final results, handle errors, cancel, emit events to the shared event system.

### 13.4 Example per-agent config (illustrative, NOT fixed)
| Agent | Provider | Model |
|---|---|---|
| Orchestrator | OpenAI | a configured reasoning model |
| Research | Anthropic | a configured Claude model |
| Coding | OpenAI | a configured coding model |
| Reviewer | Anthropic | a configured Claude model |

### 13.5 Provider authentication policy (IMPORTANT)
- Having a ChatGPT/Claude **subscription does not** mean its login may be used in any third-party app.
- **MVP implements ONLY official API-key authentication** for OpenAI and Anthropic.
- You MUST NOT: extract private tokens from local apps/CLIs, bypass OAuth restrictions, or build unofficial proxies for subscription auth.
- If the owner later wants subscription-based access, it MUST go through an officially documented mechanism whose current terms you have verified; **stop and ask the owner first** (terms for these programs have changed repeatedly).
- Keep the auth layer pluggable so an API key can always be configured as a fallback.

---

## 14. Agent system

### 14.1 Agent types
- **Orchestrator** — receives a complex task; analyzes it; decomposes; decides needed specializations; creates subagents within limits; assigns work; monitors; collects results; verifies completeness; produces the final answer.
- **Subagent** — temporary; created by the Orchestrator for one subtask (e.g., Research, Coding, Data Analyst, Reviewer, Documentation). Has its own task, context, constraints, tools. On finish → `completed`; history + results are kept.
- **Autonomous agent** — persistent profile (e.g., Developer, Research, Personal Assistant, Project Manager, Finance Analyst, GitHub Assistant). Can be run manually, receive tasks from the Orchestrator, use memory + allowed integrations, resume allowed tasks after restart. Scheduled/proactive work is out of scope for MVP.

### 14.2 Autonomy levels
| Level | Behavior |
|---|---|
| `supervised` | Important actions (all `write` and `sensitive`) need user approval |
| `balanced` | Ordinary permitted actions run automatically; `sensitive` still needs approval |
| `restricted` | Only explicitly whitelisted tools/operations in strictly defined bounds; everything else denied (default interpretation) |

An autonomy level MUST NOT grant more than the security policy allows. Per-tool/operation overrides are allowed but can only be *stricter* than the policy floor for `sensitive` operations.

### 14.3 Orchestration algorithm
1. Receive user task (from chat or tasks page).
2. Assess complexity. **Do not spawn subagents for simple requests** — answer directly. Weigh cost, complexity, and benefit of parallelism.
3. Produce a plan (persist it).
4. Determine required specializations.
5. Create subagents within limits (`MAX_ACTIVE_SUBAGENTS_PER_RUN`, `MAX_SUBAGENT_DEPTH`).
6. Give each subagent its own context, constraints, tools.
7. Start execution (parallel where independent).
8. Consume intermediate events.
9. Validate results; optionally run a Reviewer subagent.
10. Assemble the final result and report to the chat/task.

Chat integration: if a chat message looks like a complex multi-step task, the system SHOULD propose (or, per setting, start) an Agent Run and link it from the chat.

### 14.4 Agent↔agent messages
Structured, persisted in `agent_messages`:
```json
{
  "sender_agent_id": "research_01",
  "receiver_agent_id": "analysis_01",
  "message_type": "task_result",
  "content": { "summary": "Research completed", "artifacts": [], "notes": [] }
}
```
Required: send, receive, pass results, pass file artifacts, delivery-error handling, and **verify both agents belong to the same permitted run/workspace** before delivery.

### 14.5 Limits
Enforce all limits from section 7.2 in the Orchestrator/runtime, not only in prompts.

---

## 15. Tools, permissions, approvals

### 15.1 Tool Registry
Every tool defines: unique name, description, input JSON schema, output schema, required permissions, **category** (`read|write|sensitive`), confirmation policy, execution limits, usage logging.

MVP tools: File Reader, File Writer, Terminal (restricted, sandboxed), GitHub integration, Browser/Search.
Later: Calendar, Email, Google Drive, Notion, more MCP servers.

### 15.2 Permission check (MUST run in backend before EVERY tool execution)
```
authorize(agent, tool, args, context) -> ALLOW | REQUIRE_APPROVAL | DENY (+ reason)
```
Order of checks:
1. Tool is enabled and in `agent.allowed_tools`, else DENY.
2. Args valid against schema; paths/resources inside the agent's workspace/allowed scope, else DENY.
3. Category + autonomy policy (section 14.2).
4. `sensitive` → always REQUIRE_APPROVAL.
5. Write decision + reason to `audit_logs`.
Model output never overrides this result.

### 15.3 Categories
| Category | Examples | Policy |
|---|---|---|
| read | read files, analyze data | automatic if permitted |
| write | create/modify files, change project | per agent settings |
| sensitive | delete, publish, change system settings, send messages as the user | approval required |

### 15.4 Approval system
Approval record binds to ONE specific operation (store tool name + a hash of the exact arguments) and has an expiry (`APPROVAL_TTL_MINUTES`). It MUST NOT carry over to other actions.
User sees: requesting agent, its current task, exact action, affected resources, expected consequences. Buttons: **Approve / Reject / Cancel Task**.
Flow: tool call → `REQUIRE_APPROVAL` → task `waiting_approval` + `approval.required` event → user decision → `approval.resolved` event → resume or abort.
Examples requiring approval: publishing, deleting files, changing server config, sending messages on the user's behalf, changing important integration settings, high-impact external operations.

### 15.5 MCP Manager
- Add/configure MCP servers, list their tools, enable/disable tools, assign tools to agents, set permissions, log calls, handle server downtime.
- Each MCP server runs with an isolated config.
- **Never auto-trust** all tools of a newly connected MCP server — new tools start disabled.
- MCP output is untrusted content.

### 15.6 Integrations
- **GitHub:** browse repos, read files, analyze code, create branches/commits/PRs, read issues/history. Changing the main branch or publishing follows the permission policy (sensitive).
- **Browser:** open pages, search, read, extract structured data. Treat all content as untrusted (prompt injection).
- **File system:** read/write/create/rename/move inside allowed workspaces; **delete requires approval**.
- **Terminal:** only inside the sandbox; commands pass permission + limit checks.

---

## 16. Workspace & code execution

- A separate workspace per task/project; only allowed directories accessible; log all changes; clean up temp workspaces.
- Code/terminal execution MUST run in isolated Docker containers (or equivalent) with:
  CPU limit, RAM limit, wall-clock timeout, restricted filesystem, controlled network access, **no Docker socket access**, **no host secrets**, separate working dirs, command allow/deny control, no unrestricted root.
- Record for each task: commands run, files created/changed, errors, results.

---

## 17. Memory system

Types: User, Agent, Project, Task Context, Conversation Context.
Operations: create, read, update, delete; scope to an agent or project; access control; change history; context-size limiting.
MVP: plain structured rows in PostgreSQL. **No vector DB / semantic search** until a real need appears.
Memory MUST NOT automatically turn arbitrary file/web text into trusted system instructions — memory entries are data, injected into prompts clearly marked as such.

---

## 18. Pixel Office

### 18.1 Concept
2D top-down pixel art. Each character = a real agent. Position, animation, and indicators reflect real state. It is NOT decorative.

### 18.2 Visual style
Pixel art, top-down, cohesive set (desks, computers, rooms, meeting zones, info boards, interactive objects). Must look stylistically unified — don't mix unrelated asset packs. Keep an `assets/MANIFEST.md` listing every asset's source and license. Placeholder art is acceptable until the engine works.

### 18.3 Spaces
- **Subagent Office:** several workstations, shared work area, discussion room, task board, waiting zones, interaction visualization.
- **Agent Office:** individual desks/offices, personal zones, current-task display, per-agent info.
(MVP: one map + mode switch — see section 2.1.)

### 18.4 Status → animation
| Status | Visual |
|---|---|
| idle | resting |
| planning | thinking / looking at board |
| working | typing at computer |
| waiting | waiting pose |
| reviewing | studying documents |
| paused | frozen/paused indicator |
| completed | completion gesture |
| failed | error indicator |

### 18.5 Interaction — Agent Inspector
Click a character → panel with: name, type, current task, status, model, provider, autonomy level, tools, recent events, results, and actions: **Open details, Pause, Resume, Stop, View task, View logs, Change settings** (dangerous actions go through permission checks).

### 18.6 Technical requirements
- Phaser 3, base resolution **640×360**, pixel-perfect rendering, texture smoothing disabled (`pixelArt: true`, integer scaling).
- Camera pan + zoom; mobile: touch drag + pinch zoom.
- Optimize animation count; adapt to mobile screens.

### 18.7 Data flow (one direction)
```
Agent Runtime → Agent Events → DB → Realtime Event System → WebSocket → Frontend store (Zustand) → Phaser scene
```
On connect: load snapshot, then subscribe to events. Phaser reads from the store; it never mutates agent state.

---

## 19. Frontend pages

Navigation: `Chat · Subagent Office · Agent Office · Tasks · Integrations · Settings`

- **Chat:** sidebar history, dialog area, input, model picker, send, attach files, progress indicator, link to Agent Run.
- **Subagent Office:** game scene, subagent characters, active-task panel, agent list, filters, Agent Inspector, Event Log.
- **Agent Office:** persistent agents, workstations, statuses, current tasks, create/manage agents.
- **Tasks:** all/active/completed/failed, filters, search, subtasks, execution history.
- **Integrations:** providers, MCP servers, GitHub, Browser, File System, health, permissions, connection settings.
- **Settings:** General, AI Providers, Models, Agent Defaults, Autonomy, Permissions, Notifications, Appearance, Security, Storage, Backup.

---

## 20. Security requirements

Agents act on the owner's behalf, so security is part of the architecture.

**Auth:** strong password hashing (argon2id (default)); secure HTTP-only cookie sessions with expiry; CSRF protection for cookie auth; all API routes protected. Tailscale is network-level only and does NOT replace app auth.

**Secrets:** API keys only on the backend; never sent to the frontend; never logged; `.env` never committed; provider credentials encrypted at rest in the DB.

**Agent isolation:** see section 16; no unrestricted root; network control.

**Prompt-injection defense:** external content is untrusted; cannot override the system prompt; instructions inside documents/pages grant no permissions; tool execution is checked independently of model output; sensitive ops need separate confirmation; an agent cannot raise its own privileges.

**Audit log:** record agent runs, config changes, tool usage, approval requests/decisions, rejected actions, file changes, errors, integration operations. Owner can view it.

**Network:** PostgreSQL and Redis NOT exposed publicly; admin interfaces not public; SSH restricted; HTTPS via Tailscale Serve/MagicDNS TLS; no Tailscale Funnel; Tailscale ACL/grants limit access to needed services.

---

## 21. Infrastructure & deployment

### 21.1 Docker Compose services
`frontend, backend, worker, postgres, redis, nginx (or caddy)`; optional later: `backup, monitoring` (no heavy monitoring stack at first).
- `restart: unless-stopped` for critical services; health checks on all; containers auto-start after reboot.
- Postgres/Redis on an internal network only.

### 21.2 Reliability
Health checks, disk-space monitoring, error logs, graceful shutdown of background jobs.
Note: a home laptop is not 24/7. Power/internet loss = downtime. (UPS / dedicated hardware later.)

### 21.3 Backup & recovery
- Automatic PostgreSQL backups + file-data backups; manual backup command.
- Integrity verification of backups; written restore instructions in `docs/deployment.md`.
- Store backups **off the primary disk**. A backup on the same physical disk is not real protection.
- Policy (default): daily backups, keep several recent dailies, periodic weeklies, periodically test a restore.

---

## 22. Error handling

Handle: provider unavailable, rate limits, provider auth errors, MCP server down, tool failure, worker restart, WebSocket loss, PostgreSQL down, Redis down, low disk, agent failure, limit exceeded.

Each error has: unique ID, type, time, linked run, linked task, a clear user-facing message; technical details go to the server log only. Never display a task as complete if it was not.

---

## 23. Testing

- **Unit:** Agent Manager, Task Manager, Model Gateway, Permission System, Event System, Memory System, API validation, state machines.
- **Integration:** backend+Postgres, backend+Redis, worker+runtime, gateway+provider adapter (mock provider in CI), WebSocket+frontend, MCP+Tool Registry.
- **E2E scenarios:** (1) create chat (2) send message (3) get AI reply (4) create autonomous agent (5) give it a task (6) it executes (7) its status shows in the office (8) Orchestrator spawns subagents (9) subagents finish subtasks (10) results merged (11) user approves a sensitive action (12) task completes (13) open on another device (14) correct state shown.
- **Recovery:** restart backend; restart worker; drop WebSocket; Redis outage; provider outage; recovery of unfinished tasks.
- Use a **fake/mock provider** so tests don't spend money or need network.

---

## 24. Sprints (build in this order)

### Sprint 1 — Infrastructure foundation
Tasks: monorepo skeleton; Docker + Compose; Next.js app; FastAPI app; PostgreSQL + Alembic; Redis; Tailscale access docs; owner authentication; health checks; `.env.example`; CI-style test runner.
**Done when:** `docker compose up` starts everything; app opens over Tailscale from ≥2 devices; login works; DB migrations run; health endpoint green.

### Sprint 2 — Chat system
Tasks: chat UI; conversations + messages tables; history; Model Gateway; first **official API-key** provider adapter (then the second); streaming; model settings UI; provider error handling; persist messages.
**Done when:** user chats with a real model with streaming; history survives reload; provider errors show clearly; mock-provider tests pass.

### Sprint 3 — Agent engine
Tasks: Agent Manager + profiles; Task Manager; Agent Runs; status state machines; ARQ worker; event log + realtime events (WS, snapshot + resume); cancel; restart recovery.
**Done when:** one agent runs a task in the background; UI shows live status; closing the browser doesn't stop the run; reload/reconnect restores state; worker restart recovers safely.

### Sprint 4 — Orchestrator & subagents
Tasks: Orchestrator; planning; task decomposition; subagent creation within limits; context passing; agent messaging; result aggregation; Reviewer step; parallelism limits.
**Done when:** one complex user task is split and executed by multiple subagents (≤5 active, ≤2 depth), results are merged, limits provably enforced by tests.

### Sprint 5 — Pixel Office
Tasks: Phaser integration in React; map; characters; workstations; animations per status; Agent Inspector; realtime sync from the store; mobile camera controls.
**Done when:** the office shows real agents, status matches backend (including after refresh/reconnect), inspector shows live info and controls work.

### Sprint 6 — Autonomous agents
Tasks: agent profile CRUD; per-agent models; system prompts; autonomy levels; agent memory; management UI; per-agent task history.
**Done when:** the owner can create, edit, run, pause, resume and delete persistent agents and see them in Agent Office.

### Sprint 7 — Tools & integrations
Tasks: Tool Registry; Permission System; Approval System + UI; Docker sandbox workspaces; file tools; terminal tool; GitHub; Browser; MCP Manager; audit logs.
**Done when:** agents use tools only through backend permission checks; sensitive actions block on approval; sandbox limits verified; every tool use is audit-logged.

### Sprint 8 — Stabilization & mobile
Tasks: PWA; mobile polish; notifications; backups + restore drill; recovery tests; performance pass; security review; E2E suite; docs.
**Done when:** all items in section 25.3 pass.

---

## 25. Scope

### 25.1 MVP includes
Private access via Tailscale; single-user auth; chat + history; ≥1 AI provider (official API key); model selection; agent creation; background tasks; Orchestrator; subagents (max 5 active); agent statuses; realtime sync; basic Subagent Office; basic Agent Office (or agents mode on the shared map); basic memory; basic permissions; approvals for sensitive actions; logs; backups.

### 25.2 Out of scope for MVP (do NOT build)
Public registration; SaaS billing; multi-user teams; native mobile apps; custom large LLM / local LLMs; vector database; unrestricted autonomy; complex scheduling; dozens of simultaneous agents; unrestricted OS access; auto-publishing without control.

### 25.3 Acceptance criteria (checklist)
**Infrastructure**
- [ ] Ubuntu server runs the app stably; all services via Docker Compose.
- [ ] App reachable via Tailscale from MacBook, Huawei, phone.
- [ ] PostgreSQL and Redis not reachable from the public internet.

**Chat**
- [ ] Create conversations; history persists; streaming works; model selectable; provider errors handled.

**Agents**
- [ ] Create/edit agents; assign models; run tasks; statuses correct; pause/cancel; state restored after restart.

**Subagents**
- [ ] Orchestrator decomposes; creates subagents; passes context; receives and merges results; respects concurrency/depth limits.

**Pixel Office**
- [ ] Shows real agents; statuses synced with backend; profile opens; current task visible; live updates.

**Security**
- [ ] API keys never reach the frontend; agents run in restricted environments; permissions checked on the backend; sensitive actions need approval; audit log exists.

**Multi-device**
- [ ] Start on one device, open another, see current status, get the result without re-running.

**Performance targets (normal home network):** main page ≤3 s; open saved chat ≤2 s; realtime event shown usually ≤1 s; section switching without full reload; ≤5 concurrent subagents; ≥3 concurrent devices. (AI response time depends on the provider.) Stability and correctness beat parallelism.

---

## 26. Open items & assumptions (flag, don't guess silently)

1. **Subscription-based model access** (Claude plan → Claude models, Codex/ChatGPT plan → OpenAI models) is a stated owner goal, but provider terms restrict third-party use of subscription logins and have changed during 2026. MVP uses official API keys (13.5). Revisit only after verifying current official terms with the owner.
2. Chat streaming transport (SSE vs WS) — pick one, record it.
3. `subtasks` as separate table vs `tasks.parent_task_id` — pick one, record it.
4. Exact default limit values in 7.2 (except owner-specified ones) — adjustable.
5. Pixel art assets — source/licensing to be decided by the owner; use placeholders first.
6. i18n default language (English vs Russian) — owner decides; build i18n from the start.

---

## 27. Final summary

shvluup is a personal AI Office: one interface for multiple models, autonomous execution of complex tasks, collaboration between specialized agents, and visual control through a pixel-art office that mirrors real system state.

**Build order:** Infrastructure → Chat → Agent Engine → Orchestrator → Pixel Office → Autonomous Agents → Tools & Integrations → Stabilization.

Reliable engine first; the pretty office is a view of it.
