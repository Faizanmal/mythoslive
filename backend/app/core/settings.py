from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True
    )

    app_name: str = "MythosLive API"
    build_version: str = "local"
    environment: str = "development"
    database_url: str = "postgresql+asyncpg://mythos:mythos@localhost:5432/mythoslive"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    encryption_key: str | None = None
    # None creates an unbounded pgvector VECTOR column. Set when an embedding model is selected.
    embedding_dimension: int | None = None
    twitch_client_id: str | None = None
    twitch_client_secret: str | None = None
    twitch_broadcaster_redirect_uri: str = (
        "http://localhost:8000/api/twitch/oauth/broadcaster/callback"
    )
    twitch_bot_redirect_uri: str = "http://localhost:8000/api/twitch/oauth/bot/callback"
    twitch_eventsub_url: str = "wss://eventsub.wss.twitch.tv/ws"
    twitch_eventsub_keepalive_timeout: int = 30
    eventsub_max_retries: int = 10
    chat_outbox_max_size: int = 200
    chat_outbox_batch_max_size: int = 20
    chat_global_messages_per_30_seconds: int = 20
    chat_channel_interval_seconds: float = 1.0
    chat_max_message_length: int = 500
    command_max_input_length: int = 500
    command_global_per_second: int = 100
    command_user_cooldown_seconds: float = 0.5
    sim_world_id: str = "6c9f5a98-8f43-5bd5-a263-239ea8b494fc"

    ai_api_base_url: str | None = None
    ai_api_key: str | None = None
    ai_director_model: str | None = None
    ai_fast_model: str | None = None
    ai_embedding_model: str | None = None
    ai_moderation_model: str | None = None
    ai_timeout_seconds: float = 4.0
    ai_max_retries: int = 1
    ai_circuit_failure_threshold: int = 3
    ai_circuit_reset_seconds: int = 30
    ai_session_token_budget: int = 20_000
    ai_session_cost_budget_usd: float = 1.0
    ai_input_cost_per_million: float = 0.0
    ai_output_cost_per_million: float = 0.0
    ai_tone: Literal["heroic", "grimdark", "comedic"] = "heroic"
    ai_family_friendly: bool = True
    ai_banned_topics: list[str] = Field(default_factory=list)
    ai_approval_mode: Literal["required", "auto_safe"] = "required"
    quill_user_cooldown_seconds: float = 30.0
    quill_global_messages_per_minute: int = 6
    memory_context_limit: int = 6

    @field_validator("embedding_dimension")
    @classmethod
    def validate_embedding_dimension(cls, value: int | None) -> int | None:
        if value is not None and value < 1:
            raise ValueError("EMBEDDING_DIMENSION must be a positive integer or omitted")
        return value

    @field_validator("twitch_eventsub_keepalive_timeout")
    @classmethod
    def validate_keepalive_timeout(cls, value: int) -> int:
        if not 10 <= value <= 600:
            raise ValueError("TWITCH_EVENTSUB_KEEPALIVE_TIMEOUT must be between 10 and 600")
        return value

    @field_validator("chat_max_message_length")
    @classmethod
    def validate_chat_max_length(cls, value: int) -> int:
        if not 1 <= value <= 500:
            raise ValueError(
                "CHAT_MAX_MESSAGE_LENGTH must be between 1 and Twitch's 500 character limit"
            )
        return value

    @field_validator("ai_timeout_seconds")
    @classmethod
    def validate_ai_timeout(cls, value: float) -> float:
        if not 0.2 <= value <= 30:
            raise ValueError("AI_TIMEOUT_SECONDS must be between 0.2 and 30")
        return value

    @field_validator("ai_max_retries")
    @classmethod
    def validate_ai_retries(cls, value: int) -> int:
        if not 0 <= value <= 3:
            raise ValueError("AI_MAX_RETRIES must be between 0 and 3")
        return value

    @field_validator("ai_circuit_failure_threshold", "ai_circuit_reset_seconds")
    @classmethod
    def validate_ai_circuit_values(cls, value: int) -> int:
        if value < 1:
            raise ValueError("AI circuit breaker settings must be positive")
        return value

    @field_validator("ai_session_token_budget")
    @classmethod
    def validate_ai_token_budget(cls, value: int) -> int:
        if not 0 <= value <= 2_000_000:
            raise ValueError("AI_SESSION_TOKEN_BUDGET must be between 0 and 2000000")
        return value

    @field_validator(
        "ai_session_cost_budget_usd", "ai_input_cost_per_million", "ai_output_cost_per_million"
    )
    @classmethod
    def validate_ai_cost(cls, value: float) -> float:
        if value < 0 or value > 10_000:
            raise ValueError("AI cost settings must be between 0 and 10000 USD")
        return value

    @field_validator("ai_banned_topics")
    @classmethod
    def validate_ai_banned_topics(cls, value: list[str]) -> list[str]:
        if len(value) > 30 or any(not topic.strip() or len(topic) > 80 for topic in value):
            raise ValueError("AI_BANNED_TOPICS allows up to 30 non-empty topics of 80 chars")
        return [topic.strip() for topic in value]

    @field_validator("quill_user_cooldown_seconds")
    @classmethod
    def validate_quill_user_cooldown(cls, value: float) -> float:
        if not 1 <= value <= 3_600:
            raise ValueError("QUILL_USER_COOLDOWN_SECONDS must be between 1 and 3600")
        return value

    @field_validator("quill_global_messages_per_minute", "memory_context_limit")
    @classmethod
    def validate_small_positive_settings(cls, value: int) -> int:
        if not 1 <= value <= 50:
            raise ValueError("Quill and memory context limits must be between 1 and 50")
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
