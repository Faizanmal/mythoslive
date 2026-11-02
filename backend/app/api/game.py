import asyncio
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect

from app.contracts.events import EngineRealtimeSnapshot
from app.engine.service import GameEngineService

router = APIRouter(prefix="/api/game", tags=["game"])


@router.get("/state", response_model=EngineRealtimeSnapshot)
async def game_state(world_id: UUID, request: Request) -> EngineRealtimeSnapshot:
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


@router.get("/events")
async def game_events(
    request: Request,
    after: int = Query(default=0, ge=0),
    world_id: UUID | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict[str, object]:
    engine: GameEngineService = request.app.state.engine
    events = engine.events_since(after, world_id)
    if len(events) > limit:
        events = events[-limit:]
    oldest = engine.events_since(0, world_id)
    return {
        "sequence": engine.sequence,
        "oldest_sequence": oldest[0][0] if oldest else engine.sequence,
        "gap": bool(oldest and after and after < oldest[0][0] - 1),
        "events": [event.model_dump(mode="json") for _, event in events],
    }


@router.websocket("/ws/{world_id}")
async def game_events_websocket(websocket: WebSocket, world_id: UUID) -> None:
    engine: GameEngineService = websocket.app.state.engine
    await websocket.accept()
    try:
        snapshot, sequence = await engine.public_snapshot_bundle(world_id)
        if snapshot is None:
            await websocket.send_json(
                {
                    "schema_version": 1,
                    "message_type": "connection.status",
                    "status": "disconnected",
                    "detail": "No session for world.",
                }
            )
            await websocket.close(code=4404)
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
        while True:
            await asyncio.sleep(0.25)
            events = engine.events_since(cursor, world_id)
            if events and events[0][0] > cursor + 1:
                fresh, fresh_sequence = await engine.public_snapshot_bundle(world_id)
                if fresh:
                    await websocket.send_json(
                        EngineRealtimeSnapshot(
                            session_id=fresh["session_id"],
                            world_id=fresh["world_id"],
                            revision=fresh["revision"],
                            sequence=fresh_sequence,
                            state=fresh,
                        ).model_dump(mode="json")
                    )
                cursor = events[0][0] - 1
            for sequence, event in events:
                await websocket.send_json(event.model_dump(mode="json"))
                cursor = sequence
    except WebSocketDisconnect:
        return
