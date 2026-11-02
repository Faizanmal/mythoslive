import asyncio
from contextlib import asynccontextmanager
from uuid import UUID

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.ai.master import AIGameMaster
from app.ai.quill import QuillService
from app.ai.repository import AIRepository
from app.api.ai import router as ai_router
from app.api.chronicles import router as chronicles_router
from app.api.dashboard import router as dashboard_router
from app.api.game import router as game_router
from app.api.health import router as health_router
from app.api.overlay import public_router as overlay_public_router
from app.api.overlay import router as overlay_router
from app.api.simulator import router as simulator_router
from app.api.twitch import router as twitch_router
from app.core.logging import configure_logging
from app.core.settings import get_settings
from app.db.session import create_database_engine, create_session_factory
from app.engine.repository import EngineRepository
from app.engine.service import GameEngineService
from app.models.entities import World
from app.repositories.dashboard import DashboardRepository
from app.repositories.oauth_tokens import OAuthTokenRepository
from app.services.chat_outbox import ChatOutbox
from app.services.dashboard_auth import DashboardAuth
from app.services.eventsub import EventSubManager
from app.services.ingress import EventRecorder, IngressPipeline
from app.services.simulator import SimulatorService
from app.services.twitch_helix import TwitchHelixClient
from app.services.twitch_oauth import TwitchOAuthService


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    app.state.settings = settings
    app.state.db_engine = create_database_engine(settings.database_url)
    app.state.token_validation_task = None
    try:
        app.state.db_sessions = create_session_factory(app.state.db_engine)
        app.state.dashboard_auth = DashboardAuth(settings)
        app.state.dashboard_repository = DashboardRepository(app.state.db_sessions)
        app.state.oauth_repository = OAuthTokenRepository(app.state.db_sessions)
        app.state.twitch_http = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0))
        app.state.twitch_oauth = TwitchOAuthService(
            settings, app.state.oauth_repository, app.state.twitch_http
        )
        app.state.twitch_helix = TwitchHelixClient(
            settings, app.state.twitch_oauth, app.state.twitch_http
        )
        app.state.event_recorder = EventRecorder()
        app.state.ingress = IngressPipeline(settings, app.state.event_recorder)
        app.state.engine = GameEngineService(EngineRepository(app.state.db_sessions))
        await app.state.engine.ensure_simulator_world(UUID(settings.sim_world_id))
        await app.state.engine.restore()
        app.state.event_recorder.subscribe(app.state.engine.enqueue)
        app.state.ai_repository = AIRepository(app.state.db_sessions)
        app.state.ai_master = AIGameMaster(settings, app.state.engine, app.state.ai_repository)
        runtime_world_id = UUID(settings.sim_world_id)
        saved_broadcaster = await app.state.oauth_repository.get("broadcaster")
        if saved_broadcaster:
            async with app.state.db_sessions() as db:
                broadcaster_world = await db.scalar(
                    select(World.id).where(World.channel_id == saved_broadcaster.channel_id)
                )
            if broadcaster_world:
                runtime_world_id = broadcaster_world
        runtime_config = await app.state.dashboard_repository.config(runtime_world_id)
        config = runtime_config["settings"]
        app.state.ai_master.update_settings(
            tone=config.get("tone"),
            family_friendly=config.get("family_friendly"),
            banned_topics=config.get("banned_topics"),
            approval_mode=config.get("approval_mode"),
        )
        settings.command_user_cooldown_seconds = config["command_cooldown_seconds"]
        app.state.ingress.muted_twitch_ids = await app.state.dashboard_repository.muted_twitch_ids()
        app.state.event_recorder.subscribe(app.state.ai_master.on_input)
        app.state.ai_master.start()
        app.state.engine.start()
        app.state.eventsub = EventSubManager(
            settings, app.state.oauth_repository, app.state.twitch_helix, app.state.ingress
        )
        app.state.chat_outbox = ChatOutbox(settings, app.state.twitch_helix)
        app.state.chat_outbox._limiter.max_per_window = config["bot_messages_per_30_seconds"]
        app.state.chat_outbox.start()
        app.state.quill = QuillService(
            settings,
            app.state.engine,
            app.state.ai_repository,
            app.state.ai_master,
            app.state.chat_outbox,
        )
        app.state.event_recorder.subscribe(app.state.quill.on_input)
        app.state.quill.start()
        app.state.simulator = SimulatorService(
            settings, app.state.ingress, app.state.event_recorder, app.state.engine
        )

        broadcaster = await app.state.oauth_repository.get("broadcaster")
        bot = await app.state.oauth_repository.get("bot")
        if broadcaster or bot:
            broadcaster_ok, bot_ok = await asyncio.gather(
                app.state.twitch_oauth.validate_saved("broadcaster"),
                app.state.twitch_oauth.validate_saved("bot"),
            )
            if broadcaster_ok and bot_ok and broadcaster.channel_id == bot.channel_id:
                app.state.eventsub.start()
            app.state.token_validation_task = asyncio.create_task(
                app.state.twitch_oauth.validation_loop(), name="twitch-token-validation"
            )
        yield
    finally:
        simulator = getattr(app.state, "simulator", None)
        if simulator is not None:
            await simulator.stop()
        quill = getattr(app.state, "quill", None)
        if quill is not None:
            await quill.stop()
        eventsub = getattr(app.state, "eventsub", None)
        if eventsub is not None:
            await eventsub.stop()
        ai_master = getattr(app.state, "ai_master", None)
        if ai_master is not None:
            await ai_master.stop()
        engine = getattr(app.state, "engine", None)
        if engine is not None:
            await engine.stop()
        chat_outbox = getattr(app.state, "chat_outbox", None)
        if chat_outbox is not None:
            await chat_outbox.stop()
        task = app.state.token_validation_task
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        twitch_http = getattr(app.state, "twitch_http", None)
        if twitch_http is not None:
            await twitch_http.aclose()
        await app.state.db_engine.dispose()


settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Mythos-CSRF"],
)
app.include_router(health_router)
app.include_router(dashboard_router)
app.include_router(ai_router)
app.include_router(game_router)
app.include_router(overlay_router)
app.include_router(overlay_public_router)
app.include_router(chronicles_router)
app.include_router(twitch_router)
app.include_router(simulator_router)
