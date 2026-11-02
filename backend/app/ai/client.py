import asyncio
import random
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.settings import Settings


class AIServiceError(Exception):
    def __init__(self, reason: str, *, status_code: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


@dataclass
class ChatResult:
    content: str
    tool_calls: list[dict[str, Any]]
    input_tokens: int
    output_tokens: int


@dataclass
class ModerationResult:
    allowed: list[bool]
    input_tokens: int = 0


class CircuitBreaker:
    def __init__(self, threshold: int, reset_seconds: int) -> None:
        self.threshold = threshold
        self.reset_seconds = reset_seconds
        self.failures = 0
        self.open_until = 0.0

    @property
    def state(self) -> str:
        if self.open_until > time.monotonic():
            return "open"
        return "half_open" if self.failures >= self.threshold else "closed"

    def before_request(self, *, allow_probe: bool = False) -> None:
        if self.open_until > time.monotonic() and not allow_probe:
            raise AIServiceError("circuit_open")

    def success(self) -> None:
        self.failures = 0
        self.open_until = 0.0

    def failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.open_until = time.monotonic() + self.reset_seconds


class OpenAICompatibleClient:
    """Small async Chat Completions/Moderations/Embeddings client; never logs bodies."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(
                settings.ai_timeout_seconds, connect=min(3, settings.ai_timeout_seconds)
            ),
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
        )
        self._owns_client = client is None
        self.breaker = CircuitBreaker(
            settings.ai_circuit_failure_threshold, settings.ai_circuit_reset_seconds
        )
        self.requests = 0
        self.failures = 0
        self.latency_ms_total = 0

    @property
    def configured(self) -> bool:
        return bool(self.settings.ai_api_base_url and self.settings.ai_api_key)

    async def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 400,
        temperature: float = 0.5,
        allow_circuit_probe: bool = False,
    ) -> ChatResult:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        raw = await self._post("/chat/completions", body, allow_circuit_probe=allow_circuit_probe)
        try:
            choice = raw["choices"][0]["message"]
            usage = raw.get("usage", {})
            tool_calls = choice.get("tool_calls", []) or []
            return ChatResult(
                content=str(choice.get("content") or "")[:2000],
                tool_calls=tool_calls[:10],
                input_tokens=int(usage.get("prompt_tokens", 0) or 0),
                output_tokens=int(usage.get("completion_tokens", 0) or 0),
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            self.breaker.failure()
            raise AIServiceError("malformed_response") from exc

    async def moderate(self, texts: list[str], model: str) -> ModerationResult:
        if not texts:
            return ModerationResult([])
        raw = await self._post("/moderations", {"model": model, "input": texts[:32]})
        try:
            results = raw["results"]
            return ModerationResult(
                [not bool(item.get("flagged", False)) for item in results[: len(texts)]],
                int(raw.get("usage", {}).get("prompt_tokens", 0) or 0),
            )
        except (KeyError, TypeError, ValueError) as exc:
            self.breaker.failure()
            raise AIServiceError("malformed_moderation_response") from exc

    async def embed(self, texts: list[str], model: str) -> list[list[float]]:
        raw = await self._post("/embeddings", {"model": model, "input": texts[:32]})
        try:
            return [list(map(float, item["embedding"])) for item in raw["data"]]
        except (KeyError, TypeError, ValueError) as exc:
            self.breaker.failure()
            raise AIServiceError("malformed_embedding_response") from exc

    async def _post(
        self, path: str, body: dict[str, Any], *, allow_circuit_probe: bool = False
    ) -> dict[str, Any]:
        if not self.configured:
            raise AIServiceError("missing_configuration")
        self.breaker.before_request(allow_probe=allow_circuit_probe)
        base = (self.settings.ai_api_base_url or "").rstrip("/")
        headers = {
            "Authorization": f"Bearer {self.settings.ai_api_key}",
            "Content-Type": "application/json",
        }
        last_error = "provider_error"
        for attempt in range(self.settings.ai_max_retries + 1):
            started = time.monotonic()
            self.requests += 1
            try:
                async with asyncio.timeout(self.settings.ai_timeout_seconds):
                    response = await self._client.post(f"{base}{path}", headers=headers, json=body)
                self.latency_ms_total += int((time.monotonic() - started) * 1000)
                if response.status_code in {401, 403}:
                    self.failures += 1
                    self.breaker.failure()
                    raise AIServiceError("invalid_key", status_code=response.status_code)
                if response.status_code == 429:
                    last_error = "rate_limited"
                    retryable = True
                elif response.status_code >= 500:
                    last_error = "provider_unavailable"
                    retryable = True
                elif not response.is_success:
                    self.breaker.failure()
                    raise AIServiceError("provider_rejected", status_code=response.status_code)
                else:
                    try:
                        result = response.json()
                    except ValueError as exc:
                        self.breaker.failure()
                        raise AIServiceError("malformed_json") from exc
                    if not isinstance(result, dict):
                        self.breaker.failure()
                        raise AIServiceError("malformed_json")
                    self.breaker.success()
                    return result
                if not retryable or attempt >= self.settings.ai_max_retries:
                    self.failures += 1
                    self.breaker.failure()
                    raise AIServiceError(last_error, status_code=response.status_code)
            except asyncio.CancelledError:
                raise
            except TimeoutError as exc:
                last_error = "timeout"
                self.latency_ms_total += int((time.monotonic() - started) * 1000)
                self.failures += 1
                self.breaker.failure()
                if attempt >= self.settings.ai_max_retries:
                    raise AIServiceError(last_error) from exc
            except httpx.TimeoutException as exc:
                last_error = "timeout"
                self.failures += 1
                self.breaker.failure()
                if attempt >= self.settings.ai_max_retries:
                    raise AIServiceError(last_error) from exc
            except httpx.TransportError as exc:
                last_error = "network_error"
                self.failures += 1
                self.breaker.failure()
                if attempt >= self.settings.ai_max_retries:
                    raise AIServiceError(last_error) from exc
            if attempt < self.settings.ai_max_retries:
                await asyncio.sleep(min(1.5, 0.2 * 2**attempt) + random.uniform(0.0, 0.15))
        raise AIServiceError(last_error)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
