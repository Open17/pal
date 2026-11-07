"""On-demand displays with idle sleep.

A display is started the first time its owner needs the computer, frozen after
``idle_timeout_seconds`` without activity (unless someone is watching it), and
thawed the next time it is needed. Allocations and which displays were live
are persisted so they come back after the runtime or the VM restarts.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from pathlib import Path

from pal.config import BROWSER_ID, OPERATOR_ID, DisplaySettings
from pal.log import get_logger
from pal.messaging import EventBus, EventType

from .backend import DisplayBackend, DisplayBackendError
from .models import Display, DisplayState

log = get_logger(__name__)

STATE_VERSION = 1


class UnknownDisplayError(KeyError):
    pass


class DisplayManager:
    def __init__(
        self,
        settings: DisplaySettings,
        backend: DisplayBackend,
        state_file: Path,
        bus: EventBus | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self.backend = backend
        self.state_file = state_file
        self.bus = bus
        self._clock = clock
        self._displays: dict[str, Display] = {}
        self._was_live: set[str] = set()
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    # -- registration ------------------------------------------------------

    def register(self, owners: Iterable[str]) -> None:
        """Allocate displays for the operator, the shared browser, and every given bot.

        Numbers already recorded in the state file are kept, so a bot always
        gets the same display.
        """

        saved = self._load_state()
        numbers: dict[str, int] = {
            owner: entry["number"] for owner, entry in saved.items() if "number" in entry
        }
        self._was_live = {owner for owner, entry in saved.items() if entry.get("live")}
        numbers[OPERATOR_ID] = self.settings.operator_display
        numbers[BROWSER_ID] = self.settings.browser_display
        for owner in [OPERATOR_ID, BROWSER_ID, *owners]:
            if owner not in numbers:
                numbers[owner] = self._next_free_number(numbers.values())
            self._displays.setdefault(owner, self._make(owner, numbers[owner]))
        self._save_state()

    def _next_free_number(self, used: Iterable[int]) -> int:
        taken = set(used) | {self.settings.operator_display, self.settings.browser_display}
        number = self.settings.first_bot_display
        while number in taken:
            number += 1
        return number

    def _make(self, owner: str, number: int) -> Display:
        return Display(
            owner=owner,
            number=number,
            vnc_internal_port=self.settings.vnc_internal_base_port + number,
            vnc_public_port=self.settings.vnc_public_base_port + number,
            last_activity=self._clock(),
        )

    # -- queries -------------------------------------------------------------

    def get(self, owner: str) -> Display:
        try:
            return self._displays[owner]
        except KeyError:
            raise UnknownDisplayError(owner) from None

    def all(self) -> list[Display]:
        return sorted(self._displays.values(), key=lambda display: display.number)

    def environment(self, owner: str) -> dict[str, str]:
        """Environment variables that point programs at the owner's display."""

        return {"DISPLAY": self.get(owner).name, "PAL_DISPLAY_OWNER": owner}

    # -- lifecycle -------------------------------------------------------------

    async def ensure_awake(self, owner: str) -> Display:
        """Start or thaw the owner's display and mark it active."""

        display = self.get(owner)
        async with self._locks[owner]:
            display.last_activity = self._clock()
            if display.is_live:
                await self._reconcile(display)
            if display.state == "running":
                return display
            try:
                if display.state == "sleeping":
                    await self.backend.thaw(display)
                else:
                    self._set_state(display, "starting")
                    await self.backend.start(display)
            except DisplayBackendError as exc:
                self._set_state(display, "failed", error=str(exc))
                raise
            self._set_state(display, "running")
            display.last_activity = self._clock()
            return display

    def touch(self, owner: str) -> None:
        """Record activity so the display does not fall asleep."""

        self.get(owner).last_activity = self._clock()

    async def sleep(self, owner: str, *, force: bool = False) -> bool:
        """Freeze a running display. Returns whether it went to sleep."""

        display = self.get(owner)
        async with self._locks[owner]:
            if display.state != "running" or (display.viewers and not force):
                return False
            try:
                await self.backend.freeze(display)
            except DisplayBackendError as exc:
                log.warning("could not put display %s to sleep: %s", display.name, exc)
                return False
            self._set_state(display, "sleeping")
            return True

    async def stop(self, owner: str) -> None:
        """Stop a display entirely. Its windows are closed."""

        display = self.get(owner)
        async with self._locks[owner]:
            if display.state == "stopped":
                return
            if display.state == "sleeping":
                with contextlib.suppress(DisplayBackendError):
                    await self.backend.thaw(display)
            await self.backend.stop(display)
            self._set_state(display, "stopped")

    # -- viewers -----------------------------------------------------------------

    def viewer_connected(self, owner: str) -> None:
        display = self.get(owner)
        display.viewers += 1
        display.last_activity = self._clock()
        self._publish(display)

    def viewer_disconnected(self, owner: str) -> None:
        display = self.get(owner)
        display.viewers = max(0, display.viewers - 1)
        display.last_activity = self._clock()
        self._publish(display)

    # -- background work ---------------------------------------------------------

    async def restore(self) -> None:
        """Bring displays back to their state from before the restart.

        Displays that are still alive (the runtime restarted but the VM did
        not) are adopted as they are. Displays that were live before a reboot
        are started again so the desktop session can restore its windows.
        """

        for display in self.all():
            actual = await self.backend.probe(display)
            if actual in ("running", "sleeping"):
                self._set_state(display, actual, persist=False)
            elif display.owner in self._was_live:
                log.info("restoring display %s for %s", display.name, display.owner)
                try:
                    await self.ensure_awake(display.owner)
                except DisplayBackendError as exc:
                    log.warning("could not restore display %s: %s", display.name, exc)
        self._save_state()

    async def refresh(self) -> None:
        """Pick up displays whose session ended on its own (logout, crash)."""

        for display in self.all():
            if display.is_live and not self._locks[display.owner].locked():
                async with self._locks[display.owner]:
                    await self._reconcile(display)

    async def _reconcile(self, display: Display) -> None:
        actual = await self.backend.probe(display)
        if actual in ("stopped", "failed"):
            log.info("display %s (%s) ended on its own", display.name, display.owner)
            self._set_state(display, actual)

    async def sleep_idle(self) -> list[str]:
        """Freeze every display that has been idle past the timeout."""

        now = self._clock()
        slept = []
        for display in self.all():
            idle = now - display.last_activity
            if (
                display.state == "running"
                and display.viewers == 0
                and idle >= self.settings.idle_timeout_seconds
                and await self.sleep(display.owner)
            ):
                log.info("display %s (%s) asleep after %ds idle", display.name, display.owner, idle)
                slept.append(display.owner)
        return slept

    async def run_idle_monitor(self) -> None:
        while True:
            await asyncio.sleep(self.settings.check_interval_seconds)
            try:
                await self.refresh()
                await self.sleep_idle()
            except Exception:
                log.exception("display idle check failed")

    # -- state -----------------------------------------------------------------

    def _set_state(
        self, display: Display, state: DisplayState, *, error: str | None = None, persist=True
    ) -> None:
        changed = display.state != state or display.error != error
        display.state = state
        display.error = error
        if changed:
            self._publish(display)
            if persist:
                self._save_state()

    def _publish(self, display: Display) -> None:
        if self.bus is not None:
            self.bus.publish(EventType.DISPLAY_STATE, display=display.to_dict())

    def _load_state(self) -> dict[str, dict]:
        try:
            data = json.loads(self.state_file.read_text())
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            log.warning("ignoring unreadable display state %s: %s", self.state_file, exc)
            return {}
        displays = data.get("displays", {}) if isinstance(data, dict) else {}
        return {owner: entry for owner, entry in displays.items() if isinstance(entry, dict)}

    def _save_state(self) -> None:
        data = {
            "version": STATE_VERSION,
            "displays": {
                display.owner: {"number": display.number, "live": display.is_live}
                for display in self.all()
            },
        }
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n")
        tmp.replace(self.state_file)
