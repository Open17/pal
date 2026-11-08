"""Each bot's own Chromium, driven over the DevTools protocol.

Every display owner (each bot, and the user) has a Chromium of their own, on
their own display and with their own profile, so any number of them can
browse at once. The ``pal-chromium`` launcher, which is what ``chromium``
runs on the desktops, opens it with a remote-debugging port derived from the
display number; the tools connect to that port, starting the browser first if
it isn't running. Logins are carried between the browsers by
:class:`~pal.tools.browser.sync.LoginSync`.

Browsers are started with ``pal-open``, so they live in their display's slice
and survive runtime restarts.
"""

from __future__ import annotations

import asyncio
import re
from collections import defaultdict
from collections.abc import Awaitable, Callable
from pathlib import Path

import aiohttp
from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from pal.displays import Display, DisplayManager
from pal.log import get_logger

from ..computer.desktop import Desktop, DesktopError

log = get_logger(__name__)

#: A display's browser listens on this plus the display number (``:10`` → 9310).
DEBUG_PORT_BASE = 9300
LAUNCHER = "pal-chromium"

ConnectHook = Callable[[str, BrowserContext], Awaitable[None]]


class BrowserError(RuntimeError):
    """Shown to the bot as a tool error."""


def debug_port(display: Display) -> int:
    return DEBUG_PORT_BASE + display.number


def normalize_url(url: str) -> str:
    """``example.com`` → ``https://example.com``; URLs with a scheme are kept."""

    url = url.strip()
    if not url:
        raise BrowserError("no address given")
    if not re.match(r"^[a-z][a-z0-9+.-]*:", url, re.IGNORECASE):
        url = "https://" + url
    return url


class Browsers:
    """Connections to every display owner's browser."""

    def __init__(self, displays: DisplayManager, scratch: Path) -> None:
        self.displays = displays
        self.scratch = scratch
        self._playwright: Playwright | None = None
        self._browsers: dict[str, Browser] = {}
        self._contexts: dict[str, BrowserContext] = {}
        self._current: dict[str, Page] = {}
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._on_connect: list[ConnectHook] = []

    def on_connect(self, hook: ConnectHook) -> None:
        """Call ``hook(owner, context)`` each time a browser is (re)connected."""

        self._on_connect.append(hook)

    # -- connection ------------------------------------------------------------

    def endpoint(self, owner: str) -> str:
        return f"http://127.0.0.1:{debug_port(self.displays.get(owner))}"

    def connected(self, owner: str) -> BrowserContext | None:
        browser = self._browsers.get(owner)
        if browser is None or not browser.is_connected():
            return None
        return self._contexts.get(owner)

    async def context(self, owner: str, *, launch: bool = True) -> BrowserContext | None:
        """The owner's browser, starting it (and waking their display) if needed.

        With ``launch=False`` this only connects to a browser that is already
        running, and returns None otherwise.
        """

        if launch:
            await self.displays.ensure_awake(owner)
        async with self._locks[owner]:
            if (context := self.connected(owner)) is not None:
                return context
            self._forget(owner)
            endpoint = self.endpoint(owner)
            if not await _devtools_ready(endpoint):
                if not launch:
                    return None
                await self._launch(owner, endpoint)
            if self._playwright is None:
                self._playwright = await async_playwright().start()
            browser = await self._playwright.chromium.connect_over_cdp(endpoint)
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            self._browsers[owner], self._contexts[owner] = browser, context
            log.info("connected to %s's browser on %s", owner, endpoint)
        for hook in self._on_connect:
            try:
                await hook(owner, context)
            except Exception:
                log.exception("browser connect hook failed for %s", owner)
        return context

    async def _launch(self, owner: str, endpoint: str) -> None:
        display = self.displays.get(owner)
        desktop = Desktop(display.name, owner=owner, scratch=self.scratch)
        try:
            await desktop.open(LAUNCHER)
        except DesktopError as exc:
            raise BrowserError(f"could not start your browser: {exc}") from exc
        for _ in range(60):
            if await _devtools_ready(endpoint):
                return
            await asyncio.sleep(0.5)
        raise BrowserError("your browser did not start within 30 seconds")

    def _forget(self, owner: str) -> None:
        self._browsers.pop(owner, None)
        self._contexts.pop(owner, None)
        self._current.pop(owner, None)

    async def close(self) -> None:
        """Disconnect. The browsers keep running, with every tab and login."""

        for owner in list(self._browsers):
            self._forget(owner)
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    # -- tabs ------------------------------------------------------------------

    async def _require(self, owner: str) -> BrowserContext:
        context = await self.context(owner)
        assert context is not None  # launch=True starts it or raises
        return context

    def tabs(self, owner: str) -> list[Page]:
        context = self.connected(owner)
        if context is None:
            return []
        return [page for page in context.pages if not page.is_closed()]

    async def page(self, owner: str) -> Page:
        """The tab the owner is working in, opening one if there is none."""

        await self._require(owner)
        current = self._current.get(owner)
        if current is not None and not current.is_closed():
            self.displays.touch(owner)
            return current
        tabs = self.tabs(owner)
        if tabs:
            self._current[owner] = tabs[-1]
            return tabs[-1]
        return await self.new_tab(owner)

    async def new_tab(self, owner: str, url: str = "about:blank") -> Page:
        """Open a tab next to the owner's current one (or in a new window)."""

        context = await self._require(owner)
        tabs = self.tabs(owner)
        if not tabs:
            page = await context.new_page()
        else:
            opener = self._current.get(owner)
            if opener is None or opener.is_closed():
                opener = tabs[-1]
            async with context.expect_page() as created:
                # A tab opened from a page joins that page's window.
                await opener.evaluate("url => { window.open(url, '_blank') }", url)
            page = await created.value
        self._current[owner] = page
        return page

    def select(self, owner: str, page: Page) -> None:
        self._current[owner] = page

    async def close_tab(self, owner: str, page: Page) -> None:
        await page.close()
        if self._current.get(owner) is page:
            self._current.pop(owner, None)
            tabs = self.tabs(owner)
            if tabs:
                self._current[owner] = tabs[-1]


async def _devtools_ready(endpoint: str) -> bool:
    try:
        timeout = aiohttp.ClientTimeout(total=2)
        async with (
            aiohttp.ClientSession(timeout=timeout) as http,
            http.get(f"{endpoint}/json/version") as response,
        ):
            return response.status == 200
    except (aiohttp.ClientError, TimeoutError, OSError):
        return False
