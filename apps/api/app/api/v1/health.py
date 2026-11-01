from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.schemas.health import HealthResponse, LivenessResponse
from app.services.health import check_health

router = APIRouter(prefix="/health", tags=["health"])


@router.get(
    "",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse}},
    summary="Readiness: API, PostgreSQL and Redis",
)
async def health(request: Request) -> JSONResponse:
    state = request.app.state
    result = await check_health(state.db, state.redis, state.version)
    return JSONResponse(result.model_dump(), status_code=200 if result.status == "ok" else 503)


@router.get("/live", response_model=LivenessResponse, summary="Liveness: the process is up")
async def live() -> LivenessResponse:
    return LivenessResponse(status="ok")
