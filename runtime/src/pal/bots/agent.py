"""One bot: an agent session plus an inbox of messages to work through.

Each bot keeps a single long-lived agent session, so everything it hears —
from the user or from teammates — lands in one continuous context. Messages
are handled one at a time in arrival order.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    StreamEvent,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from pal.config import BotDefinition, ModelSettings
from pal.log import get_logger
from pal.messaging import EventBus, EventType, Message, Messenger, new_id
from pal.tools.builtin import TeamMessagingError

from .prompts import frame_message
from .state import BotStateStore

log = get_logger(__name__)

BotStatus = Literal["offline", "idle", "busy", "error"]
_TOOL_INPUT_PREVIEW = 500


class AgentClient(Protocol):
    """The part of the agent SDK client a bot uses."""

    async def connect(self, prompt: str | None = None) -> None: ...
    async def query(self, prompt: str) -> None: ...
    def receive_response(self) -> AsyncIterator[Any]: ...
    async def interrupt(self) -> None: ...
    async def disconnect(self) -> None: ...


ClientFactory = Callable[[ClaudeAgentOptions], AgentClient]
OptionsFactory = Callable[[BotDefinition, ModelSettings, str | None], ClaudeAgentOptions]


def default_client_factory(options: ClaudeAgentOptions) -> AgentClient:
    return ClaudeSDKClient(options=options)


class TurnError(RuntimeError):
    pass


@dataclass
class WorkItem:
    message: Message
    #: Resolved with the bot's answer when the sender is waiting for it.
    reply: asyncio.Future[str] | None = None
    #: Bots further up the conversation that are waiting on this one.
    chain: tuple[str, ...] = ()


@dataclass
class TurnOutcome:
    text: str
    session_id: str | None = None
    cost_usd: float | None = None
    num_turns: int | None = None
    tools_used: list[str] = field(default_factory=list)


class BotAgent:
    def __init__(
        self,
        definition: BotDefinition,
        *,
        options_factory: OptionsFactory,
        settings: Callable[[], ModelSettings],
        state: BotStateStore,
        messenger: Messenger,
        bus: EventBus,
        display_name: Callable[[str], str],
        client_factory: ClientFactory = default_client_factory,
    ) -> None:
        self.definition = definition
        self._options_factory = options_factory
        self._settings = settings
        self._state = state
        self._messenger = messenger
        self._bus = bus
        self._display_name = display_name
        self._client_factory = client_factory

        self.status: BotStatus = "offline"
        self.last_error: str | None = None
        self._inbox: asyncio.Queue[WorkItem] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        self._client: AgentClient | None = None
        self._client_settings: ModelSettings | None = None
        self._current: WorkItem | None = None

    @property
    def id(self) -> str:
        return self.definition.id

    @property
    def current_chain(self) -> tuple[str, ...]:
        """The waiting chain of the message being handled right now."""

        return self._current.chain if self._current else ()

    @property
    def queued(self) -> int:
        return self._inbox.qsize()

    @property
    def model_settings(self) -> ModelSettings:
        return self._settings()

    # -- lifecycle -------------------------------------------------------

    def start(self) -> None:
        if self._worker is None:
            self._worker = asyncio.create_task(self._work(), name=f"bot-{self.id}")
            self._set_status("idle")

    async def stop(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker
            self._worker = None
        while not self._inbox.empty():
            self._fail(self._inbox.get_nowait(), f"{self.definition.name} shut down")
        await self._disconnect()
        self._set_status("offline")

    def submit(self, item: WorkItem) -> None:
        self._inbox.put_nowait(item)

    async def interrupt(self) -> bool:
        if self.status != "busy" or self._client is None:
            return False
        await self._client.interrupt()
        return True

    async def reset_session(self) -> None:
        """Forget the current conversation context and start fresh next turn."""

        await self._disconnect()
        self._state.set_session_id(self.id, None)

    def to_dict(self) -> dict[str, Any]:
        settings = self.model_settings
        return {
            "id": self.id,
            "name": self.definition.name,
            "role": self.definition.role,
            "color": self.definition.color,
            "status": self.status,
            "queued": self.queued,
            "model": settings.model,
            "effort": settings.effort,
            "session_id": self._state.session_id(self.id),
            "last_error": self.last_error,
        }

    # -- work loop ---------------------------------------------------------

    async def _work(self) -> None:
        while True:
            item = await self._inbox.get()
            try:
                await self._handle(item)
            except asyncio.CancelledError:
                self._fail(item, f"{self.definition.name} shut down")
                raise
            except Exception:  # never let one message kill the bot
                log.exception("%s: unexpected failure handling %s", self.id, item.message.id)

    async def _handle(self, item: WorkItem) -> None:
        self._current = item
        self._set_status("busy")
        turn_id = new_id("turn")
        prompt = frame_message(item.message, self._display_name(item.message.sender))
        error: str | None = None
        try:
            outcome = await self._run_turn(prompt, turn_id)
            text = outcome.text.strip() or "(no response)"
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("%s: turn %s failed", self.id, turn_id)
            await self._disconnect()
            error = str(exc) or exc.__class__.__name__
            text = f"Sorry, something went wrong while I was working on that: {error}"
            outcome = TurnOutcome(text)
        finally:
            self._current = None

        incoming = item.message
        reply = Message(
            sender=self.id,
            recipient=incoming.sender,
            content=text,
            kind="chat" if incoming.kind == "chat" else "reply",
            reply_to=incoming.id,
            metadata={
                "turn_id": turn_id,
                "error": error is not None,
                "delivered": incoming.kind != "notice",
            },
        )
        await self._messenger.record(reply)
        if item.reply is not None and not item.reply.done():
            if error is not None:
                item.reply.set_exception(
                    TeamMessagingError(f"{self.definition.name} failed to answer: {error}")
                )
            else:
                item.reply.set_result(text)
        self._bus.publish(
            EventType.BOT_TURN_COMPLETED,
            bot=self.id,
            turn_id=turn_id,
            message_id=reply.id,
            error=error,
            cost_usd=outcome.cost_usd,
            num_turns=outcome.num_turns,
            tools_used=outcome.tools_used,
        )
        self.last_error = error
        self._set_status("error" if error else "idle")

    async def _run_turn(self, prompt: str, turn_id: str) -> TurnOutcome:
        client = await self._ensure_client()
        await client.query(prompt)
        return await self._consume(client, turn_id)

    async def _consume(self, client: AgentClient, turn_id: str) -> TurnOutcome:
        outcome = TurnOutcome(text="")
        segment: list[str] = []  # text after the most recent tool call
        tool_names: dict[str, str] = {}
        async for message in client.receive_response():
            if isinstance(message, StreamEvent):
                delta = _text_delta(message.event)
                if delta:
                    self._bus.publish(
                        EventType.BOT_TEXT_DELTA, bot=self.id, turn_id=turn_id, text=delta
                    )
            elif isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        segment.append(block.text)
                    elif isinstance(block, ThinkingBlock) and block.thinking:
                        self._bus.publish(
                            EventType.BOT_THINKING,
                            bot=self.id,
                            turn_id=turn_id,
                            text=block.thinking,
                        )
                    elif isinstance(block, ToolUseBlock):
                        segment.clear()
                        tool_names[block.id] = block.name
                        outcome.tools_used.append(block.name)
                        self._bus.publish(
                            EventType.BOT_TOOL_STARTED,
                            bot=self.id,
                            turn_id=turn_id,
                            tool_use_id=block.id,
                            tool=block.name,
                            input=_preview(block.input),
                        )
            elif isinstance(message, UserMessage) and isinstance(message.content, list):
                for block in message.content:
                    if isinstance(block, ToolResultBlock):
                        self._bus.publish(
                            EventType.BOT_TOOL_FINISHED,
                            bot=self.id,
                            turn_id=turn_id,
                            tool_use_id=block.tool_use_id,
                            tool=tool_names.get(block.tool_use_id),
                            is_error=bool(block.is_error),
                        )
            elif isinstance(message, ResultMessage):
                outcome.session_id = message.session_id
                outcome.cost_usd = message.total_cost_usd
                outcome.num_turns = message.num_turns
                if message.session_id:
                    self._state.set_session_id(self.id, message.session_id)
                if message.is_error and message.terminal_reason not in (
                    "aborted_streaming",
                    "aborted_tools",
                ):
                    detail = "; ".join(message.errors or []) or message.subtype
                    raise TurnError(detail)
                outcome.text = message.result or "".join(segment)
        if not outcome.text:
            outcome.text = "".join(segment)
        return outcome

    # -- session management ---------------------------------------------------

    async def _ensure_client(self) -> AgentClient:
        settings = self.model_settings
        if self._client is not None and settings != self._client_settings:
            # Model and effort are fixed per session; reconnect and resume so
            # the conversation carries over with the new settings.
            log.info("%s: switching to %s (%s effort)", self.id, settings.model, settings.effort)
            await self._disconnect()
        if self._client is None:
            self._client = await self._connect(settings)
            self._client_settings = settings
        return self._client

    async def _connect(self, settings: ModelSettings) -> AgentClient:
        session_id = self._state.session_id(self.id)
        client = self._client_factory(self._options_factory(self.definition, settings, session_id))
        try:
            await client.connect()
        except Exception:
            if session_id is None:
                raise
            log.warning("%s: could not resume session %s; starting fresh", self.id, session_id)
            with contextlib.suppress(Exception):
                await client.disconnect()
            self._state.set_session_id(self.id, None)
            client = self._client_factory(self._options_factory(self.definition, settings, None))
            await client.connect()
        return client

    async def _disconnect(self) -> None:
        client, self._client, self._client_settings = self._client, None, None
        if client is not None:
            try:
                await client.disconnect()
            except Exception:
                log.debug("%s: error while disconnecting", self.id, exc_info=True)

    # -- helpers -------------------------------------------------------------

    def _fail(self, item: WorkItem, reason: str) -> None:
        if item.reply is not None and not item.reply.done():
            item.reply.set_exception(TeamMessagingError(reason))

    def _set_status(self, status: BotStatus) -> None:
        if status != self.status:
            self.status = status
            self._bus.publish(EventType.BOT_STATUS, bot=self.id, status=status, queued=self.queued)


def _text_delta(event: dict[str, Any]) -> str | None:
    if event.get("type") != "content_block_delta":
        return None
    delta = event.get("delta") or {}
    return delta.get("text") if delta.get("type") == "text_delta" else None


def _preview(value: Any) -> Any:
    text = repr(value)
    return value if len(text) <= _TOOL_INPUT_PREVIEW else text[:_TOOL_INPUT_PREVIEW] + "…"
