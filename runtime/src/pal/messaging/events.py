"""Runtime events and the in-process bus that fans them out to subscribers."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pal.log import get_logger

log = get_logger(__name__)


class EventType:
    """Event names published on the bus (and streamed to the app)."""

    MESSAGE_CREATED = "message.created"
    BOT_STATUS = "bot.status"
    BOT_TEXT_DELTA = "bot.text.delta"
    BOT_THINKING = "bot.thinking"
    BOT_TOOL_STARTED = "bot.tool.started"
    BOT_TOOL_FINISHED = "bot.tool.finished"
    BOT_TURN_COMPLETED = "bot.turn.completed"
    BOT_SETTINGS_CHANGED = "bot.settings.changed"
    BOT_ADDED = "bot.added"
    BOT_UPDATED = "bot.updated"
    BOT_REMOVED = "bot.removed"
    DISPLAY_STATE = "display.state"


@dataclass(frozen=True)
class Event:
    type: str
    data: dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "data": self.data, "timestamp": self.timestamp.isoformat()}


class Subscription:
    """A bounded queue of events for one subscriber.

    A subscriber that falls behind loses its oldest events instead of
    slowing down the publisher.
    """

    def __init__(self, maxsize: int) -> None:
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize)
        self.dropped = 0

    def offer(self, event: Event) -> None:
        if self._queue.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
            self.dropped += 1
        self._queue.put_nowait(event)

    async def get(self) -> Event:
        return await self._queue.get()

    def __aiter__(self) -> AsyncIterator[Event]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[Event]:
        while True:
            yield await self._queue.get()


class EventBus:
    def __init__(self, *, queue_size: int = 1000) -> None:
        self._subscribers: set[Subscription] = set()
        self._queue_size = queue_size

    def publish(self, type_: str, **data: Any) -> Event:
        event = Event(type_, data)
        for subscriber in tuple(self._subscribers):
            subscriber.offer(event)
        return event

    @contextlib.contextmanager
    def subscribe(self):  # type: ignore[no-untyped-def]
        subscription = Subscription(self._queue_size)
        self._subscribers.add(subscription)
        try:
            yield subscription
        finally:
            self._subscribers.discard(subscription)
            if subscription.dropped:
                log.debug("subscriber dropped %d events", subscription.dropped)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
