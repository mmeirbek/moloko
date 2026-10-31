# Security

Agents will act on the owner's behalf, so security is part of the architecture (spec §20).
This file tracks what is implemented and what is still open.

## Implemented (Sprint 1)

**Network**
- Only Caddy publishes a port, on `127.0.0.1:8080`; reachable from outside only through Tailscale Serve (HTTPS, tailnet members only). No Funnel.
- PostgreSQL and Redis sit on an `internal: true` Docker network: no published ports, no egress.
- Tailscale is network-level only — the app has its own authentication.

**Authentication**
- Single owner account, created via CLI; no registration endpoint.
- argon2id hashes (argon2-cffi defaults, RFC 9106 profile), rehash on parameter change; hashing runs off the event loop.
- Unknown usernames take the same time and return the same error as wrong passwords.
- Lockout after `LOGIN_MAX_FAILURES` failures per username within `LOGIN_LOCKOUT_SECONDS` → `429`.
- Server-side sessions: random 256-bit token in an `HttpOnly; Secure; SameSite=Lax` cookie, only its SHA-256 in the DB, absolute expiry, revocation on logout and password reset. Sessions on different devices are independent.

**CSRF**: signed double-submit token bound to the session, checked by a global middleware on every non-GET `/api/*` request (login included). `SameSite=Strict` CSRF cookie.

**Authorization**: every API route requires a session unless explicitly allow-listed; a test checks every route in the schema.

**Data handling**
- Secrets only via environment variables; `.env` is git- and docker-ignored; compose refuses to start without `POSTGRES_PASSWORD` / `SECRET_KEY`; `SECRET_KEY` must be ≥32 chars.
- Logs are JSON lines with explicit fields only — no bodies, cookies, tokens or passwords. Validation errors never echo input.
- Audit log of auth events and account changes, append-only enforced by a DB trigger.

**Containers**: pinned image versions; backend non-root (uid 10001), read-only root FS, `cap_drop: ALL`, `no-new-privileges`; frontend non-root, `cap_drop: ALL`; Caddy only `NET_BIND_SERVICE`. No Docker socket mounted anywhere.

**HTTP headers** (Caddy): `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`, `Cross-Origin-Opener-Policy`, restrictive `Permissions-Policy`; `Server` header removed. API responses are `no-store`. `robots.txt` disallows everything.

## Open items

| Item | Planned |
|---|---|
| Content-Security-Policy with nonces | Sprint 8 security review |
| Encrypting provider API keys at rest (`APP_ENCRYPTION_KEY`) | Sprint 2 |
| Permission system, approvals, sandbox isolation | Sprint 7 |
| UI for viewing the audit log | Sprint 7/8 |
| Expired-session cleanup job | Sprint 3 (worker) |
| Redis password | Revisit in Sprint 7 (sandbox containers) |
| Automated backups off the primary disk | Sprint 8 |

## Reporting

This is a private, single-owner project. Report problems to the owner directly.
