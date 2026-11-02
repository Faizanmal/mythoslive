from datetime import UTC, datetime
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.contracts.events import ChatEnableRequest, ChatSendRequest, TwitchConnectionStatus
from app.core.settings import Settings
from app.repositories.oauth_tokens import OAuthTokenRepository
from app.services.chat_outbox import ChatOutbox
from app.services.dashboard_auth import (
    DashboardPrincipal,
    require_dashboard,
    require_dashboard_mutation,
)
from app.services.eventsub import EventSubManager
from app.services.twitch_oauth import (
    OAuthRole,
    TwitchOAuthError,
    TwitchOAuthService,
)

router = APIRouter(prefix="/api/twitch", tags=["twitch"])


class OAuthStartError(BaseModel):
    detail: str


def _local_origin(request: Request) -> None:
    settings: Settings = request.app.state.settings
    origin = request.headers.get("origin")
    if origin not in settings.cors_origins:
        raise HTTPException(status_code=403, detail="Request origin is not allowed.")


@router.get("/status", response_model=TwitchConnectionStatus)
async def connection_status(
    request: Request, _principal: DashboardPrincipal = Depends(require_dashboard)
) -> TwitchConnectionStatus:
    oauth: TwitchOAuthService = request.app.state.twitch_oauth
    repository: OAuthTokenRepository = request.app.state.oauth_repository
    eventsub: EventSubManager = request.app.state.eventsub
    outbox: ChatOutbox = request.app.state.chat_outbox
    broadcaster = await repository.get("broadcaster")
    bot = await repository.get("bot")
    broadcaster_state = oauth.status("broadcaster")
    bot_state = oauth.status("bot")
    event_status = eventsub.status
    any_subscription_failed = any(
        value != "enabled" for value in event_status["subscriptions"].values()
    )
    eventsub_state = event_status["status"]
    if eventsub_state == "connected" and any_subscription_failed:
        eventsub_state = "degraded"
    return TwitchConnectionStatus(
        broadcaster_connected=broadcaster is not None and broadcaster_state.status == "connected",
        bot_connected=bot is not None and bot_state.status == "connected",
        broadcaster_user_id=broadcaster.twitch_user_id if broadcaster else None,
        bot_user_id=bot.twitch_user_id if bot else None,
        broadcaster_scopes=broadcaster.scopes if broadcaster else [],
        bot_scopes=bot.scopes if bot else [],
        eventsub_status=eventsub_state,
        eventsub_session_id=event_status["session_id"],
        subscriptions=event_status["subscriptions"],
        last_keepalive_at=event_status["last_keepalive_at"],
        last_message_at=event_status["last_message_at"],
        last_error=event_status["last_error"] or broadcaster_state.error or bot_state.error,
        chat_send_enabled=outbox.enabled,
        outbox_pending=outbox.pending,
        outbox_sent=outbox.sent,
        outbox_dropped=outbox.dropped,
    )


@router.get("/oauth/{role}/start")
async def oauth_start(role: OAuthRole, request: Request) -> RedirectResponse:
    oauth: TwitchOAuthService = request.app.state.twitch_oauth
    if role == "bot":
        principal = await require_dashboard(request)
        if principal.simulator:
            raise HTTPException(
                status_code=409, detail="Connect a broadcaster before authorizing a bot."
            )
    try:
        return RedirectResponse(await oauth.begin(role), status_code=302)
    except TwitchOAuthError as exc:
        raise HTTPException(
            status_code=503 if exc.code == "not_configured" else 409, detail=exc.public_message
        ) from exc


@router.get("/oauth/{role}/callback")
async def oauth_callback(
    role: OAuthRole,
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    oauth: TwitchOAuthService = request.app.state.twitch_oauth
    eventsub: EventSubManager = request.app.state.eventsub
    frontend = request.app.state.settings.cors_origins[0]
    try:
        principal = (
            await request.app.state.dashboard_auth.authenticate(request) if role == "bot" else None
        )
        if error:
            if not await oauth.states.consume(role, state):
                raise TwitchOAuthError(
                    "invalid_state", "OAuth state was missing, expired, or invalid."
                )
            raise TwitchOAuthError("authorization_denied", "Twitch authorization was denied.")
        if not code:
            if not await oauth.states.consume(role, state):
                raise TwitchOAuthError(
                    "invalid_state", "OAuth state was missing, expired, or invalid."
                )
            raise TwitchOAuthError("missing_code", "Twitch did not return an authorization code.")
        connected = await oauth.complete(role, code, state)
        if role == "bot" and (
            principal is None or connected.channel_id != UUID(principal.channel_id)
        ):
            raise TwitchOAuthError(
                "channel_mismatch", "Authorize the bot for the signed-in broadcaster."
            )
        broadcaster = await request.app.state.oauth_repository.get("broadcaster")
        bot = await request.app.state.oauth_repository.get("bot")
        if broadcaster and bot and broadcaster.channel_id == bot.channel_id:
            eventsub.start()
        else:
            await eventsub.stop()
            request.app.state.chat_outbox.set_enabled(False)
        response = RedirectResponse(
            f"{frontend}/dashboard/connect?connected={role}", status_code=303
        )
        if role == "broadcaster":
            request.app.state.dashboard_auth.set_cookies(response, connected.twitch_user_id or "")
        return response
    except HTTPException as exc:
        return RedirectResponse(
            f"{frontend}/dashboard/connect?oauth_error=sign_in_required&message={quote(str(exc.detail))}",
            status_code=303,
        )
    except TwitchOAuthError as exc:
        return RedirectResponse(
            f"{frontend}/dashboard/connect?oauth_error={quote(exc.code)}&message={quote(exc.public_message)}",
            status_code=303,
        )


@router.delete("/oauth/{role}")
async def disconnect_role(
    role: OAuthRole,
    request: Request,
    principal: DashboardPrincipal = Depends(require_dashboard_mutation),
) -> dict[str, str]:
    oauth: TwitchOAuthService = request.app.state.twitch_oauth
    eventsub: EventSubManager = request.app.state.eventsub
    outbox: ChatOutbox = request.app.state.chat_outbox
    broadcaster = await oauth.repository.get("broadcaster")
    if (
        principal.simulator
        or not broadcaster
        or broadcaster.twitch_user_id != principal.broadcaster_id
    ):
        raise HTTPException(
            status_code=403, detail="This Twitch connection is not owned by the session."
        )
    try:
        await oauth.disconnect(role)
        if role == "broadcaster":
            await oauth.disconnect("bot")
    except TwitchOAuthError as exc:
        raise HTTPException(status_code=502, detail=exc.public_message) from exc
    await eventsub.stop()
    outbox.set_enabled(False)
    return {"status": "disconnected", "role": role}


@router.post("/chat/enable")
async def set_chat_enabled(
    body: ChatEnableRequest,
    request: Request,
    principal: DashboardPrincipal = Depends(require_dashboard_mutation),
) -> dict[str, bool]:
    oauth: TwitchOAuthService = request.app.state.twitch_oauth
    outbox: ChatOutbox = request.app.state.chat_outbox
    if body.enabled:
        broadcaster = await oauth.repository.get("broadcaster")
        bot = await oauth.repository.get("bot")
        if not oauth.configured or not broadcaster or not bot:
            raise HTTPException(
                status_code=409, detail="Connect both Twitch roles before enabling chat."
            )
        if broadcaster.channel_id != bot.channel_id:
            raise HTTPException(
                status_code=409, detail="Bot account is not authorized for this broadcaster."
            )
        if principal.simulator or broadcaster.twitch_user_id != principal.broadcaster_id:
            raise HTTPException(
                status_code=403, detail="This Twitch channel is not owned by the session."
            )
    outbox.set_enabled(body.enabled)
    return {"enabled": outbox.enabled}


@router.post("/chat/test")
async def send_test_chat(
    body: ChatSendRequest,
    request: Request,
    principal: DashboardPrincipal = Depends(require_dashboard_mutation),
) -> dict[str, object]:
    outbox: ChatOutbox = request.app.state.chat_outbox
    broadcaster = await request.app.state.oauth_repository.get("broadcaster")
    if not outbox.enabled:
        raise HTTPException(
            status_code=409, detail="Enable bot chat explicitly before sending a test."
        )
    if broadcaster is None or broadcaster.twitch_user_id is None:
        raise HTTPException(status_code=409, detail="Connect a broadcaster account first.")
    if principal.simulator or broadcaster.twitch_user_id != principal.broadcaster_id:
        raise HTTPException(
            status_code=403, detail="This Twitch channel is not owned by the session."
        )
    try:
        result = await outbox.enqueue(
            channel_id=broadcaster.twitch_user_id,
            message=body.message,
            source="twitch",
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "status": result.status,
        "message_id": result.message_id,
        "drop_code": result.drop_code,
        "drop_reason": result.drop_reason,
        "retry_after_seconds": result.retry_after_seconds,
        "completed_at": datetime.now(UTC),
    }
