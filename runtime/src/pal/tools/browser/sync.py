"""Carry logins between everyone's browsers.

Each bot (and the user) has a browser of their own, but a site signed in to in
any of them should be signed in everywhere. Logins live in cookies, so every
couple of seconds this reads the cookies of every running browser, works out
what changed in each since it last looked, and copies those changes, sign-ins
and sign-outs alike, to all the others.

The merged cookies are also kept on disk, so a browser started later (or
started again) is signed in from its first page.

Only browsers on displays that are awake are read: a sleeping display's
browser is frozen. It catches up when its display wakes.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from playwright.async_api import BrowserContext

from pal.displays import DisplayManager
from pal.log import get_logger

from .session import Browsers

log = get_logger(__name__)

Cookie = dict[str, Any]
Key = tuple[str, str, str, str]

#: The cookie fields a browser accepts back.
FIELDS = ("name", "value", "domain", "path", "expires", "httpOnly", "secure", "sameSite")
#: How long a sign-out is remembered, so a browser that was off can't bring it back.
FORGET_SIGN_OUTS_AFTER = 7 * 24 * 3600
CALL_TIMEOUT = 5.0


def cookie_key(cookie: Cookie) -> Key:
    partition = cookie.get("partitionKey") or ""
    if isinstance(partition, dict):
        partition = json.dumps(partition, sort_keys=True)
    return (cookie["name"], cookie["domain"], cookie.get("path", "/"), str(partition))


def fingerprint(cookie: Cookie) -> tuple:
    return (
        cookie.get("value"),
        round(float(cookie.get("expires", -1))),
        bool(cookie.get("httpOnly")),
        bool(cookie.get("secure")),
        cookie.get("sameSite"),
    )


def expired(cookie: Cookie, now: float) -> bool:
    expires = float(cookie.get("expires", -1))
    return 0 < expires < now


def _lasts(cookie: Cookie) -> float:
    expires = float(cookie.get("expires", -1))
    return expires if expires > 0 else 0.0


def settable(cookie: Cookie) -> Cookie:
    clean = {field: cookie[field] for field in FIELDS if field in cookie}
    if cookie.get("partitionKey"):
        clean["partitionKey"] = cookie["partitionKey"]
    return clean


class LoginSync:
    def __init__(
        self,
        browsers: Browsers,
        displays: DisplayManager,
        jar_file: Path,
        *,
        interval: float = 2.0,
        clock=time.time,
    ) -> None:
        self.browsers = browsers
        self.displays = displays
        self.jar_file = jar_file
        self.interval = interval
        self._clock = clock
        #: Every login, merged from all browsers.
        self.jar: dict[Key, Cookie] = {}
        #: Cookies deleted in some browser (signed out), and when.
        self.removed: dict[Key, float] = {}
        #: What each browser had after the last sync, to tell what it changed since.
        self._seen: dict[str, dict[Key, tuple]] = {}
        #: Cookies a browser refused, so they aren't retried every round.
        self._refused: dict[str, set[tuple[Key, tuple]]] = {}
        self._load()
        browsers.on_connect(self._connected)

    async def _connected(self, owner: str, context: BrowserContext) -> None:
        # A (re)started browser has lost its session cookies: that is not a
        # sign-out, so look at it afresh.
        self._seen.pop(owner, None)
        self._refused.pop(owner, None)

    # -- the loop --------------------------------------------------------------

    async def run(self) -> None:
        while True:
            try:
                await self.sync_once()
            except Exception:
                log.exception("login sync failed")
            await asyncio.sleep(self.interval)

    async def sync_once(self) -> None:
        contexts = await self._running_browsers()
        readings: dict[str, list[Cookie]] = {}
        for owner, context in contexts.items():
            cookies = await self._call(owner, context.cookies())
            if cookies is not None:
                readings[owner] = cookies
        if not readings:
            return
        before = dict(self.jar), dict(self.removed)
        now = self._clock()
        for owner, cookies in readings.items():
            self._take_changes(owner, cookies, now)
        self._tidy(now)
        for owner, cookies in readings.items():
            await self._bring_up_to_date(owner, contexts[owner], cookies, now)
        if (self.jar, self.removed) != before:
            self._save()

    async def _running_browsers(self) -> dict[str, BrowserContext]:
        contexts = {}
        for display in self.displays.all():
            if display.state != "running":
                continue
            try:
                context = await asyncio.wait_for(
                    self.browsers.context(display.owner, launch=False), CALL_TIMEOUT
                )
            except Exception as exc:
                log.debug("cannot reach %s's browser: %s", display.owner, exc)
                continue
            if context is not None:
                contexts[display.owner] = context
        return contexts

    async def _call(self, owner: str, call):
        try:
            return await asyncio.wait_for(call, CALL_TIMEOUT)
        except Exception as exc:
            log.debug("browser call for %s failed: %s", owner, exc)
            return None

    # -- merging ---------------------------------------------------------------

    def _take_changes(self, owner: str, cookies: list[Cookie], now: float) -> None:
        current = {cookie_key(c): c for c in cookies if not expired(c, now)}
        seen = self._seen.get(owner)
        if seen is None:
            # First look at this browser: whatever it has that nobody signed
            # out of joins the jar. Where both have a login, the one that
            # lasts longer is taken to be the newer.
            for key, cookie in current.items():
                if key in self.removed:
                    continue
                known = self.jar.get(key)
                if known is None or _lasts(cookie) > _lasts(known):
                    self.jar[key] = cookie
            return
        for key, cookie in current.items():
            if seen.get(key) != fingerprint(cookie):
                self.jar[key] = cookie
                self.removed.pop(key, None)
        for key in seen.keys() - current.keys():
            if key in self.jar:
                del self.jar[key]
                self.removed[key] = now

    def _tidy(self, now: float) -> None:
        for key in [k for k, c in self.jar.items() if expired(c, now)]:
            del self.jar[key]
        for key in [k for k, at in self.removed.items() if now - at > FORGET_SIGN_OUTS_AFTER]:
            del self.removed[key]

    async def _bring_up_to_date(
        self, owner: str, context: BrowserContext, cookies: list[Cookie], now: float
    ) -> None:
        have = {cookie_key(c): c for c in cookies if not expired(c, now)}
        refused = self._refused.setdefault(owner, set())
        missing = [
            cookie
            for key, cookie in self.jar.items()
            if (key not in have or fingerprint(have[key]) != fingerprint(cookie))
            and (key, fingerprint(cookie)) not in refused
        ]
        extra = [key for key in have if key not in self.jar]
        if missing:
            await self._add(owner, context, missing, refused)
        for name, domain, path, _ in extra:
            await self._call(owner, context.clear_cookies(name=name, domain=domain, path=path))
        if missing or extra:
            # Read back what the browser now has. Anything it changed in the
            # meantime is a change of its own, passed on next round.
            cookies = await self._call(owner, context.cookies()) or cookies
            for cookie in cookies:
                key = cookie_key(cookie)
                if expired(cookie, now) or (key, fingerprint(cookie)) in refused:
                    continue
                changed = key not in self.jar or fingerprint(self.jar[key]) != fingerprint(cookie)
                if changed and key not in self.removed:
                    self.jar[key] = cookie
        self._seen[owner] = {cookie_key(c): fingerprint(c) for c in cookies if not expired(c, now)}

    async def _add(
        self, owner: str, context: BrowserContext, cookies: list[Cookie], refused: set
    ) -> None:
        if await self._call(owner, context.add_cookies([settable(c) for c in cookies])) is not None:
            return
        # One bad cookie fails the whole batch: add them one at a time instead.
        for cookie in cookies:
            try:
                await asyncio.wait_for(context.add_cookies([settable(cookie)]), CALL_TIMEOUT)
            except Exception as exc:
                refused.add((cookie_key(cookie), fingerprint(cookie)))
                log.debug("%s's browser refused cookie %s: %s", owner, cookie_key(cookie), exc)

    # -- storage ---------------------------------------------------------------

    def _load(self) -> None:
        try:
            data = json.loads(self.jar_file.read_text())
        except FileNotFoundError:
            return
        except (OSError, ValueError) as exc:
            log.warning("ignoring unreadable login store %s: %s", self.jar_file, exc)
            return
        self.jar = {cookie_key(c): c for c in data.get("cookies", [])}
        self.removed = {tuple(item["key"]): item["at"] for item in data.get("removed", [])}

    def _save(self) -> None:
        self.jar_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "cookies": list(self.jar.values()),
            "removed": [{"key": list(key), "at": at} for key, at in self.removed.items()],
        }
        temporary = self.jar_file.with_suffix(".tmp")
        # Logins are secrets: readable by the pal user only.
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle)
        temporary.replace(self.jar_file)
