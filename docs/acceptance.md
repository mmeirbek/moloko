# Acceptance checklist (spec 25.3)

✅ = verified automatically in this repository (tests named). 👤 = needs the owner's real
server/devices; the steps are in `docs/deployment.md`. Status as of 2026-11-01.

## Infrastructure
| Item | Status | Evidence / how to verify |
|---|---|---|
| Ubuntu server runs the app stably; all services via Docker Compose | ✅ compose stack (8 services, health checks, restart policies) runs and passes all E2E · 👤 on the MateBook | `docker compose ps` — all `healthy` |
| Reachable via Tailscale from MacBook, Huawei, phone | 👤 | `tailscale serve --bg 8080`, open `https://moloko.<tailnet>.ts.net` on each device |
| PostgreSQL and Redis not reachable from the internet | ✅ internal Docker network, no published ports · 👤 confirm | `sudo ss -ltnp \| grep -E ':5432\|:6379'` prints nothing |

## Chat
| Item | Status | Evidence |
|---|---|---|
| Create conversations; history persists; streaming; model selectable; provider errors handled | ✅ | `e2e/tests/chat.spec.ts`; `tests/test_chat_api.py`, `test_chat_stream.py`, `test_providers*.py` |
| Real provider with an official API key | 👤 | Settings → AI providers: add your OpenAI/Anthropic key, «Проверить» |

## Agents
| Item | Status | Evidence |
|---|---|---|
| Create/edit agents; assign models; run tasks; statuses; pause/cancel; state restored after restart | ✅ | `e2e/tests/agents.spec.ts`, `recovery.spec.ts`; `tests/test_engine.py`, `test_tasks_agents_api.py` |

## Subagents
| Item | Status | Evidence |
|---|---|---|
| Orchestrator decomposes; creates subagents; passes context; merges results; respects concurrency/depth limits | ✅ | `e2e/tests/orchestrator.spec.ts`; `tests/test_orchestrator.py` (peak active subagents = limit, depth limit) |

## Pixel Office
| Item | Status | Evidence |
|---|---|---|
| Real agents; statuses synced; profile opens; current task visible; live updates | ✅ | `e2e/tests/office.spec.ts` (status after reload, inspector, pause freezes the character, subagents come and go) |

## Security
| Item | Status | Evidence |
|---|---|---|
| API keys never reach the frontend | ✅ | provider/GitHub/MCP API tests assert only hints are returned |
| Agents run in restricted environments | ✅ | `tests/test_sandbox_runner.py` (real Docker: no network/root/caps, read-only, limits) |
| Permissions checked on the backend | ✅ | `tests/test_tool_policy.py`, `test_tools_engine.py` |
| Sensitive actions need approval | ✅ | `tests/test_tools_engine.py`, `e2e/tests/tools.spec.ts` |
| Audit log exists | ✅ | Settings → Audit log; `tests/test_tools_integrations.py` |

## Multi-device
| Item | Status | Evidence |
|---|---|---|
| Start on one device, open another, see current status, get the result without re-running | ✅ | `e2e/tests/chat.spec.ts` (phone joins a running answer), Sprint 3/4 E2E (task started on the laptop finished and visible on the phone) · 👤 on your devices |

## Performance targets
| Item | Status | Evidence |
|---|---|---|
| Main page ≤ 3 s; saved chat ≤ 2 s; realtime ≤ 1 s; no full reloads; ≤ 5 subagents; ≥ 3 devices | ✅ (local network) · 👤 over Tailscale | `e2e/tests/performance.spec.ts`, `docs/performance.md` |

## Backups (spec 21.3)
| Item | Status | Evidence |
|---|---|---|
| Automatic daily DB + file backups, integrity checks, rotation, tested restore | ✅ | `infrastructure/backup/*`, `tests/test_storage.py`; manual end-to-end restore test |
| Stored off the primary disk | 👤 | set `BACKUP_DIR` to an external disk; Settings → Backups must not warn «тот же диск» |
