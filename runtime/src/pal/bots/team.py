"""The bot team: routes messages and owns model settings for every bot."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable

from pal.config import USER_ID, Effort, ModelSettings, PalConfig, validate_effort
from pal.log import get_logger
from pal.messaging import EventBus, EventType, Message, Messenger
from pal.tools.builtin import TeamGateway, TeamMember, TeamMessagingError

from .agent import BotAgent, WorkItem
from .state import BotStateStore, ModelOverride

log = get_logger(__name__)


class UnknownBotError(KeyError):
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

    # -- membership --------------------------------------------------------

    def add(self, agents: Iterable[BotAgent]) -> None:
        for agent in agents:
            self._agents[agent.id] = agent

    def agent(self, bot_id: str) -> BotAgent:
        try:
            return self._agents[bot_id]
        except KeyError:
            raise UnknownBotError(bot_id) from None

    @property
    def agents(self) -> list[BotAgent]:
        return list(self._agents.values())

    def display_name(self, participant: str) -> str:
        if participant == USER_ID:
            return "the user"
        agent = self._agents.get(participant)
        return agent.definition.name if agent else participant

    def start(self) -> None:
        for agent in self._agents.values():
            agent.start()

    async def stop(self) -> None:
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

    async def send_from_user(self, bot_id: str, content: str) -> Message:
        agent = self.agent(bot_id)
        if not content.strip():
            raise ValueError("message is empty")
        message = await self.messenger.record(
            Message(sender=USER_ID, recipient=bot_id, content=content)
        )
        agent.submit(WorkItem(message))
        return message

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
