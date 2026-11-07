"""The team's shared browser.

One Chromium with one profile runs on its own display, so a login made by
any bot — or by the user, watching that display from the app — works for
every bot. Each bot gets its own window and only ever sees its own tabs.

The browser is started with ``pal-open``, so it lives in its display's slice
and survives runtime restarts; bots drive it over the DevTools protocol, which
works whether or not their window is in front.
"""

from __future__ import annotations

import asyncio
import shlex
from pathlib import Path

import aiohttp
from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from pal.config import BROWSER_ID
from pal.displays import DisplayManager
from pal.log import get_logger

from ..computer.desktop import Desktop, DesktopError

log = get_logger(__name__)

DEBUG_PORT = 9222
CHROMIUM = "chromium"


class BrowserError(RuntimeError):
    """Shown to the bot as a tool error."""


def chromium_command(port: int, profile: Path) -> list[str]:
    return [
        CHROMIUM,
        f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--password-store=basic",
        "--disable-features=Translate,MediaRouter",
        # Bots work in windows that are often behind others; keep them running.
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--start-maximized",
    ]


class SharedBrowser:
    def __init__(self, displays: DisplayManager, profile: Path, downloads: Path) -> None:
        self.displays = displays
        self.profile = profile
        self.downloads = downloads
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._lock = asyncio.Lock()
        self._tabs: dict[str, list[Page]] = {}
        self._current: dict[str, Page] = {}

    # -- connection ------------------------------------------------------------

    async def context(self) -> BrowserContext:
        """Connect to the shared browser, starting it (and its display) if needed."""

        await self.displays.ensure_awake(BROWSER_ID)
        async with self._lock:
            if (
                self._context is not None
                and self._browser is not None
                and self._browser.is_connected()
            ):
                return self._context
            self._forget_pages()
            endpoint = f"http://127.0.0.1:{DEBUG_PORT}"
            if not await _devtools_ready(endpoint):
                await self._launch(endpoint)
            if self._playwright is None:
                self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.connect_over_cdp(endpoint)
            contexts = self._browser.contexts
            self._context = contexts[0] if contexts else await self._browser.new_context()
            self._context.on("page", self._adopt_popup)
            await self._set_download_folder()
            log.info("connected to the shared browser on %s", endpoint)
            return self._context

    async def _launch(self, endpoint: str) -> None:
        self.profile.mkdir(parents=True, exist_ok=True)
        display = self.displays.get(BROWSER_ID)
        desktop = Desktop(display.name, owner=BROWSER_ID, scratch=self.profile)
        try:
            await desktop.open(shlex.join(chromium_command(DEBUG_PORT, self.profile)))
        except DesktopError as exc:
            raise BrowserError(f"could not start the browser: {exc}") from exc
        for _ in range(60):
            if await _devtools_ready(endpoint):
                return
            await asyncio.sleep(0.5)
        raise BrowserError("the browser did not start within 30 seconds")

    async def _set_download_folder(self) -> None:
        assert self._browser is not None
        self.downloads.mkdir(parents=True, exist_ok=True)
        try:
            cdp = await self._browser.new_browser_cdp_session()
            await cdp.send(
                "Browser.setDownloadBehavior",
                {"behavior": "allow", "downloadPath": str(self.downloads), "eventsEnabled": True},
            )
        except Exception as exc:  # downloads still work, to the default folder
            log.warning("could not set the browser's download folder: %s", exc)

    def _forget_pages(self) -> None:
        self._tabs.clear()
        self._current.clear()

    # -- tabs ------------------------------------------------------------------

    def tabs(self, bot_id: str) -> list[Page]:
        tabs = [page for page in self._tabs.get(bot_id, []) if not page.is_closed()]
        self._tabs[bot_id] = tabs
        return tabs

    async def page(self, bot_id: str) -> Page:
        """The tab the bot is working in, opening its window if it has none."""

        await self.context()
        current = self._current.get(bot_id)
        if current is not None and not current.is_closed():
            self.displays.touch(BROWSER_ID)
            return current
        tabs = self.tabs(bot_id)
        if tabs:
            self._current[bot_id] = tabs[-1]
            return tabs[-1]
        return await self.new_tab(bot_id)

    async def new_tab(self, bot_id: str, url: str = "about:blank") -> Page:
        """Open a tab in the bot's window (opening the window first if needed)."""

        context = await self.context()
        tabs = self.tabs(bot_id)
        async with context.expect_page() as created:
            if tabs:
                # A tab opened from one of the bot's pages joins that page's window.
                await tabs[-1].evaluate("url => { window.open(url, '_blank') }", url)
            else:
                assert self._browser is not None
                cdp = await self._browser.new_browser_cdp_session()
                await cdp.send("Target.createTarget", {"url": url, "newWindow": True})
        page = await created.value
        self._claim(bot_id, page)
        return page

    def select(self, bot_id: str, page: Page) -> None:
        self._current[bot_id] = page

    async def close_tab(self, bot_id: str, page: Page) -> None:
        await page.close()
        tabs = self.tabs(bot_id)
        if self._current.get(bot_id) is page:
            self._current.pop(bot_id, None)
            if tabs:
                self._current[bot_id] = tabs[-1]

    def _claim(self, bot_id: str, page: Page) -> None:
        for owner, tabs in self._tabs.items():
            if owner != bot_id and page in tabs:
                tabs.remove(page)
        if page not in self._tabs.setdefault(bot_id, []):
            self._tabs[bot_id].append(page)
        self._current[bot_id] = page

    def owner(self, page: Page) -> str | None:
        return next((bot for bot, tabs in self._tabs.items() if page in tabs), None)

    def _adopt_popup(self, page: Page) -> None:
        """Tabs a page opens (target=_blank links, pop-ups) belong to that page's bot."""

        async def adopt() -> None:
            try:
                opener = await page.opener()
            except Exception:
                return
            bot = self.owner(opener) if opener is not None else None
            if bot is not None and self.owner(page) is None:
                self._tabs[bot].append(page)

        asyncio.get_running_loop().create_task(adopt())

    async def close(self) -> None:
        """Disconnect. The browser keeps running, with every tab and login."""

        self._browser = self._context = None
        self._forget_pages()
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None


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
