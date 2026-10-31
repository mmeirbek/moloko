# moloko — notes for coding agents

Read first, in this order:
1. `shvluup-spec.md` — the full specification (the product was renamed **moloko**; read "shvluup" as "moloko").
2. `docs/external-repositories.md` — which open-source repos are USE / REFERENCE / AVOID, and the rules for adding any dependency.
3. `docs/decisions.md` — every choice made so far + the dependency register. Add to it whenever you decide something the spec leaves open.

## Status
- Sprint 1 (infrastructure foundation): **done**. Next: Sprint 2 (chat). Do not start a later sprint early.

## Hard rules (from the spec — never break)
- Backend is the single source of truth; PostgreSQL holds all durable state; Redis never holds the only copy.
- Every new API router goes into `protected` in `apps/api/app/api/v1/router.py`. Public routes must be added to `PUBLIC_ROUTES` deliberately. Never use `include_in_schema=False`.
- State-changing requests need CSRF (global middleware) — don't bypass it.
- Official API keys only for AI providers (spec 13.5). Ask the owner before anything else.
- Never log secrets, passwords, tokens, cookies, or request bodies. `audit_logs` is append-only (DB trigger).
- No hardcoded model names, hosts, keys or limits — add settings to `apps/api/app/core/config.py` and `.env.example`.

## Commands
- All checks (what CI runs): `infrastructure/scripts/check.sh`
- Backend only (starts throwaway Postgres/Redis containers): `infrastructure/scripts/test-api.sh`
- After changing API schemas: `cd apps/api && uv run python scripts/export_openapi.py && cd ../.. && npm run generate:types`
- New migration: `cd apps/api && uv run alembic revision --autogenerate -m "..."` (review it; `tests/test_migrations_and_audit.py` checks models == migrations)
- Frontend: `npm run lint`, `npm run typecheck`, `npm run test`, `npm run build`

## Layout
- `apps/api` — FastAPI: `api/` (routers, no logic) → `services/` → `repositories/` → `models/`. `core/` = config, db, security, errors, middleware.
- `apps/web` — Next.js App Router. `app/` routes, `features/` (feature components + hooks), `components/ui` (shadcn-style), `lib/api` (the only place that calls `fetch`), `messages/` (ru + en, same keys — tested).
- `packages/shared-types` — generated TS types from the API's OpenAPI schema (committed, CI checks drift).
- `infrastructure/` — Dockerfiles, Caddyfile, scripts.
