from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.settings import get_settings
from app.repositories.health import HealthRepository
from app.services.readiness import ReadinessService

router = APIRouter()


@router.get("/healthz", tags=["health"])
async def healthz(request: Request) -> dict[str, str]:
    return {
        "status": "ok",
        "version": request.app.version,
        "build": get_settings().build_version,
    }


@router.get("/readyz", tags=["health"])
async def readyz(request: Request) -> dict[str, str]:
    engine: AsyncEngine = request.app.state.db_engine
    service = ReadinessService(HealthRepository(engine))
    if not await service.is_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="database not ready"
        )
    return {
        "status": "ready",
        "database": "ok",
        "version": request.app.version,
        "build": get_settings().build_version,
    }
