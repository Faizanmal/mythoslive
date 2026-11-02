import asyncio
import secrets
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, update

from app.contracts.events import EngineRealtimeSnapshot
from app.engine.service import GameEngineService
from app.models.entities import OverlayAccessKey, World
from app.services.dashboard_auth import DashboardPrincipal, require_dashboard_mutation

router = APIRouter(prefix="/api/overlay", tags=["overlay"])
public_router = APIRouter(tags=["overlay"])


class OverlayKeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    world_id: UUID | None = None


class OverlayKeyResponse(BaseModel):
    key: str
    world_id: UUID


async def _world_for_key(request: Request, raw_key: str) -> UUID | None:
    if not raw_key or len(raw_key) > 128:
        return None
    digest = sha256(raw_key.encode("utf-8")).hexdigest()
    async with request.app.state.db_sessions() as db:
        row = await db.scalar(
            select(OverlayAccessKey).where(
                OverlayAccessKey.token_hash == digest, OverlayAccessKey.revoked_at.is_(None)
            )
        )
        return row.world_id if row else None


@router.post("/key", response_model=OverlayKeyResponse)
async def create_overlay_key(
    body: OverlayKeyRequest,
    request: Request,
    principal: DashboardPrincipal = Depends(require_dashboard_mutation),
) -> OverlayKeyResponse:
    """Rotate a world-scoped read-only key; the plaintext is returned only once."""
    world_id = UUID(principal.world_id)
    if body.world_id is not None and body.world_id != world_id:
        raise HTTPException(status_code=403, detail="That world is not owned by this account.")
    raw_key = secrets.token_urlsafe(32)
    digest = sha256(raw_key.encode("utf-8")).hexdigest()
    async with request.app.state.db_sessions.begin() as db:
        world = await db.scalar(select(World).where(World.id == world_id).with_for_update())
        if world is None:
            raise HTTPException(status_code=404, detail="World not found.")
        await db.execute(
            update(OverlayAccessKey)
            .where(
                OverlayAccessKey.world_id == world_id,
                OverlayAccessKey.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        db.add(OverlayAccessKey(world_id=world_id, token_hash=digest))
    return OverlayKeyResponse(key=raw_key, world_id=world_id)


@router.delete("/key")
async def revoke_overlay_key(
    request: Request,
    world_id: UUID | None = None,
    principal: DashboardPrincipal = Depends(require_dashboard_mutation),
) -> dict[str, int]:
    owned_world_id = UUID(principal.world_id)
    if world_id is not None and world_id != owned_world_id:
        raise HTTPException(status_code=403, detail="That world is not owned by this account.")
    async with request.app.state.db_sessions.begin() as db:
        result = await db.execute(
            update(OverlayAccessKey)
            .where(
                OverlayAccessKey.world_id == owned_world_id,
                OverlayAccessKey.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        return {"revoked": result.rowcount or 0}


@router.get("/snapshot", response_model=EngineRealtimeSnapshot)
async def overlay_snapshot(key: str, request: Request) -> EngineRealtimeSnapshot:
    world_id = await _world_for_key(request, key)
    if world_id is None:
        raise HTTPException(status_code=403, detail="Overlay key is invalid or revoked.")
    engine: GameEngineService = request.app.state.engine
    snapshot, sequence = await engine.public_snapshot_bundle(world_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="No session exists for this world.")
    return EngineRealtimeSnapshot(
        session_id=snapshot["session_id"],
        world_id=snapshot["world_id"],
        revision=snapshot["revision"],
        sequence=sequence,
        state=snapshot,
    )


@router.websocket("/ws")
@public_router.websocket("/ws/overlay")
async def overlay_websocket(websocket: WebSocket, key: str = Query()) -> None:
    world_id = await _world_for_key(websocket, key)
    if world_id is None:
        await websocket.close(code=4403, reason="Invalid or revoked overlay key")
        return
    engine: GameEngineService = websocket.app.state.engine
    await websocket.accept()
    try:
        cursor = -1
        checked_key_at = 0.0
        while True:
            now = asyncio.get_running_loop().time()
            if now - checked_key_at >= 5:
                if await _world_for_key(websocket, key) != world_id:
                    await websocket.close(code=4403, reason="Overlay key was revoked")
                    return
                checked_key_at = now
            oldest = engine.events_since(0)
            if cursor == -1 or (oldest and cursor < oldest[0][0] - 1):
                snapshot, sequence = await engine.public_snapshot_bundle(world_id)
                if snapshot is None:
                    await websocket.close(code=4404, reason="No session exists for this world")
                    return
                await websocket.send_json(
                    EngineRealtimeSnapshot(
                        session_id=snapshot["session_id"],
                        world_id=snapshot["world_id"],
                        revision=snapshot["revision"],
                        sequence=sequence,
                        state=snapshot,
                    ).model_dump(mode="json")
                )
                cursor = sequence
            events = engine.events_since(cursor, world_id)
            for sequence, event in events:
                if sequence > cursor:
                    await websocket.send_json(event.model_dump(mode="json"))
                    cursor = sequence
            await asyncio.sleep(0.2)
    except WebSocketDisconnect:
        return
