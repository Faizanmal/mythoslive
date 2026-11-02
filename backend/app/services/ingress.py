import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from app.contracts.events import ActorIdentity, GameEvent
from app.core.settings import Settings
from app.services.command_parser import CommandRejected, parse_command

EventSource = Literal["twitch", "simulator"]


class EventSubDeduper:
    """Bounded TTL cache for Twitch's at-least-once notification delivery."""

    def __init__(self, *, max_items: int = 50_000, ttl_seconds: float = 7_200) -> None:
        self.max_items = max_items
        self.ttl_seconds = ttl_seconds
        self._seen: dict[str, float] = {}
        self._order: deque[tuple[str, float]] = deque()

    def accept(self, message_id: str, *, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        self._prune(current)
        if message_id in self._seen:
            return False
        expires = current + self.ttl_seconds
        self._seen[message_id] = expires
        self._order.append((message_id, expires))
        while len(self._seen) > self.max_items:
            self._remove_oldest()
        return True

    def _prune(self, now: float) -> None:
        while self._order and self._order[0][1] <= now:
            self._remove_oldest()

    def _remove_oldest(self) -> None:
        message_id, expires = self._order.popleft()
        if self._seen.get(message_id) == expires:
            self._seen.pop(message_id, None)


@dataclass
class IngressMetrics:
    accepted: int = 0
    ignored: int = 0
    rejected: int = 0
    duplicates: int = 0
    bot_messages: int = 0


class EventRecorder:
    """Short-lived, bounded in-memory feed for the simulator and dashboard."""

    def __init__(self, max_items: int = 100) -> None:
        self._items: deque[tuple[int, GameEvent]] = deque(maxlen=max_items)
        self._sequence = 0
        self.metrics = IngressMetrics()
        self._subscribers: list[Callable[[GameEvent], object]] = []

    def subscribe(self, subscriber: Callable[[GameEvent], object]) -> None:
        self._subscribers.append(subscriber)

    def publish(self, event: GameEvent) -> GameEvent:
        self._sequence += 1
        self._items.append((self._sequence, event))
        self.metrics.accepted += 1
        for subscriber in self._subscribers:
            subscriber(event)
        return event

    def since(self, sequence: int = 0) -> list[tuple[int, GameEvent]]:
        return [(seq, event) for seq, event in self._items if seq > sequence]

    @property
    def sequence(self) -> int:
        return self._sequence


class IngressPipeline:
    def __init__(
        self,
        settings: Settings,
        recorder: EventRecorder,
        *,
        clock=time.monotonic,
    ) -> None:
        self.settings = settings
        self.recorder = recorder
        self._clock = clock
        self.bot_user_id: str | None = None
        self.muted_twitch_ids: set[str] = set()
        self._user_last: dict[str, float] = {}
        self._global_times: deque[float] = deque()

    def handle_chat(
        self,
        *,
        message: str,
        source: EventSource,
        world_id: UUID,
        user_id: str | None,
        display_name: str,
        color: str | None = None,
        is_moderator: bool = False,
        event_id: UUID | None = None,
        occurred_at: datetime | None = None,
    ) -> GameEvent | None:
        if source == "twitch" and user_id and user_id == self.bot_user_id:
            self.recorder.metrics.bot_messages += 1
            self.recorder.metrics.ignored += 1
            return None
        if source == "twitch" and user_id and user_id in self.muted_twitch_ids:
            self.recorder.metrics.ignored += 1
            return None
        if len(message) > self.settings.command_max_input_length:
            self.recorder.metrics.rejected += 1
            return None
        try:
            parsed = parse_command(
                message,
                is_moderator=is_moderator,
                max_length=self.settings.command_max_input_length,
            )
        except CommandRejected:
            self.recorder.metrics.rejected += 1
            return None
        now = self._clock()
        if not self._within_rate_limits(user_id or display_name, now):
            self.recorder.metrics.rejected += 1
            return None
        simulated = source == "simulator"
        normalized_identity = (
            f"simulator:{user_id or display_name.casefold()}"
            if simulated
            else f"twitch:{user_id}"
            if user_id
            else None
        )
        actor = ActorIdentity(
            kind="simulator" if simulated else "twitch",
            identity_key=normalized_identity,
            twitch_user_id=user_id if not simulated else None,
            display_name=f"[SIM] {display_name}" if simulated else display_name,
            color=color if not simulated else None,
        )
        event = GameEvent(
            event_id=event_id or uuid4(),
            event_type=(f"chat.command.{parsed.name}" if parsed else "chat.message"),
            occurred_at=occurred_at or datetime.now(UTC),
            source=source,
            world_id=world_id,
            actor=actor,
            payload={
                "command": parsed.name if parsed else None,
                "arguments": parsed.arguments if parsed else None,
                "message": message if parsed is None else None,
                "simulated": simulated,
                "is_moderator": bool(is_moderator and not simulated),
            },
        )
        return self.recorder.publish(event)

    def record_social_event(self, event: GameEvent) -> GameEvent:
        return self.recorder.publish(event)

    def _within_rate_limits(self, actor_key: str, now: float) -> bool:
        while self._global_times and self._global_times[0] <= now - 1:
            self._global_times.popleft()
        if len(self._global_times) >= self.settings.command_global_per_second:
            return False
        previous = self._user_last.get(actor_key)
        if previous is not None and now - previous < self.settings.command_user_cooldown_seconds:
            return False
        self._global_times.append(now)
        self._user_last[actor_key] = now
        if len(self._user_last) > 20_000:
            cutoff = now - 60
            self._user_last = {key: seen for key, seen in self._user_last.items() if seen > cutoff}
        return True
