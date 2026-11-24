"""Health endpoints: no auth, no tenant (system_design §2, api_spec §1)."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.modules.health import service
from app.modules.health.schemas import LiveResponse, ReadyResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=LiveResponse)
async def live() -> LiveResponse:
    """Liveness: 200 while the process is up. Checks nothing (Docker healthcheck)."""
    return LiveResponse()


@router.get(
    "/ready",
    response_model=ReadyResponse,
    responses={503: {"model": ReadyResponse, "description": "A dependency is down"}},
)
async def ready(request: Request) -> JSONResponse:
    """Readiness: Postgres, Redis and the storage bucket. 200 if all ok, else 503."""
    report = await service.readiness(request.app.state.redis, request.app.state.settings)
    return JSONResponse(report.model_dump(), status_code=200 if report.status == "ok" else 503)
