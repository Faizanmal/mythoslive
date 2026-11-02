from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.ai.master import AIGameMaster
from app.core.settings import Settings
from app.services.dashboard_auth import (
    DashboardPrincipal,
    require_dashboard,
    require_dashboard_mutation,
)

router = APIRouter(prefix="/api/ai", tags=["ai"])


class AISettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tone: Literal["heroic", "grimdark", "comedic"] | None = None
    family_friendly: bool | None = None
    banned_topics: list[str] | None = Field(default=None, max_length=30)
    approval_mode: Literal["required", "auto_safe"] | None = None


def _check_origin(request: Request) -> None:
    settings: Settings = request.app.state.settings
    if request.headers.get("origin") not in settings.cors_origins:
        raise HTTPException(status_code=403, detail="Request origin is not allowed.")


@router.get("/status")
async def ai_status(
    request: Request, _principal: DashboardPrincipal = Depends(require_dashboard)
) -> dict[str, object]:
    status = request.app.state.ai_master.status()
    quill = getattr(request.app.state, "quill", None)
    if quill is not None:
        status["quill"] = quill.status()
    return status


@router.patch("/settings")
async def update_ai_settings(
    body: AISettingsPatch,
    request: Request,
    _principal: DashboardPrincipal = Depends(require_dashboard_mutation),
) -> dict[str, object]:
    settings: AIGameMaster = request.app.state.ai_master
    values = body.model_dump(exclude_unset=True)
    if "banned_topics" in values and values["banned_topics"] is not None:
        if any(not item.strip() or len(item) > 80 for item in values["banned_topics"]):
            raise HTTPException(status_code=422, detail="Banned topics must be 1–80 characters.")
    settings.update_settings(**values)
    return settings.status()


@router.get("/pending")
async def list_pending_ai_events(
    request: Request,
    world_id: UUID | None = Query(default=None),  # noqa: B008 - FastAPI dependency metadata
    limit: int = Query(50, ge=1, le=100),
    principal: DashboardPrincipal = Depends(require_dashboard),
) -> list[dict[str, object]]:
    target = UUID(principal.world_id)
    if world_id is not None and world_id != target:
        raise HTTPException(status_code=403, detail="That world is not owned by this account.")
    rows = await request.app.state.dashboard_repository.list_proposals(target, limit)
    return [
        {
            "id": str(row.id),
            "world_id": str(row.world_id),
            "payload": row.payload,
            "created_at": row.created_at.isoformat(),
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "default_decision": "veto on expiry; world remains unchanged",
        }
        for row in rows
    ]


@router.post("/pending/{pending_id}/approve")
async def approve_ai_event(
    pending_id: UUID,
    request: Request,
    principal: DashboardPrincipal = Depends(require_dashboard_mutation),
) -> dict[str, str]:
    result = await request.app.state.dashboard_repository.decide_proposal(
        UUID(principal.world_id), pending_id, principal.broadcaster_id, approve=True
    )
    if result is None:
        raise HTTPException(
            status_code=404, detail="Pending world event was not found or already reviewed."
        )
    return {"status": result}


@router.post("/pending/{pending_id}/reject")
async def reject_ai_event(
    pending_id: UUID,
    request: Request,
    principal: DashboardPrincipal = Depends(require_dashboard_mutation),
) -> dict[str, str]:
    result = await request.app.state.dashboard_repository.decide_proposal(
        UUID(principal.world_id), pending_id, principal.broadcaster_id, approve=False
    )
    if result is None:
        raise HTTPException(
            status_code=404, detail="Pending world event was not found or already reviewed."
        )
    return {"status": result}
