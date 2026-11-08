"""Composition root: builds every service and runs them together."""

from __future__ import annotations

import asyncio
import contextlib
import signal

from pal import __version__
from pal.api import ApiContext, ApiServer, create_app, load_or_create_token
from pal.bots import (
    BotAgent,
    BotStateStore,
    BotTeam,
    ClientFactory,
    SessionOptionsBuilder,
    auth_status,
    default_client_factory,
    scrub_api_credentials,
)
from pal.config import PalConfig
from pal.displays import DisplayBackend, DisplayManager, VncProxy, create_backend
from pal.log import get_logger
from pal.memory import MemoryService
from pal.messaging import ConversationLog, EventBus, Messenger
from pal.tools import ToolProvider, ToolRegistry
from pal.tools.browser import BrowserTools, SharedBrowser
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

        self.browser = SharedBrowser(
            self.displays, paths.data / "browser", paths.shared_workspace / "downloads"
        )
        self.tools = ToolRegistry(
            [
                MemoryTools(self.memory),
                TeamTools(self.team),
                DisplayTools(self.displays),
                ComputerTools(self.displays, paths.data / "cache" / "screens"),
                BrowserTools(self.browser),
            ]
        )
        for provider in extra_tools or ():
            self.tools.add(provider)

        options = SessionOptionsBuilder(config, self.tools, self.memory, self.displays)
        self.team.add(
            BotAgent(
                bot,
                options_factory=lambda d, s, resume: options.build(d, s, resume=resume),
                settings=lambda bot_id=bot.id: self.team.model_settings(bot_id),
                state=self.state,
                messenger=self.messenger,
                bus=self.bus,
                display_name=self.team.display_name,
                client_factory=client_factory,
            )
            for bot in config.bots
        )

        self.vnc = VncProxy(self.displays, bind_host=config.displays.vnc_bind_host)
        self.api: ApiServer | None = None
        self._background: list[asyncio.Task[None]] = []

    def _prepare_directories(self) -> None:
        paths = self.config.paths
        for directory in (paths.workspaces, paths.shared_workspace, paths.data, paths.state):
            directory.mkdir(parents=True, exist_ok=True)
        for bot_id in self.config.bot_ids:
            paths.bot_workspace(bot_id).mkdir(exist_ok=True)

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
        )
        self.api = ApiServer(create_app(ctx), self.config.api.host, self.config.api.port)
        await self.api.start()
        self._background.append(
            asyncio.create_task(self.displays.run_idle_monitor(), name="display-idle-monitor")
        )
        log.info("Pal %s running with bots: %s", __version__, ", ".join(self.config.bot_ids))

    async def stop(self) -> None:
        for task in self._background:
            task.cancel()
        for task in self._background:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._background.clear()
        if self.api is not None:
            await self.api.stop()
        await self.team.stop()
        await self.browser.close()
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
