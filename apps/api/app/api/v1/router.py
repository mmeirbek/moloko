"""API v1 routing.

Every new module router goes into ``protected`` — it requires a valid session for
every route. Only the explicit allow-list in ``public`` is reachable anonymously;
``tests/test_route_protection.py`` fails if anything else is.

Never set ``include_in_schema=False`` on a route: that test discovers routes
through the OpenAPI schema, so a hidden route would escape the check.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import require_auth
from app.api.v1 import (
    agents,
    ai_services,
    auth,
    chats,
    costs,
    events,
    health,
    memories,
    providers,
    push,
    runs,
    system,
    tasks,
    tooling,
)

public = APIRouter()
public.include_router(health.router)
public.include_router(auth.public_router)

protected = APIRouter(dependencies=[Depends(require_auth)])
protected.include_router(auth.protected_router)
protected.include_router(providers.router)
protected.include_router(chats.router)
protected.include_router(agents.router)
protected.include_router(tasks.router)
protected.include_router(events.router)
protected.include_router(system.router)
protected.include_router(runs.router)
protected.include_router(memories.router)
protected.include_router(push.router)
protected.include_router(costs.router)
protected.include_router(ai_services.router)
protected.include_router(tooling.tools_router)
protected.include_router(tooling.approvals_router)
protected.include_router(tooling.integrations_router)
protected.include_router(tooling.mcp_router)
protected.include_router(tooling.workspaces_router)
protected.include_router(tooling.audit_router)
protected.include_router(tooling.task_tools_router)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(public)
api_router.include_router(protected)

# Paths (method, path) that may be called without a session.
PUBLIC_ROUTES = frozenset(
    {
        ("GET", "/api/v1/health"),
        ("GET", "/api/v1/health/live"),
        ("GET", "/api/v1/auth/csrf"),
        ("POST", "/api/v1/auth/login"),
        ("POST", "/api/v1/auth/logout"),
    }
)
