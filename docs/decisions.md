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
| redis (redis-py) | 8.1.0 | MIT | Redis client | 1 | 2026-10-31 |
| argon2-cffi | 25.1.0 | MIT | argon2id password hashing | 1 | 2026-10-31 |
| pytest / pytest-asyncio | 9.2.0 / 1.4.1 | MIT / Apache-2.0 | Tests (dev) | 1 | 2026-10-31 |
| httpx | 0.28.1 | BSD-3-Clause | Test client (dev) | 1 | 2026-10-31 |
| ruff | 0.17.3 | MIT | Lint + format (dev) | 1 | 2026-10-31 |
| mypy | 2.4.1 | MIT | Type checking (dev) | 1 | 2026-10-31 |
| uv | 0.11.32 | MIT OR Apache-2.0 | Python package manager (build tool) | 1 | 2026-10-31 |
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
| **Container images** | | | | | |
| postgres | 17.11-alpine | PostgreSQL License | Database | 1 | 2026-10-31 |
| redis | 8.10.3-alpine | RSALv2 / SSPLv1 / AGPLv3 (we rely on AGPLv3) | Cache/queue/pub-sub | 1 | 2026-10-31 |
| caddy | 2.11.7-alpine | Apache-2.0 | Reverse proxy | 1 | 2026-10-31 |
| python | 3.12.16-slim | PSF-2.0 | Backend runtime | 1 | 2026-10-31 |
| node | 22.23.4-alpine | MIT | Frontend runtime | 1 | 2026-10-31 |
