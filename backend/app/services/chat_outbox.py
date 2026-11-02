import asyncio
import itertools
from dataclasses import dataclass, field
from enum import IntEnum

from app.core.settings import Settings
from app.services.twitch_helix import ChatRateLimiter, SendChatResult, TwitchHelixClient


class ChatPriority(IntEnum):
    SYSTEM = 0
    GAME = 10
    CHRONICLER = 20


@dataclass(order=True)
class _QueuedMessage:
    priority: int
    sequence: int
    channel_id: str = field(compare=False)
    message: str = field(compare=False)
    source: str = field(compare=False)
    future: asyncio.Future[SendChatResult] = field(compare=False)


class ChatOutbox:
    """Single-worker priority queue. Unknown network outcomes are never retried."""

    def __init__(self, settings: Settings, helix: TwitchHelixClient) -> None:
        self.settings = settings
        self.helix = helix
        self.enabled = False
        self.pending = 0
        self.sent = 0
        self.dropped = 0
        self.failed = 0
        self.rate_limited = 0
        self._queue: asyncio.PriorityQueue[_QueuedMessage | tuple[int, int, None]] = (
            asyncio.PriorityQueue(maxsize=settings.chat_outbox_max_size)
        )
        self._sequence = itertools.count()
        self._worker: asyncio.Task[None] | None = None
        self._limiter = ChatRateLimiter(
            max_per_window=settings.chat_global_messages_per_30_seconds,
            window_seconds=30,
            per_channel_interval=settings.chat_channel_interval_seconds,
        )

    def start(self) -> None:
        if self._worker is None:
            self._worker = asyncio.create_task(self._run(), name="twitch-chat-outbox")

    async def stop(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                pass
        while not self._queue.empty():
            item = self._queue.get_nowait()
            if isinstance(item, _QueuedMessage) and not item.future.done():
                item.future.set_exception(RuntimeError("Chat outbox stopped before sending."))
            self._queue.task_done()
        self.pending = 0

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled

    async def enqueue(
        self,
        *,
        channel_id: str,
        message: str,
        source: str,
        priority: ChatPriority = ChatPriority.GAME,
    ) -> SendChatResult:
        return (
            await self.enqueue_batch(
                channel_id=channel_id, messages=[message], source=source, priority=priority
            )
        )[0]

    async def enqueue_batch(
        self,
        *,
        channel_id: str,
        messages: list[str],
        source: str,
        priority: ChatPriority = ChatPriority.GAME,
    ) -> list[SendChatResult]:
        futures = self.enqueue_nowait_batch(
            channel_id=channel_id, messages=messages, source=source, priority=priority
        )
        return list(await asyncio.gather(*futures))

    def enqueue_nowait_batch(
        self,
        *,
        channel_id: str,
        messages: list[str],
        source: str,
        priority: ChatPriority = ChatPriority.GAME,
    ) -> list[asyncio.Future[SendChatResult]]:
        if not messages or len(messages) > self.settings.chat_outbox_batch_max_size:
            raise ValueError("Chat batch exceeds the configured batch maximum.")
        if not self.enabled:
            raise RuntimeError("Bot chat sending is disabled; explicitly enable it first.")
        if source != "twitch":
            raise RuntimeError("Simulator events cannot enter the Twitch chat outbox.")
        if self._worker is None:
            raise RuntimeError("Chat outbox is not running.")
        if self._queue.qsize() + len(messages) > self.settings.chat_outbox_max_size:
            raise RuntimeError("Chat outbox is full.")
        for message in messages:
            if not message.strip():
                raise ValueError("Chat message cannot be empty.")
            if len(message) > self.settings.chat_max_message_length:
                raise ValueError("Chat message exceeds Twitch's 500 character limit.")
        loop = asyncio.get_running_loop()
        futures = []
        for message in messages:
            future: asyncio.Future[SendChatResult] = loop.create_future()
            item = _QueuedMessage(
                int(priority), next(self._sequence), channel_id, message, source, future
            )
            self._queue.put_nowait(item)
            futures.append(future)
        self.pending += len(futures)
        return futures

    async def _run(self) -> None:
        while True:
            item = await self._queue.get()
            if not isinstance(item, _QueuedMessage):
                self._queue.task_done()
                continue
            try:
                if not self.enabled:
                    raise RuntimeError(
                        "Bot chat sending was disabled before this message was sent."
                    )
                await self._limiter.wait_turn(item.channel_id)
                if not self.enabled:
                    raise RuntimeError(
                        "Bot chat sending was disabled before this message was sent."
                    )
                result = await self.helix.send_chat_message(item.message)
                if result.status == "rate_limited":
                    self.rate_limited += 1
                    self._limiter.block_for(result.retry_after_seconds or 30.0)
                    await self._queue.put(item)
                    continue
                if result.status == "sent":
                    self.sent += 1
                elif result.status == "dropped":
                    self.dropped += 1
                else:
                    self.failed += 1
                if not item.future.done():
                    item.future.set_result(result)
            except Exception as exc:
                self.failed += 1
                if not item.future.done():
                    item.future.set_exception(exc)
            finally:
                if item.future.done():
                    self.pending = max(0, self.pending - 1)
                self._queue.task_done()
