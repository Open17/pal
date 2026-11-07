"""How displays are actually started, frozen, and stopped."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol

from pal.config import DisplaySettings
from pal.log import get_logger

from .models import Display, DisplayState

log = get_logger(__name__)


class DisplayBackendError(RuntimeError):
    pass


class DisplayBackend(Protocol):
    async def start(self, display: Display) -> None: ...
    async def stop(self, display: Display) -> None: ...
    async def freeze(self, display: Display) -> None: ...
    async def thaw(self, display: Display) -> None: ...
    async def probe(self, display: Display) -> DisplayState:
        """The state the display is really in, used to adopt it after a restart."""
        ...


class SystemdDisplayBackend:
    """Runs each display as the user unit ``pal-display@<owner>.service``.

    The unit starts Xvnc and an xfce4 session in the slice
    ``pal-display-<owner>.slice``, which also holds every program launched
    onto the display with ``pal-open``. Sleeping a display freezes the slice:
    every process stops using CPU but keeps its memory, so windows are exactly
    where they were when it thaws. Stopping the slice closes the display and
    everything on it.
    """

    UNIT_TEMPLATE = "pal-display@{owner}.service"
    SLICE_TEMPLATE = "pal-display-{owner}.slice"

    def __init__(self, settings: DisplaySettings, env_dir: Path) -> None:
        self.settings = settings
        self.env_dir = env_dir

    def unit(self, display: Display) -> str:
        return self.UNIT_TEMPLATE.format(owner=display.owner)

    def slice(self, display: Display) -> str:
        return self.SLICE_TEMPLATE.format(owner=display.owner)

    def write_environment(self, display: Display) -> Path:
        """Write the per-display settings the unit reads via ``EnvironmentFile``."""

        self.env_dir.mkdir(parents=True, exist_ok=True)
        path = self.env_dir / f"{display.owner}.env"
        path.write_text(
            f"PAL_DISPLAY_NUMBER={display.number}\n"
            f"PAL_VNC_PORT={display.vnc_internal_port}\n"
            f"PAL_DISPLAY_GEOMETRY={self.settings.geometry}\n"
            f"PAL_DISPLAY_DEPTH={self.settings.depth}\n"
            f"PAL_DISPLAY_OWNER={display.owner}\n"
        )
        return path

    async def start(self, display: Display) -> None:
        self.write_environment(display)
        await self._systemctl("start", self.unit(display))

    async def stop(self, display: Display) -> None:
        await self._systemctl("stop", self.slice(display))

    async def freeze(self, display: Display) -> None:
        await self._systemctl("freeze", self.slice(display))

    async def thaw(self, display: Display) -> None:
        await self._systemctl("thaw", self.slice(display))

    async def probe(self, display: Display) -> DisplayState:
        output = await self._systemctl(
            "show",
            "--property=ActiveState,FreezerState",
            self.unit(display),
            self.slice(display),
            check=False,
        )
        # One block of properties per unit, separated by a blank line.
        unit_block, _, slice_block = output.partition("\n\n")
        active = _properties(unit_block).get("ActiveState")
        freezer = _properties(slice_block).get("FreezerState")
        if active == "active":
            return "sleeping" if freezer in ("frozen", "freezing") else "running"
        if active == "activating":
            return "starting"
        if active == "failed":
            return "failed"
        return "stopped"

    async def _systemctl(self, *args: str, check: bool = True) -> str:
        process = await asyncio.create_subprocess_exec(
            "systemctl",
            "--user",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if check and process.returncode != 0:
            message = stderr.decode().strip() or f"exit status {process.returncode}"
            raise DisplayBackendError(f"systemctl {' '.join(args)}: {message}")
        return stdout.decode()


def _properties(block: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in block.splitlines() if "=" in line)


class InMemoryDisplayBackend:
    """A backend that only tracks state, for development machines and tests."""

    def __init__(self) -> None:
        self.states: dict[str, DisplayState] = {}
        self.calls: list[tuple[str, str]] = []

    async def start(self, display: Display) -> None:
        self._record("start", display, "running")

    async def stop(self, display: Display) -> None:
        self._record("stop", display, "stopped")

    async def freeze(self, display: Display) -> None:
        self._record("freeze", display, "sleeping")

    async def thaw(self, display: Display) -> None:
        self._record("thaw", display, "running")

    async def probe(self, display: Display) -> DisplayState:
        return self.states.get(display.owner, "stopped")

    def _record(self, action: str, display: Display, state: DisplayState) -> None:
        self.calls.append((action, display.owner))
        self.states[display.owner] = state


def create_backend(settings: DisplaySettings, env_dir: Path) -> DisplayBackend:
    if settings.backend == "systemd":
        return SystemdDisplayBackend(settings, env_dir)
    log.warning("display backend is %r: displays are simulated, not started", settings.backend)
    return InMemoryDisplayBackend()
