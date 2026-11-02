# Security

Agents will act on the owner's behalf, so security is part of the architecture (spec §20).
This file tracks what is implemented and what is still open.

## Implemented (Sprint 1)

**Network**
- Only Caddy publishes a port, on `127.0.0.1:8080`; reachable from outside only through Tailscale Serve (HTTPS, tailnet members only). No Funnel.
- PostgreSQL and Valkey (Redis-compatible) sit on an `internal: true` Docker network: no published ports, no egress.
- Tailscale is network-level only — the app has its own authentication.

**Authentication**
- Single owner account, created via CLI; no registration endpoint.
- argon2id hashes (argon2-cffi defaults, RFC 9106 profile), rehash on parameter change; hashing runs off the event loop.
- Unknown usernames take the same time and return the same error as wrong passwords.
- Lockout after `LOGIN_MAX_FAILURES` failures per username within `LOGIN_LOCKOUT_SECONDS` → `429`. Wrong passwords given to confirm a change while signed in (e.g. the session lifetime) count toward the same lockout, so a stolen session cannot be used to guess the password.
- Server-side sessions: random 256-bit token in an `HttpOnly; Secure; SameSite=Lax` cookie, only its SHA-256 in the DB, absolute expiry, revocation on logout and password reset. Sessions on different devices are independent.
- The owner can choose the session lifetime (`SESSION_TTL_MIN_HOURS..SESSION_TTL_MAX_HOURS`, default `SESSION_TTL_HOURS`) — only with the password. A shorter lifetime also shortens the other open sessions; a longer one never extends them (only the session that confirmed it).

**CSRF**: signed double-submit token bound to the session, checked by a global middleware on every non-GET `/api/*` request (login included). `SameSite=Strict` CSRF cookie.

**Authorization**: every API route requires a session unless explicitly allow-listed; a test checks every route in the schema.

**Data handling**
- Secrets only via environment variables; `.env` is git- and docker-ignored; compose refuses to start without `POSTGRES_PASSWORD` / `SECRET_KEY`; `SECRET_KEY` must be ≥32 chars.
- Logs are JSON lines with explicit fields only — no bodies, cookies, tokens or passwords. Validation errors never echo input.
- Audit log of auth events and account changes, append-only enforced by a DB trigger.

**Containers**: pinned image versions; backend non-root (uid 10001), read-only root FS, `cap_drop: ALL`, `no-new-privileges`; frontend non-root, `cap_drop: ALL`; Caddy only `NET_BIND_SERVICE`. No Docker socket mounted anywhere.

**HTTP headers** (Caddy): `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`, `Cross-Origin-Opener-Policy`, restrictive `Permissions-Policy`; `Server` header removed. API responses are `no-store`. `robots.txt` disallows everything.

**AI providers (Sprint 2)**: official API keys only; keys encrypted at rest (Fernet), never returned to the browser (only `…last4`), never logged (provider errors are redacted); official base URLs pinned so environment variables can't redirect keys; `base_url` overrides must be HTTPS; model output rendered without raw HTML.

**Memory (Sprint 6)**: memory is injected into prompts only as fenced, labelled data (never as instructions); fence-like text inside entries is neutralised; per-entry and per-prompt size limits; subagents get no memory; the audit log records memory changes without their content; "forget" deletes the entry and its history.

**Tools (Sprint 7)**
- `authorize()` before every tool execution (enabled, allowed, schema, scope, category × autonomy); decisions and executions are audited with the argument hash, never the arguments' secrets. Model output cannot change a decision.
- Approvals bind to one operation (tool + hash of exact args), expire, are single-use, and are re-checked together with the policy right before execution.
- Workspaces: relative paths only, no `..`, no symlinks on the path; file deletes and overwrites need approval.
- Sandbox: only the runner service holds the Docker socket; sandbox containers have no network, no root, no capabilities, a read-only root filesystem, CPU/RAM/pids/time limits, no Docker socket, no host environment, only their workspace. The runner accepts a single token-protected request type and has no app secrets.
- Package downloads (`terminal_run` with `network: "packages"`, 2026-11-02): **sensitive** (approval; never at the restricted level). The container joins the internal network `PACKAGES_NETWORK`; its only other member is `egress-packages`. That proxy allows only HTTPS `CONNECT` to `SANDBOX_PACKAGE_HOSTS` (npm + PyPI by default) at public addresses on port 443, and the TLS ClientHello must name the same host, so another site behind the registry's CDN address is cut off. There is no DNS on that network (checked: `getaddrinfo` fails), and a direct connection is unreachable. Nothing else about the container changes, and no token or secret ever enters it (GitHub goes through the server's `github_*` tools). It logs hosts and byte counts only. Residual risk: a malicious package runs its install script in the sandbox and can read the workspace. It can only talk to the registries, but a client that hides the real site inside TLS (Encrypted Client Hello, or a different `Host` inside the tunnel on a CDN that still allows domain fronting) is not visible to the proxy. That is why every such call needs the owner's approval.
- `web_fetch`: SSRF guard (public addresses only, pinned connection, per-hop redirect checks, port and size limits).
- GitHub token and MCP tokens are encrypted at rest and never returned to the browser; GitHub API host pinned.
- MCP tools start disabled; MCP and every other tool output is fenced as untrusted data.
- Residual risk: the runner's Docker socket is root-equivalent on the host — keep the runner minimal (it is), and never mount the socket anywhere else.

**Passkeys (owner request, 2026-11-02)** — sign in with Face ID / Touch ID (WebAuthn, `py_webauthn`):
- Off unless `WEBAUTHN_RP_ID` + `WEBAUTHN_ORIGINS` are set (the server's `*.ts.net` name; validated at startup: a domain, HTTPS origins on it). The password always keeps working.
- Only public data is stored (`webauthn_credentials`: credential id, COSE public key, sign count, transports); the private key never leaves the device or its password manager. User handle = the user's UUID bytes (no personal data).
- Adding one: signed-in session **and** the current password (same lockout as every password check), then a challenge bound to that session. Deleting one: the password again — a borrowed or stolen session can neither add a way in nor remove the owner's. Renaming: session only. At most `WEBAUTHN_MAX_CREDENTIALS`.
- Challenges: 64 random bytes, single-use (Valkey `GETDEL`), TTL `WEBAUTHN_CHALLENGE_TTL_SECONDS`, stored under a hash of the challenge (never the challenge itself) with their purpose and binding: the session (adding) or a hash of an `HttpOnly; Secure; SameSite=Strict` flow cookie scoped to `/api/v1/auth/passkeys/login` (signing in). Ephemeral by design — losing one only means asking again.
- Verification: origin in `WEBAUTHN_ORIGINS`, RP ID hash, user presence **and user verification** (biometrics/device PIN), signature, sign-count regression (cloned authenticators), user handle = the credential's owner, active account. Attestation `none` (privacy; Apple/Google passkeys don't attest).
- Signing in creates exactly the password login's session (same cookies, per-user lifetime, CSRF rotated), audited `auth.login` with `method: passkey` + our passkey row id. Every failure for a known passkey counts toward the owner's login lockout, and a locked account cannot be entered with a passkey either; unknown passkeys are audited under one shared key that locks nobody out. One error (`401 passkey_rejected`) for every reason.
- Never logged or audited: credential ids, public keys, challenges, client data, signatures, the flow cookie (tested).

## Security review (Sprint 8)

| Area (spec 20) | Status | Evidence |
|---|---|---|
| Auth: argon2id, HttpOnly/Secure/SameSite cookies, expiry, CSRF, all routes protected | ✅ | `tests/test_auth.py`, `tests/test_route_protection.py`, CSRF middleware tests |
| Secrets only on the backend, encrypted at rest, never logged or returned | ✅ | provider/GitHub/MCP tests assert the token never appears in responses or the audit log |
| Agent isolation: sandbox without network/root/caps, read-only, limits, no Docker socket | ✅ | `tests/test_sandbox_runner.py` against a real Docker daemon |
| Prompt injection: external content fenced as data; permissions checked independently of model output; sensitive ops need approval; agents cannot raise their own privileges | ✅ | `tests/test_tool_policy.py`, `tests/test_tools_engine.py`, memory/attachment fence tests |
| Audit log of runs, config changes, tool use, approvals, denials, file changes, integrations; owner can view it | ✅ | Settings → Audit log; `tests/test_tools_integrations.py::test_audit_log_api_pages_and_filters` |
| Network: PostgreSQL/Redis internal only, app on 127.0.0.1 behind Tailscale Serve, no Funnel | ✅ (owner verifies on the server) | compose networks; `docs/deployment.md` checks |
| Browser: CSP with nonces, no inline/eval scripts, framing denied, HSTS, nosniff, Referrer-Policy, COOP/CORP | ✅ | `e2e/tests/pwa.spec.ts` (also fails on any CSP violation in every E2E test) |
| Service worker never caches API/WS | ✅ | `apps/web/public/sw.js`, `pwa.spec.ts` (`no-store` API) |
| Backups: integrity checks, restore drill, owner-only files, off-disk warning | ✅ | `backup.sh`, `restore-check.sh`, `tests/test_storage.py`; manual end-to-end restore |
| Dependencies | ✅ | npm prod: 0 known vulnerabilities; Python runtime: 0 (`pip-audit`); dev-only ESLint findings accepted |

Residual risks (accepted, documented): the sandbox runner holds the Docker socket (root-equivalent; kept minimal); the home laptop is a single machine (power/disk loss → restore from off-disk backups); Web Push messages pass through Apple/Google/Mozilla/Microsoft push services — the payload (title, short text, link) is encrypted end to end (RFC 8291), the service sees only ciphertext, timing and size; subscriptions may only point to `PUSH_ALLOWED_HOSTS`.

## Open items

| Item | Planned |
|---|---|
| Content-Security-Policy with nonces | ✅ Sprint 8 |
| Permission system, approvals, sandbox isolation | ✅ Sprint 7 |
| UI for viewing the audit log | ✅ Sprint 7 (Settings → Audit log) |
| Expired-session cleanup job | Sprint 3 (worker) |
| Redis password | Not needed for sandbox containers (they have no network); revisit if anything new joins the internal network |
| Sandbox network egress (e.g. for `pip install`) | ✅ 2026-11-02: opt-in per command (`network: "packages"`, sensitive), only through the allow-listing proxy `egress-packages` (registries only, TLS name checked) |
| Automated backups off the primary disk | ✅ Sprint 8 (BACKUP_DIR must be set to another disk by the owner) |
| Web Push for notifications with the app closed | ✅ after Sprint 8 (owner approved; encrypted, allow-listed push hosts) |
| Agents' browser | Sensitive tool (approval); own container on an internal network; the egress proxy allows only public addresses on 80/443; no host secrets; screenshot in the workspace, page text fenced as untrusted |
| PDF export | Raw HTML in results escaped; printed with no network |
| Search by meaning | Texts of memories and files are sent to the owner's OpenAI-type provider for embeddings (toggle in Settings → Voice & search); agents search only their own scope, never chat files |
| Microphone (voice input) | ✅ `Permissions-Policy: microphone=(self)`; audio goes to the local `stt` service (internal network, no internet, nothing logged but timings) or, when it is off/not ready, only to the owner's OpenAI-type provider |
| Uploaded pictures/PDFs | ✅ type from the bytes, size/page limits, PDF parsed in a thread with a timeout, served with `nosniff` + sandbox CSP |
| Uploaded files of any type and size (2026-11-02) | ✅ streamed to disk (never whole in memory or the RAM-backed /tmp), name stripped to its last part, stored under a random id; free-disk guard; only text/picture/PDF detected from the bytes are served as such, everything else as `application/octet-stream` download; picture sizes read from headers (no decoding above `CHAT_IMAGE_MAX_PIXELS`), downscaling in a child process with a time and memory limit; file text is fenced as untrusted data |
| Official GitHub MCP server | ✅ after Sprint 8 (read-only by default, tools start disabled, token from Integrations → GitHub) |

## Reporting

This is a private, single-owner project. Report problems to the owner directly.
