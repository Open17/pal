"""Composition root: builds every service and runs them together."""

from __future__ import annotations

import asyncio
import contextlib
import shutil
import signal
from dataclasses import replace
from pathlib import Path

from pal import __version__
from pal.api import ApiContext, ApiServer, create_app, load_or_create_token
from pal.bots import (
    BotAgent,
    BotStateStore,
    BotTeam,
    ClientFactory,
    Greeter,
    ModelGreeter,
    SessionOptionsBuilder,
    auth_status,
    default_client_factory,
    scrub_api_credentials,
)
from pal.config import (
    BOTS_DIR_NAME,
    USER_ID,
    BotDefinition,
    ConfigError,
    PalConfig,
    new_bot_id,
    save_bot,
    validate_color,
)
from pal.displays import DisplayBackend, DisplayManager, VncProxy, create_backend
from pal.log import get_logger
from pal.memory import MemoryService
from pal.messaging import ConversationLog, EventBus, EventType, Messenger, conversation_id
from pal.tools import ToolProvider, ToolRegistry
from pal.tools.browser import Browsers, BrowserTools, LoginSync
from pal.tools.builtin import DisplayTools, MemoryTools, TeamTools
from pal.tools.computer import ComputerTools

log = get_logger(__name__)


class PalRuntime:
    def __init__(
        self,
        config: PalConfig,
        *,
        client_factory: ClientFactory = default_client_factory,
        display_backend: DisplayBackend | None = None,
        extra_tools: list[ToolProvider] | None = None,
        greeter: Greeter | None = None,
    ) -> None:
        self.config = config
        paths = config.paths

        self.bus = EventBus()
        self.messenger = Messenger(ConversationLog(paths.conversations), self.bus)
        self.memory = MemoryService(paths.memory)
        self.displays = DisplayManager(
            config.displays,
            display_backend or create_backend(config.displays, paths.config / "displays"),
            paths.state / "displays.json",
            self.bus,
        )
        self.displays.register(config.bot_ids)
        self.state = BotStateStore(paths.state / "bots.json")
        self.team = BotTeam(config, self.state, self.messenger, self.bus)
        self.displays.is_working = self.team.is_working

        self.browsers = Browsers(self.displays, paths.data / "cache" / "screens")
        # Browsers quit cleanly before their display stops, keeping their tabs.
        self.displays.before_stop.append(self.browsers.quit)
        self.logins = LoginSync(
            self.browsers, self.displays, paths.data / "browsers" / "logins.json"
        )
        self.tools = ToolRegistry(
            [
                MemoryTools(self.memory),
                TeamTools(self.team),
                DisplayTools(self.displays),
                ComputerTools(self.displays, paths.data / "cache" / "screens"),
                BrowserTools(self.browsers),
            ]
        )
        for provider in extra_tools or ():
            self.tools.add(provider)

        self._client_factory = client_factory
        self._greeter = greeter or ModelGreeter(
            paths.secrets, paths.workspaces, cli_path=config.agent.cli_path
        )
        self._options = SessionOptionsBuilder(
            config,
            self.tools,
            self.memory,
            self.displays,
            team=lambda: [agent.definition for agent in self.team.agents],
        )
        self.team.add(self._make_agent(bot) for bot in config.bots)

        self.vnc = VncProxy(self.displays, bind_host=config.displays.vnc_bind_host)
        self.api: ApiServer | None = None
        self._background: list[asyncio.Task[None]] = []

    def _make_agent(self, bot: BotDefinition) -> BotAgent:
        options = self._options
        return BotAgent(
            bot,
            options_factory=lambda d, s, resume: options.build(d, s, resume=resume),
            settings=lambda bot_id=bot.id: self.team.model_settings(bot_id),
            state=self.state,
            messenger=self.messenger,
            bus=self.bus,
            display_name=self.team.display_name,
            client_factory=self._client_factory,
            greeter=self._greeter,
        )

    # -- the team --------------------------------------------------------------

    @property
    def _bots_dir(self) -> Path:
        return self.config.paths.config / BOTS_DIR_NAME

    async def add_bot(
        self, name: str, *, role: str = "", persona: str = "", color: str | None = None
    ) -> BotAgent:
        """Create a bot: it gets a definition file, a display, and starts listening."""

        name = name.strip()
        if not name:
            raise ConfigError("a bot needs a name")
        taken = {agent.id for agent in self.team.agents} | {
            path.stem for path in self._bots_dir.glob("*.toml")
        }
        bot = BotDefinition(
            id=new_bot_id(name, taken),
            name=name,
            role=role.strip(),
            persona=persona.strip(),
            color=validate_color(color, where="new bot") if color else None,
        )
        save_bot(self._bots_dir, bot)
        self.config = replace(self.config, bots=(*self.config.bots, bot))
        self.displays.register([bot.id])
        await self.vnc.add(bot.id)
        agent = self._make_agent(bot)
        self.team.add([agent])
        # Announced before it starts, so listeners know the bot before its status.
        self.bus.publish(EventType.BOT_ADDED, bot=bot.id, **agent.to_dict())
        agent.start()
        agent.greet()
        log.info("added bot %s (%s)", bot.id, bot.name)
        return agent

    def edit_bot(
        self,
        bot_id: str,
        *,
        name: str | None = None,
        role: str | None = None,
        persona: str | None = None,
        color: str | None = None,
    ) -> BotAgent:
        """Change a bot's name, role, instructions, or color, and save them to its
        definition file. Its id stays, so its chats and memory carry over."""

        agent = self.team.agent(bot_id)
        changes: dict[str, str | None] = {}
        if name is not None:
            if not name.strip():
                raise ConfigError("a bot needs a name")
            changes["name"] = name.strip()
        if role is not None:
            changes["role"] = role.strip()
        if persona is not None:
            changes["persona"] = persona.strip()
        if color is not None:
            changes["color"] = validate_color(color, where=bot_id)
        bot = replace(agent.definition, **changes)
        save_bot(self._bots_dir, bot)
        agent.definition = bot
        self.config = replace(
            self.config, bots=tuple(bot if b.id == bot_id else b for b in self.config.bots)
        )
        if changes.keys() - {"color"}:
            # Prompts name every teammate, so each bot picks the change up next turn.
            for member in self.team.agents:
                member.refresh_prompt()
        self.bus.publish(EventType.BOT_UPDATED, bot=bot_id, **agent.to_dict())
        return agent

    async def remove_bot(self, bot_id: str) -> None:
        """Remove a bot and everything that was its own, so a new bot with the same
        name starts fresh: its conversations (with the user and with teammates),
        session, model choice, private knowledge, display windows and browser
        profile. Shared team memory and files in the team's folder stay."""

        if len(self.team.agents) <= 1:
            raise ConfigError("Pal needs at least one bot")
        agent = self.team.remove(bot_id)
        await agent.stop()
        (self._bots_dir / f"{bot_id}.toml").unlink(missing_ok=True)
        self.config = replace(
            self.config, bots=tuple(b for b in self.config.bots if b.id != bot_id)
        )
        await self.vnc.remove(bot_id)
        await self.displays.unregister(bot_id)  # also quits its browser first
        await self.messenger.log.delete_with(bot_id)
        self.state.forget(bot_id)
        await self.memory.forget_bot(bot_id)
        await asyncio.to_thread(
            shutil.rmtree, self.config.paths.data / "browsers" / bot_id, ignore_errors=True
        )
        self.bus.publish(EventType.BOT_REMOVED, bot=bot_id)
        log.info("removed bot %s", bot_id)

    def _prepare_directories(self) -> None:
        paths = self.config.paths
        for directory in (paths.workspaces, paths.data, paths.state):
            directory.mkdir(parents=True, exist_ok=True)

    async def _greet_new_chats(self) -> None:
        """Every bot says hello first: those you've never talked to do it now."""

        for agent in self.team.agents:
            chat = conversation_id(USER_ID, agent.id)
            if not await self.messenger.log.read(chat, limit=1):
                agent.greet()

    async def start(self) -> None:
        scrub_api_credentials()
        self._prepare_directories()
        status = auth_status(self.config.paths.secrets)
        if status.ok:
            log.info("signed in via %s", status.detail)
        else:
            log.warning("bots cannot answer yet: %s", status.detail)

        await self.displays.restore()
        await self.vnc.start()
        self.team.start()
        await self._greet_new_chats()

        ctx = ApiContext(
            config=self.config,
            team=self.team,
            memory=self.memory,
            messenger=self.messenger,
            displays=self.displays,
            bus=self.bus,
            api_token=load_or_create_token(self.config.paths.secrets),
            auth_status=lambda: auth_status(self.config.paths.secrets),
            version=__version__,
            bots=self,
        )
        self.api = ApiServer(create_app(ctx), self.config.api.host, self.config.api.port)
        await self.api.start()
        self._background.append(
            asyncio.create_task(self.displays.run_idle_monitor(), name="display-idle-monitor")
        )
        self._background.append(asyncio.create_task(self.logins.run(), name="login-sync"))
        names = ", ".join(agent.id for agent in self.team.agents) or "none yet"
        log.info("Pal %s running with bots: %s", __version__, names)

    async def stop(self) -> None:
        # The computer may be shutting down: remember what's open to reopen it,
        # and quit the browsers so they keep their tabs. (Not when only the
        # runtime restarts: its displays and browsers carry on.)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self.displays.save_windows(), 30)
            if await _computer_shutting_down():
                await asyncio.wait_for(
                    asyncio.gather(
                        *(
                            self.browsers.quit(display.owner)
                            for display in self.displays.all()
                            if display.state == "running"  # asleep, they're frozen
                        )
                    ),
                    30,
                )
        for task in self._background:
            task.cancel()
        for task in self._background:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._background.clear()
        if self.api is not None:
            await self.api.stop()
        await self.team.stop()
        await self.browsers.close()
        await self.vnc.close()
        log.info("Pal stopped")

    async def run_forever(self) -> None:
        """Run until SIGINT or SIGTERM."""

        stopping = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stopping.set)
        await self.start()
        try:
            await stopping.wait()
        finally:
            await self.stop()


async def _computer_shutting_down() -> bool:
    try:
        process = await asyncio.create_subprocess_exec(
            "systemctl", "is-system-running", stdout=asyncio.subprocess.PIPE
        )
        output, _ = await process.communicate()
    except OSError:
        return False
    return output.decode().strip() == "stopping"
