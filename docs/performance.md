# Performance (spec 25.3)

Measured by `e2e/tests/performance.spec.ts` (runs in the E2E suite), on the server's own
network — a lower bound; over Tailscale add the network round trip (usually tens of ms).

| Target (spec 25.3) | Limit | Measured (2026-11-01) |
|---|---|---|
| Main page (cold browser, incl. JS) | ≤ 3 s | 1.65 s |
| Open a saved chat | ≤ 2 s | 0.69 s |
| Realtime event shown (REST change → WebSocket → UI) | ≤ 1 s | 0.29 s |
| Switch sections (no full reload) | — | 0.49 s |
| Concurrent subagents | ≤ 5 | limit enforced in code (`MAX_ACTIVE_SUBAGENTS_PER_RUN`), tested |
| Concurrent devices | ≥ 3 | independent sessions + WebSocket per device; tested with 2 in E2E, no shared per-device state on the server |

Notes: static assets are hashed and cached immutably; Caddy compresses text (not
`text/event-stream`, so chat tokens are not buffered); the service worker serves the app
shell from cache; API responses are `no-store`. AI answer time depends on the provider.
