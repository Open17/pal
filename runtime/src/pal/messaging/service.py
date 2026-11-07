"""Records messages and announces them on the event bus."""

from __future__ import annotations

from .events import EventBus, EventType
from .log import ConversationLog
from .models import Message


class Messenger:
    def __init__(self, log: ConversationLog, bus: EventBus) -> None:
        self.log = log
        self.bus = bus

    async def record(self, message: Message) -> Message:
        await self.log.append(message)
        self.bus.publish(EventType.MESSAGE_CREATED, message=message.to_dict())
        return message
