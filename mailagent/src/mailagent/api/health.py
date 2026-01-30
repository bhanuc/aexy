"""Health check endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter

from mailagent import __version__
from mailagent.config import get_settings
from mailagent.database import check_db_connection
from mailagent.redis_client import check_redis_connection
from mailagent.schemas import HealthResponse

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Check service health."""
    settings = get_settings()

    db_healthy = await check_db_connection()
    redis_healthy = await check_redis_connection()

    status = "healthy" if (db_healthy and redis_healthy) else "degraded"

    return HealthResponse(
        status=status,
        service=settings.service_name,
        version=__version__,
        database=db_healthy,
        redis=redis_healthy,
        timestamp=datetime.now(timezone.utc),
    )


@router.get("/ready")
async def readiness_check() -> dict:
    """Kubernetes readiness probe."""
    db_healthy = await check_db_connection()
    redis_healthy = await check_redis_connection()

    if not db_healthy or not redis_healthy:
        return {"ready": False, "database": db_healthy, "redis": redis_healthy}

    return {"ready": True}


@router.get("/live")
async def liveness_check() -> dict:
    """Kubernetes liveness probe."""
    return {"alive": True}
