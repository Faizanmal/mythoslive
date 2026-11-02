import asyncio
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.ai.master import AIGameMaster
from app.contracts.events import EngineRealtimeSnapshot
from app.core.settings import Settings
from app.engine.service import GameEngineService
from app.models.entities import OAuthToken
from app.repositories.dashboard import DashboardRepository
from app.services.dashboard_auth import (
    DashboardPrincipal,
    require_dashboard,
    require_dashboard_mutation,
)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


class SessionControl(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["start", "pause", "resume", "end"]


class DashboardConfigPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    director_notes: str | None = Field(default=None, max_length=1_000)
    tone: Literal["heroic", "grimdark", "comedic"] | None = None
    family_friendly: bool | None = None
    banned_topics: list[str] | None = Field(default=None, max_length=30)
    approval_mode: Literal["required", "auto_safe"] | None = None
    difficulty: Literal["easy", "normal", "hard"] | None = None
    duration_minutes: Literal[15, 30, 60, 90] | None = None
    vote_window_seconds: int | None = Field(default=None, ge=10, le=60)
    command_cooldown_seconds: float | None = Field(default=None, ge=0.5, le=30)
    bot_messages_per_30_seconds: int | None = Field(default=None, ge=1, le=20)


class ProposalEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str = Field(min_length=1, max_length=200)
    flag_id: Literal[
        "lantern_festival",
        "market_open",
        "village_trusts_party",
        "ashfall_cleared",
        "river_crossed",
    ]


class ViewerModeration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    viewer_id: UUID
    action: Literal["mute", "unmute", "kick"]


def _repository(request: Request) -> DashboardRepository:
    return request.app.state.dashboard_repository


def _owned(principal: DashboardPrincipal, world_id: UUID | None) -> UUID:
    if world_id and str(world_id) != principal.world_id:
        raise HTTPException(status_code=403, detail="That world is not owned by this account.")
    return UUID(principal.world_id)


@router.get("/auth-options")
async def auth_options(request: Request) -> dict[str, bool]:
    settings: Settings = request.app.state.settings
    return {
        "simulator_available": settings.environment == "development",
        "twitch_configured": bool(settings.twitch_client_id and settings.twitch_client_secret),
    }


@router.post("/dev-session")
async def simulator_dashboard_login(request: Request) -> JSONResponse:
    settings: Settings = request.app.state.settings
    origin = request.headers.get("origin")
    if (
        settings.environment != "development"
        or request.url.hostname not in {"localhost", "127.0.0.1"}
        or origin not in settings.cors_origins
    ):
        raise HTTPException(status_code=404, detail="Simulator dashboard login is unavailable.")
    response = JSONResponse({"status": "signed_in", "mode": "simulator"})
    request.app.state.dashboard_auth.set_cookies(response, "local-simulator")
    return response


@router.get("/auth")
async def dashboard_auth_status(
    request: Request, principal: DashboardPrincipal = Depends(require_dashboard)
) -> dict[str, Any]:
    return {
        "authenticated": True,
        "broadcaster_id": principal.broadcaster_id,
        "world_id": principal.world_id,
        "mode": "simulator" if principal.simulator else "twitch",
        "csrf_cookie": "mythos_dashboard_csrf",
    }


@router.post("/signout")
async def dashboard_signout(
    request: Request, _principal: DashboardPrincipal = Depends(require_dashboard_mutation)
) -> JSONResponse:
    response = JSONResponse({"status": "signed_out"})
    request.app.state.dashboard_auth.clear_cookies(response)
    return response


@router.get("/session")
async def session_snapshot(
    request: Request, principal: DashboardPrincipal = Depends(require_dashboard)
) -> EngineRealtimeSnapshot | dict[str, Any]:
    world_id = UUID(principal.world_id)
    engine: GameEngineService = request.app.state.engine
    snapshot, sequence = await engine.public_snapshot_bundle(world_id)
    if snapshot is None:
        return {"world_id": str(world_id), "state": "NO_SESSION", "snapshot": None}
    return EngineRealtimeSnapshot(
        session_id=snapshot["session_id"],
        world_id=world_id,
        revision=snapshot["revision"],
        sequence=sequence,
        state=snapshot,
    )


@router.post("/session/control")
async def control_session(
    body: SessionControl,
    request: Request,
    principal: DashboardPrincipal = Depends(require_dashboard_mutation),
) -> dict[str, Any]:
    repo = _repository(request)
    world_id = UUID(principal.world_id)
    config = await repo.config(world_id)
    settings = config["settings"]
    engine: GameEngineService = request.app.state.engine
    try:
        state = await engine.dashboard_control(
            world_id,
            body.action,
            principal.broadcaster_id,
            session_config={
                "difficulty": settings["difficulty"],
                "duration_minutes": settings["duration_minutes"],
                "vote_window_seconds": settings["vote_window_seconds"],
            },
        )
    except LookupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await repo.audit(
        world_id,
        principal.broadcaster_id,
        "session.panic_pause" if body.action == "pause" else f"session.{body.action}",
        {"session_id": str(state.session_id), "state": state.state.value},
    )
    snapshot, sequence = await engine.public_snapshot_bundle(world_id)
    return {
        "state": state.state.value,
        "session_id": str(state.session_id),
        "snapshot": snapshot,
        "sequence": sequence,
    }


@router.get("/overview")
async def dashboard_overview(
    request: Request, principal: DashboardPrincipal = Depends(require_dashboard)
) -> dict[str, Any]:
    world_id = UUID(principal.world_id)
    engine: GameEngineService = request.app.state.engine
    state = await engine.get_state(world_id)
    ai: AIGameMaster = request.app.state.ai_master
    eventsub = request.app.state.eventsub.status
    outbox = request.app.state.chat_outbox
    ingress = request.app.state.event_recorder.metrics
    return {
        "mode": "simulator" if principal.simulator else "twitch",
        "world_id": str(world_id),
        "session_state": state.state.value if state else "NO_SESSION",
        "snapshot": await engine.public_snapshot(world_id),
        "sequence": engine.sequence,
        "connected_websocket_clients": engine.connected_clients,
        "llm": ai.status(),
        "eventsub": eventsub,
        "chat": {
            "accepted": ingress.accepted,
            "rejected": ingress.rejected,
            "messages_per_minute": round(
                ingress.accepted
                / max(
                    1,
                    (
                        datetime.now(UTC)
                        - getattr(request.app.state, "booted_at", datetime.now(UTC))
                    ).total_seconds()
                    / 60,
                ),
                1,
            ),
            "outbox_pending": outbox.pending,
            "outbox_sent": outbox.sent,
            "outbox_dropped": outbox.dropped,
        },
        "simulator": request.app.state.simulator.status(),
    }


@router.get("/events")
async def dashboard_events(
    request: Request,
    after: int = 0,
    principal: DashboardPrincipal = Depends(require_dashboard),
) -> dict[str, Any]:
    engine: GameEngineService = request.app.state.engine
    world_id = UUID(principal.world_id)
    entries = engine.events_since(after, world_id)[-200:]
    return {
        "sequence": engine.sequence,
        "events": [event.model_dump(mode="json") for _, event in entries],
    }


@router.get("/chat")
async def dashboard_chat(
    request: Request,
    after: int = 0,
    _principal: DashboardPrincipal = Depends(require_dashboard),
) -> dict[str, Any]:
    recorder = request.app.state.event_recorder
    rows = recorder.since(after)[-100:]
    return {
        "sequence": recorder.sequence,
        "events": [
            {
                "sequence": sequence,
                "event_id": str(event.event_id),
                "event_type": event.event_type,
                "source": event.source,
                "simulated": event.source == "simulator",
                "display_name": event.actor.display_name if event.actor else "System",
                "command": event.payload.get("command"),
                "arguments": event.payload.get("arguments"),
                "occurred_at": event.occurred_at.isoformat(),
            }
            for sequence, event in rows
            if event.event_type.startswith("chat.command.")
        ],
    }


@router.websocket("/ws")
async def dashboard_realtime(websocket: WebSocket) -> None:
    if websocket.headers.get("origin") not in websocket.app.state.settings.cors_origins:
        await websocket.close(code=4403, reason="Dashboard websocket origin is not allowed")
        return
    try:
        principal = await websocket.app.state.dashboard_auth.authenticate(websocket)
    except HTTPException:
        await websocket.close(code=4401, reason="Broadcaster sign-in required")
        return
    engine: GameEngineService = websocket.app.state.engine
    world_id = UUID(principal.world_id)
    await websocket.accept()
    engine.connected_clients += 1
    try:
        snapshot, cursor = await engine.public_snapshot_bundle(world_id)
        if snapshot:
            await websocket.send_json(
                EngineRealtimeSnapshot(
                    session_id=snapshot["session_id"],
                    world_id=world_id,
                    revision=snapshot["revision"],
                    sequence=cursor,
                    state=snapshot,
                ).model_dump(mode="json")
            )
        while True:
            events = engine.events_since(cursor, world_id)
            oldest = engine.events_since(0, world_id)
            if events and oldest and cursor and cursor < oldest[0][0] - 1:
                fresh, fresh_cursor = await engine.public_snapshot_bundle(world_id)
                if fresh:
                    await websocket.send_json(
                        EngineRealtimeSnapshot(
                            session_id=fresh["session_id"],
                            world_id=world_id,
                            revision=fresh["revision"],
                            sequence=fresh_cursor,
                            state=fresh,
                        ).model_dump(mode="json")
                    )
                cursor = fresh_cursor
                continue
            for sequence, event in events:
                if sequence > cursor:
                    await websocket.send_json(event.model_dump(mode="json"))
                    cursor = sequence
            await asyncio.sleep(0.25)
    except WebSocketDisconnect:
        pass
    finally:
        engine.connected_clients = max(0, engine.connected_clients - 1)


@router.get("/config")
async def get_dashboard_config(
    request: Request, principal: DashboardPrincipal = Depends(require_dashboard)
) -> dict[str, Any]:
    return await _repository(request).config(UUID(principal.world_id))


@router.patch("/config")
async def update_dashboard_config(
    body: DashboardConfigPatch,
    request: Request,
    principal: DashboardPrincipal = Depends(require_dashboard_mutation),
) -> dict[str, Any]:
    values = body.model_dump(exclude_unset=True)
    notes = values.pop("director_notes", None)
    banned = values.get("banned_topics")
    if banned is not None and any(not item.strip() or len(item) > 80 for item in banned):
        raise HTTPException(status_code=422, detail="Banned topics must be 1–80 characters.")
    config = await _repository(request).save_config(
        UUID(principal.world_id),
        principal.broadcaster_id,
        director_notes=notes,
        settings=values,
    )
    ai: AIGameMaster = request.app.state.ai_master
    ai.update_settings(
        tone=values.get("tone"),
        family_friendly=values.get("family_friendly"),
        banned_topics=values.get("banned_topics"),
        approval_mode=values.get("approval_mode"),
    )
    settings: Settings = request.app.state.settings
    if "command_cooldown_seconds" in values:
        settings.command_user_cooldown_seconds = values["command_cooldown_seconds"]
    if "bot_messages_per_30_seconds" in values:
        settings.chat_global_messages_per_30_seconds = values["bot_messages_per_30_seconds"]
        request.app.state.chat_outbox._limiter.max_per_window = values[
            "bot_messages_per_30_seconds"
        ]
    return config


@router.get("/proposals")
async def proposals(
    request: Request, principal: DashboardPrincipal = Depends(require_dashboard)
) -> list[dict[str, Any]]:
    rows = await _repository(request).list_proposals(UUID(principal.world_id))
    now = datetime.now(UTC)
    return [
        {
            "id": str(row.id),
            "payload": row.payload,
            "status": row.status,
            "created_at": row.created_at.isoformat(),
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "seconds_remaining": max(0, int((row.expires_at - now).total_seconds()))
            if row.expires_at and row.status == "pending"
            else 0,
            "default_decision": "veto on expiry; world remains unchanged",
        }
        for row in rows
    ]


@router.patch("/proposals/{pending_id}")
async def edit_proposal(
    pending_id: UUID,
    body: ProposalEdit,
    request: Request,
    principal: DashboardPrincipal = Depends(require_dashboard_mutation),
) -> dict[str, bool]:
    result = await _repository(request).edit_proposal(
        UUID(principal.world_id),
        pending_id,
        principal.broadcaster_id,
        description=body.description,
        flag_id=body.flag_id,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Pending proposal not found or expired.")
    return {"edited": True}


@router.post("/proposals/{pending_id}/decision")
async def decide_proposal(
    pending_id: UUID,
    body: dict[str, Any],
    request: Request,
    principal: DashboardPrincipal = Depends(require_dashboard_mutation),
) -> dict[str, str]:
    if set(body) != {"approve"} or not isinstance(body["approve"], bool):
        raise HTTPException(status_code=422, detail="Expected an approve boolean.")
    result = await _repository(request).decide_proposal(
        UUID(principal.world_id), pending_id, principal.broadcaster_id, approve=body["approve"]
    )
    if result is None:
        raise HTTPException(
            status_code=404, detail="Pending proposal not found or already decided."
        )
    if result == "applied":
        await request.app.state.engine.publish_ai_presentation(
            UUID(principal.world_id),
            "toast",
            {"text": "A new chapter enters Emberfall's canon, approved by the keeper."},
        )
    return {"status": result}


@router.get("/codex")
async def world_codex(
    request: Request, principal: DashboardPrincipal = Depends(require_dashboard)
) -> dict[str, Any]:
    return await _repository(request).world_codex(UUID(principal.world_id))


@router.delete("/memories/{memory_id}")
async def delete_memory(
    memory_id: UUID,
    request: Request,
    principal: DashboardPrincipal = Depends(require_dashboard_mutation),
) -> dict[str, bool]:
    result = await _repository(request).delete_memory(
        UUID(principal.world_id), memory_id, principal.broadcaster_id
    )
    if not result:
        raise HTTPException(status_code=404, detail="Memory was not found in this world.")
    return {"deleted": True}


@router.post("/viewers/moderate")
async def moderate_viewer(
    body: ViewerModeration,
    request: Request,
    principal: DashboardPrincipal = Depends(require_dashboard_mutation),
) -> dict[str, str]:
    kick = body.action == "kick"
    result = await _repository(request).set_viewer_mute(
        UUID(principal.world_id),
        body.viewer_id,
        principal.broadcaster_id,
        muted=body.action != "unmute",
        kick=kick,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Viewer not found in this world.")
    twitch_id, identity_key = result
    if kick:
        await request.app.state.engine.remove_viewer(
            UUID(principal.world_id), identity_key, "A wayfarer"
        )
    if body.action == "unmute":
        request.app.state.ingress.muted_twitch_ids.discard(twitch_id)
    else:
        request.app.state.ingress.muted_twitch_ids.add(twitch_id)
    return {"status": "kicked" if kick else body.action + "d"}


@router.get("/audit")
async def audit_log(
    request: Request, principal: DashboardPrincipal = Depends(require_dashboard)
) -> list[dict[str, Any]]:
    return await _repository(request).audit_log(UUID(principal.world_id))


@router.get("/features")
async def feature_eligibility(
    request: Request, principal: DashboardPrincipal = Depends(require_dashboard)
) -> dict[str, Any]:
    async with request.app.state.db_sessions() as db:
        broadcaster = await db.scalar(
            select(OAuthToken).where(
                OAuthToken.role == "broadcaster",
                OAuthToken.channel_id == UUID(principal.channel_id),
            )
        )
    scopes = set(broadcaster.scopes if broadcaster else [])
    connected = broadcaster is not None
    return {
        "features": [
            {
                "name": "Incoming raids",
                "available": connected,
                "enabled": connected,
                "reason": "Core channel.raid v1 needs the broadcaster token but no event scope."
                if connected
                else "Connect the broadcaster account to receive incoming raids.",
            },
            {
                "name": "Follows",
                "available": "moderator:read:followers" in scopes,
                "enabled": "moderator:read:followers" in scopes,
                "reason": "Requires broadcaster follower-read scope and moderator relationship."
                if "moderator:read:followers" not in scopes
                else "Scope granted; subscription status is shown in Connect.",
            },
            {
                "name": "Subscriptions",
                "available": False,
                "enabled": False,
                "reason": (
                    "Requires Twitch Affiliate or Partner eligibility and an enabled "
                    "subscription event scope."
                ),
            },
            {
                "name": "Channel points",
                "available": False,
                "enabled": False,
                "reason": (
                    "Requires Affiliate or Partner eligibility and additional EventSub permissions."
                ),
            },
            {
                "name": "Cheers",
                "available": False,
                "enabled": False,
                "reason": (
                    "Disabled in this release; requires bits:read and a permitted broadcaster "
                    "account."
                ),
            },
            {
                "name": "Native polls",
                "available": False,
                "enabled": False,
                "reason": (
                    "Disabled in this release; Twitch polls require Affiliate/Partner eligibility "
                    "and channel:read:polls or channel:manage:polls. Chat votes remain available."
                ),
            },
        ]
    }
