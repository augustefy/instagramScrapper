"""
GET /health — état de l'API et de ses dépendances.
"""

from fastapi import APIRouter, Depends, Request

from api.deps import get_redis
from api.schemas import HealthResponse

router = APIRouter(tags=["ops"])


@router.get("/health", response_model=HealthResponse, summary="Health check")
async def health(request: Request, redis=Depends(get_redis)) -> HealthResponse:
    checks: dict[str, str] = {"api": "ok"}

    try:
        redis.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "error"

    status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return HealthResponse(status=status, checks=checks)
