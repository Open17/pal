"""The bot team: routes messages and owns model settings for every bot."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable

from pal.config import USER_ID, Effort, ModelSettings, PalConfig, validate_effort
from pal.log import get_logger
from pal.messaging import (
    EventBus,
    EventType,
    Message,
    Messenger,
    clean_reaction,
    conversation_id,
    excerpt,
)
from pal.tools.builtin import TeamGateway, TeamMember, TeamMessagingError

from .agent import BotAgent, WorkItem
from .state import BotStateStore, ModelOverride

log = get_logger(__name__)


REACTION_DELAY_SECONDS = 2.5


class UnknownBotError(KeyError):
    pass


class UnknownMessageError(KeyError):
    pass


class BotTeam(TeamGateway):
    """Routes messages between the user and bots, and between bots.

    When a bot waits for another bot's answer, the team records who is
    waiting on whom. A request that would close a cycle in that graph would
    deadlock (every bot in the cycle waiting for the next), so it is refused
    with an explanation the bot can act on.
    """

    def __init__(
        self, config: PalConfig, state: BotStateStore, messenger: Messenger, bus: EventBus
    ) -> None:
        self.config = config
        self.state = state
        self.messenger = messenger
        self.bus = bus
        self._agents: dict[str, BotAgent] = {}
        self._waiting_on: dict[str, str] = {}
        #: How long the user's reaction settles before its bot is told, so
        #: trying a few in a row reaches it once, as the last one.
        self.reaction_delay = REACTION_DELAY_SECONDS
        self._pending_reactions: dict[str, asyncio.Task[None]] = {}
        #: The user's reaction each bot last heard about, by message id.
        self._told_reactions: dict[str, str] = {}

    # -- membership --------------------------------------------------------

    def add(self, agents: Iterable[BotAgent]) -> None:
        for agent in agents:
            self._agents[agent.id] = agent

    def remove(self, bot_id: str) -> BotAgent:
        """Take a bot off the team (the caller stops it)."""

        agent = self.agent(bot_id)
        del self._agents[bot_id]
        self._waiting_on.pop(bot_id, None)
        return agent

    def agent(self, bot_id: str) -> BotAgent:
        try:
            return self._agents[bot_id]
        except KeyError:
            raise UnknownBotError(bot_id) from None

    @property
    def agents(self) -> list[BotAgent]:
        return list(self._agents.values())

    def is_working(self, bot_id: str) -> bool:
        agent = self._agents.get(bot_id)
        return agent is not None and agent.status == "busy"

    def display_name(self, participant: str) -> str:
        if participant == USER_ID:
            return "the user"
        agent = self._agents.get(participant)
        return agent.definition.name if agent else participant

    def start(self) -> None:
        for agent in self._agents.values():
            agent.start()

    async def stop(self) -> None:
        await self._drop_pending_reactions()
        await asyncio.gather(*(agent.stop() for agent in self._agents.values()))

    # -- TeamGateway -------------------------------------------------------

    def roster(self) -> list[TeamMember]:
        members = []
        for agent in self._agents.values():
            status = agent.status
            if agent.id in self._waiting_on:
                status = f"waiting on {self._waiting_on[agent.id]}"
            elif agent.queued:
                status = f"{status}, {agent.queued} queued"
            members.append(
                TeamMember(agent.id, agent.definition.name, agent.definition.role, status)
            )
        return members

    async def send(
        self, sender: str, recipient: str, content: str, *, wait_for_reply: bool
    ) -> str | None:
        if recipient == sender:
            raise TeamMessagingError("You cannot message yourself.")
        if recipient not in self._agents:
            known = ", ".join(sorted(self._agents)) or "none"
            raise TeamMessagingError(f"There is no bot called {recipient!r} (teammates: {known}).")
        if not content.strip():
            raise TeamMessagingError("The message is empty.")

        chain = (*self._agents[sender].current_chain, sender) if sender in self._agents else ()
        if wait_for_reply:
            self._check_can_wait(sender, recipient, chain)

        message = await self.messenger.record(
            Message(
                sender=sender,
                recipient=recipient,
                content=content,
                kind="request" if wait_for_reply else "notice",
                metadata={"chain": list(chain)},
            )
        )
        target = self._agents[recipient]
        if not wait_for_reply:
            target.submit(WorkItem(message, None, chain))
            return None

        reply: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        target.submit(WorkItem(message, reply, chain))
        self._waiting_on[sender] = recipient
        self._publish_status(sender)
        timeout = self.config.messaging.reply_timeout_seconds
        try:
            return await asyncio.wait_for(asyncio.shield(reply), timeout)
        except TimeoutError:
            raise TeamMessagingError(
                f"{target.definition.name} did not answer within {timeout} seconds. Their "
                "answer will still be recorded in your conversation with them."
            ) from None
        finally:
            self._waiting_on.pop(sender, None)
            self._publish_status(sender)

    async def react(self, bot_id: str, emoji: str) -> Message:
        """A bot reacts to the message it is handling right now."""

        agent = self._agents.get(bot_id)
        target = agent.current_message if agent else None
        if agent is None or target is None:
            raise TeamMessagingError("There is no message to react to right now.")
        if target.kind == "reaction":
            raise TeamMessagingError(
                "You can't react to a reaction. Reply in words, or not at all."
            )
        try:
            emoji = clean_reaction(emoji, allow_empty=False)
        except ValueError as exc:
            raise TeamMessagingError(f"{exc}, like 👍.") from None
        reaction = await self._record_reaction(bot_id, target, emoji)
        agent.reacted(emoji)
        return reaction

    async def _record_reaction(self, sender: str, target: Message, emoji: str) -> Message:
        """Record a reaction in the target's conversation and tell its author.

        A bot hears about the user's reaction right away, in a turn of its own
        (see ``_tell_reaction``). Anything else it reads with its next message:
        a teammate's reaction, or the user taking one back.
        """

        recipient = target.recipient if target.sender == sender else target.sender
        quoted = excerpt(target.content)
        reaction = await self.messenger.record(
            Message(
                sender=sender,
                recipient=recipient,
                content=emoji,
                kind="reaction",
                reply_to=target.id,
                metadata={"quote": {"sender": target.sender, "content": quoted}},
            )
        )
        author = self._agents.get(target.sender)
        if author is None or target.sender == sender:
            return reaction
        if sender == USER_ID:
            pending = self._pending_reactions.pop(target.id, None)
            if pending is not None:
                pending.cancel()
            self._pending_reactions[target.id] = asyncio.create_task(
                self._tell_reaction(author, reaction), name=f"reaction-{target.id}"
            )
        else:
            who = self.display_name(sender)
            author.note(
                f'[{who} reacted {emoji} to your message: "{quoted}"]'
                if emoji
                else f'[{who} took back their reaction to your message: "{quoted}"]'
            )
        return reaction

    async def _tell_reaction(self, author: BotAgent, reaction: Message) -> None:
        """Once the user's reaction settles, give the bot a turn to respond to it."""

        target = reaction.reply_to or ""
        try:
            await asyncio.sleep(self.reaction_delay)
        except asyncio.CancelledError:
            return  # a newer reaction replaced this one
        self._pending_reactions.pop(target, None)
        told = self._told_reactions.get(target, "")
        if reaction.content == told:
            return  # back to what the bot already knows
        if reaction.content:
            self._told_reactions[target] = reaction.content
            author.submit(WorkItem(reaction))
        else:
            # Taking a reaction back rarely needs an answer: noted, not a turn.
            self._told_reactions.pop(target, None)
            quoted = reaction.metadata["quote"]["content"]
            author.note(f'[The user took back their {told} on your message: "{quoted}"]')

    async def _drop_pending_reactions(self) -> None:
        tasks = list(self._pending_reactions.values())
        self._pending_reactions.clear()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _check_can_wait(self, sender: str, recipient: str, chain: tuple[str, ...]) -> None:
        if len(chain) > self.config.messaging.max_chain_depth:
            raise TeamMessagingError(
                f"Too many bots are already waiting on each other ({' → '.join(chain)}). "
                "Finish this part yourself or send a message without waiting."
            )
        # Follow who the recipient is (transitively) waiting on.
        seen, current = [recipient], recipient
        while current in self._waiting_on:
            current = self._waiting_on[current]
            seen.append(current)
            if current == sender:
                path = " → ".join([sender, *seen])
                raise TeamMessagingError(
                    f"{self.display_name(recipient)} cannot answer right now because they are "
                    f"waiting on you ({path}). Answer their request first, or send this "
                    "without waiting for a reply."
                )
            if len(seen) > len(self._agents):
                break

    def _publish_status(self, bot_id: str) -> None:
        agent = self._agents.get(bot_id)
        if agent is not None:
            self.bus.publish(
                EventType.BOT_STATUS,
                bot=bot_id,
                status=agent.status,
                queued=agent.queued,
                waiting_on=self._waiting_on.get(bot_id),
            )

    # -- user messages -------------------------------------------------------

    async def send_from_user(
        self, bot_id: str, content: str, *, reply_to: str | None = None
    ) -> Message:
        """Send the user's message to a bot, optionally as a reply to an earlier
        message in their chat, which the bot sees quoted."""

        agent = self.agent(bot_id)
        if not content.strip():
            raise ValueError("message is empty")
        metadata = {}
        if reply_to is not None:
            quoted = await self.messenger.log.find(conversation_id(USER_ID, bot_id), reply_to)
            if quoted is None or quoted.kind == "reaction":
                raise UnknownMessageError(reply_to)
            metadata["quote"] = {"sender": quoted.sender, "content": excerpt(quoted.content, 300)}
        message = await self.messenger.record(
            Message(
                sender=USER_ID,
                recipient=bot_id,
                content=content,
                reply_to=reply_to,
                metadata=metadata,
            )
        )
        agent.submit(WorkItem(message))
        return message

    async def react_from_user(self, bot_id: str, message_id: str, emoji: str) -> Message:
        """The user reacts to a message in their chat with a bot; an empty emoji
        takes their reaction back. A reaction to the bot's own message reaches it
        a moment later, as a turn it can answer or let pass."""

        self.agent(bot_id)
        emoji = clean_reaction(emoji, allow_empty=True)
        target = await self.messenger.log.find(conversation_id(USER_ID, bot_id), message_id)
        if target is None or target.kind == "reaction":
            raise UnknownMessageError(message_id)
        return await self._record_reaction(USER_ID, target, emoji)

    # -- model settings ------------------------------------------------------

    def default_settings(self) -> ModelSettings:
        """Configured defaults with any runtime change from the app on top."""

        return self.state.defaults_override().apply(self.config.model)

    def model_settings(self, bot_id: str) -> ModelSettings:
        """Defaults, then the bot's configured override, then its runtime override."""

        definition = self.agent(bot_id).definition
        settings = definition.model_settings(self.default_settings())
        return self.state.bot_override(bot_id).apply(settings)

    def update_defaults(self, *, model: str | None = None, effort: Effort | None = None) -> None:
        current = self.state.defaults_override()
        self.state.set_defaults_override(_merge(current, model, effort))
        for agent in self._agents.values():
            self._announce_settings(agent.id)

    def update_bot(
        self, bot_id: str, *, model: str | None = None, effort: Effort | None = None
    ) -> ModelSettings:
        self.agent(bot_id)
        current = self.state.bot_override(bot_id)
        self.state.set_bot_override(bot_id, _merge(current, model, effort))
        return self._announce_settings(bot_id)

    def clear_bot_override(self, bot_id: str) -> ModelSettings:
        self.agent(bot_id)
        self.state.set_bot_override(bot_id, ModelOverride())
        return self._announce_settings(bot_id)

    def _announce_settings(self, bot_id: str) -> ModelSettings:
        settings = self.model_settings(bot_id)
        self.bus.publish(
            EventType.BOT_SETTINGS_CHANGED,
            bot=bot_id,
            model=settings.model,
            effort=settings.effort,
        )
        return settings


def _merge(current: ModelOverride, model: str | None, effort: Effort | None) -> ModelOverride:
    if effort is not None:
        validate_effort(effort, where="settings")
    return ModelOverride(model=model or current.model, effort=effort or current.effort)
