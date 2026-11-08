"""Control one X display with standard desktop tools.

Runs ``xdotool`` (pointer and keyboard), ``wmctrl`` (windows), ``scrot``
(screenshots), ``xclip`` (clipboard), ``tesseract`` (text recognition), and
``pal-open`` (launching programs into the display's slice).
"""

from __future__ import annotations

import asyncio
import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

KEY_ALIASES = {
    "enter": "Return",
    "return": "Return",
    "esc": "Escape",
    "escape": "Escape",
    "backspace": "BackSpace",
    "del": "Delete",
    "delete": "Delete",
    "tab": "Tab",
    "space": "space",
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
    "home": "Home",
    "end": "End",
    "pageup": "Page_Up",
    "pgup": "Page_Up",
    "pagedown": "Page_Down",
    "pgdn": "Page_Down",
    "insert": "Insert",
    "ctrl": "ctrl",
    "control": "ctrl",
    "alt": "alt",
    "option": "alt",
    "shift": "shift",
    "super": "super",
    "win": "super",
    "meta": "super",
    "cmd": "ctrl",
    "command": "ctrl",
}

BUTTONS = {"left": 1, "middle": 2, "right": 3}
SCROLL_BUTTONS = {"up": 4, "down": 5, "left": 6, "right": 7}


class DesktopError(RuntimeError):
    """A desktop command failed; the message is shown to the bot."""


@dataclass(frozen=True)
class Window:
    id: str
    desktop: int
    pid: int
    x: int
    y: int
    width: int
    height: int
    app: str
    title: str


def normalize_keys(combo: str) -> str:
    """``"Ctrl+Shift+t"`` → ``"ctrl+shift+t"``; ``"cmd+enter"`` → ``"ctrl+Return"``."""

    parts = [part.strip() for part in combo.split("+")]
    if not all(parts):
        raise DesktopError(f"invalid key combination {combo!r}")
    keys = []
    for part in parts:
        alias = KEY_ALIASES.get(part.lower())
        if alias:
            keys.append(alias)
        elif re.fullmatch(r"[fF]([1-9]|1[0-2])", part):
            keys.append(part.upper())
        else:
            keys.append(part)
    return "+".join(keys)


def parse_windows(output: str) -> list[Window]:
    """Parse ``wmctrl -lpGx``: id, desktop, pid, x, y, w, h, class, host, title."""

    windows = []
    for line in output.splitlines():
        parts = line.split(None, 9)
        if len(parts) < 9:
            continue
        try:
            windows.append(
                Window(
                    id=parts[0],
                    desktop=int(parts[1]),
                    pid=int(parts[2]),
                    x=int(parts[3]),
                    y=int(parts[4]),
                    width=int(parts[5]),
                    height=int(parts[6]),
                    app=parts[7].split(".")[-1],
                    title=parts[9] if len(parts) > 9 else "",
                )
            )
        except ValueError:
            continue
    # Desktop furniture (desktop icons, panels) lives on desktop -1.
    return [w for w in windows if w.desktop >= 0]


class Desktop:
    def __init__(self, display: str, *, owner: str, scratch: Path) -> None:
        self.display = display
        self.owner = owner
        self.scratch = scratch

    @property
    def environment(self) -> dict[str, str]:
        return {**os.environ, "DISPLAY": self.display, "PAL_BOT_ID": self.owner}

    async def run(self, *args: str, stdin: bytes | None = None, time_limit: float = 20) -> str:
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self.environment,
            )
        except FileNotFoundError as exc:
            raise DesktopError(f"{args[0]} is not installed on this computer") from exc
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(stdin), time_limit)
        except TimeoutError:
            process.kill()
            raise DesktopError(f"{args[0]} took longer than {time_limit:g}s") from None
        if process.returncode != 0:
            message = stderr.decode(errors="replace").strip() or f"exit status {process.returncode}"
            raise DesktopError(f"{args[0]}: {message}")
        return stdout.decode(errors="replace")

    # -- screen ------------------------------------------------------------

    async def screenshot(self) -> Path:
        self.scratch.mkdir(parents=True, exist_ok=True)
        path = self.scratch / f"screen-{self.owner}.png"
        await self.run("scrot", "--overwrite", "--pointer", str(path))
        return path

    async def screen_size(self) -> tuple[int, int]:
        width, height = (await self.run("xdotool", "getdisplaygeometry")).split()
        return int(width), int(height)

    async def recognize_text(self, image: Path) -> str:
        return await self.run(
            "tesseract", str(image), "stdout", "--psm", "11", "tsv", time_limit=60
        )

    # -- pointer -----------------------------------------------------------

    async def move(self, x: int, y: int) -> None:
        await self.run("xdotool", "mousemove", "--sync", str(x), str(y))

    async def click(self, x: int, y: int, *, button: str = "left", count: int = 1) -> None:
        if button not in BUTTONS:
            raise DesktopError(f"unknown mouse button {button!r}")
        await self.run(
            "xdotool", "mousemove", "--sync", str(x), str(y),
            "click", "--repeat", str(count), "--delay", "80", str(BUTTONS[button]),
        )  # fmt: skip

    async def drag(self, start: tuple[int, int], end: tuple[int, int], *, steps: int = 15) -> None:
        # Move in steps while the button is down: window managers and most
        # applications ignore a press that jumps straight to its destination.
        args = ["xdotool", "mousemove", "--sync", str(start[0]), str(start[1]), "mousedown", "1"]
        args += ["sleep", "0.1"]
        for step in range(1, steps + 1):
            x = start[0] + (end[0] - start[0]) * step // steps
            y = start[1] + (end[1] - start[1]) * step // steps
            args += ["mousemove", str(x), str(y), "sleep", "0.02"]
        args += ["sleep", "0.1", "mouseup", "1"]
        await self.run(*args)

    async def scroll(self, x: int, y: int, direction: str, amount: int) -> None:
        if direction not in SCROLL_BUTTONS:
            raise DesktopError(f"unknown scroll direction {direction!r}")
        await self.run(
            "xdotool", "mousemove", "--sync", str(x), str(y),
            "click", "--repeat", str(amount), "--delay", "40", str(SCROLL_BUTTONS[direction]),
        )  # fmt: skip

    async def cursor(self) -> tuple[int, int]:
        values = dict(
            line.split("=", 1)
            for line in (await self.run("xdotool", "getmouselocation", "--shell")).splitlines()
            if "=" in line
        )
        return int(values["X"]), int(values["Y"])

    # -- keyboard ----------------------------------------------------------

    async def type_text(self, text: str) -> None:
        await self.run("xdotool", "type", "--delay", "8", "--", text, time_limit=120)

    async def press(self, combos: list[str]) -> list[str]:
        keys = [normalize_keys(combo) for combo in combos]
        await self.run("xdotool", "key", "--delay", "60", "--", *keys)
        return keys

    # -- windows -----------------------------------------------------------

    async def windows(self) -> list[Window]:
        return parse_windows(await self.run("wmctrl", "-lpGx"))

    async def find_window(self, target: str) -> Window:
        windows = await self.windows()
        for window in windows:
            if window.id.lower() == target.lower():
                return window
        needle = target.lower()
        matches = [w for w in windows if needle in w.title.lower() or needle == w.app.lower()]
        if not matches:
            raise DesktopError(f"no window matches {target!r}; use list_windows to see them")
        return matches[-1]

    async def focus_window(self, window: Window) -> None:
        await self.run("wmctrl", "-i", "-a", window.id)

    async def close_window(self, window: Window) -> None:
        await self.run("wmctrl", "-i", "-c", window.id)

    async def maximize_window(self, window: Window) -> None:
        await self.run("wmctrl", "-i", "-r", window.id, "-b", "add,maximized_vert,maximized_horz")

    async def minimize_window(self, window: Window) -> None:
        await self.run("xdotool", "windowminimize", str(int(window.id, 16)))

    async def move_window(self, window: Window, x: int, y: int, width: int, height: int) -> None:
        await self.run(
            "wmctrl", "-i", "-r", window.id, "-b", "remove,maximized_vert,maximized_horz"
        )
        await self.run("wmctrl", "-i", "-r", window.id, "-e", f"0,{x},{y},{width},{height}")

    # -- programs and clipboard ------------------------------------------------

    async def open(self, command: str) -> list[str]:
        argv = shlex.split(command)
        if not argv:
            raise DesktopError("no command given")
        await self.run("pal-open", *argv)
        return argv

    async def clipboard_read(self) -> str:
        try:
            return await self.run("xclip", "-selection", "clipboard", "-o", time_limit=5)
        except DesktopError:
            return ""

    async def clipboard_write(self, text: str) -> None:
        # xclip forks to keep serving the selection, and that child would hold
        # captured output pipes open; so wait only for the parent to exit.
        process = await asyncio.create_subprocess_exec(
            "xclip", "-selection", "clipboard", "-i",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            env=self.environment,
        )  # fmt: skip
        process.stdin.write(text.encode())
        await process.stdin.drain()
        process.stdin.close()
        if await asyncio.wait_for(process.wait(), 5) != 0:
            raise DesktopError("could not set the clipboard")
