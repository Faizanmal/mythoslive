from fastapi import APIRouter, Depends, HTTPException, Request

from app.contracts.events import SimChatRequest, SimSocialRequest, SimStatus
from app.core.settings import Settings
from app.services.dashboard_auth import (
    DashboardPrincipal,
    require_dashboard,
    require_dashboard_mutation,
)
from app.services.simulator import SimulatorService

router = APIRouter(prefix="/api/sim", tags=["simulator"])


def _check_origin(request: Request) -> None:
    settings: Settings = request.app.state.settings
    if request.headers.get("origin") not in settings.cors_origins:
        raise HTTPException(status_code=403, detail="Request origin is not allowed.")


@router.get("/status", response_model=SimStatus)
async def simulator_status(
    request: Request, _principal: DashboardPrincipal = Depends(require_dashboard)
) -> SimStatus:
    return SimStatus.model_validate(request.app.state.simulator.status())


@router.post("/start", response_model=SimStatus)
async def simulator_start(
    request: Request, principal: DashboardPrincipal = Depends(require_dashboard_mutation)
) -> SimStatus:
    if not principal.simulator:
        raise HTTPException(status_code=403, detail="Simulator controls require simulator mode.")
    simulator: SimulatorService = request.app.state.simulator
    await simulator.start()
    return SimStatus.model_validate(simulator.status())


@router.post("/stop", response_model=SimStatus)
async def simulator_stop(
    request: Request, principal: DashboardPrincipal = Depends(require_dashboard_mutation)
) -> SimStatus:
    if not principal.simulator:
        raise HTTPException(status_code=403, detail="Simulator controls require simulator mode.")
    simulator: SimulatorService = request.app.state.simulator
    await simulator.stop()
    return SimStatus.model_validate(simulator.status())


@router.post("/chat", response_model=SimStatus)
async def simulator_chat(
    body: SimChatRequest,
    request: Request,
    principal: DashboardPrincipal = Depends(require_dashboard_mutation),
) -> SimStatus:
    if not principal.simulator:
        raise HTTPException(status_code=403, detail="Simulator chat requires simulator mode.")
    request.app.state.simulator.submit(body.persona_name, body.message)
    return SimStatus.model_validate(request.app.state.simulator.status())


@router.post("/social", response_model=SimStatus)
async def simulator_social(
    body: SimSocialRequest,
    request: Request,
    principal: DashboardPrincipal = Depends(require_dashboard_mutation),
) -> SimStatus:
    if not principal.simulator:
        raise HTTPException(status_code=403, detail="Social event fixtures require simulator mode.")
    request.app.state.simulator.submit_social(body.event_type, body.name, body.viewers)
    return SimStatus.model_validate(request.app.state.simulator.status())
