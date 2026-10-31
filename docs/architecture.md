# Architecture

Status: **Sprint 1** (infrastructure foundation). See `shvluup-spec.md` §5 for the target
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
- The ARQ **worker** joins in Sprint 3 (same image as the backend, different command).

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
