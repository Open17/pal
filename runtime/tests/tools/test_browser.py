from __future__ import annotations

from pathlib import Path

import pytest

from pal.config import DisplaySettings
from pal.displays import DisplayManager, InMemoryDisplayBackend
from pal.tools import ToolContext
from pal.tools.browser import BrowserError, BrowserTools, SharedBrowser, chromium_command, locate


class FakeLocator:
    def __init__(self, how: str, *args, **kwargs) -> None:
        self.how, self.args, self.kwargs = how, args, kwargs
        self.index = None

    def nth(self, index: int) -> FakeLocator:
        self.index = index
        return self


class FakePage:
    def __init__(self, name: str = "page") -> None:
        self.name = name
        self.closed = False

    def is_closed(self) -> bool:
        return self.closed

    def locator(self, selector):
        return FakeLocator("css", selector)

    def get_by_role(self, role, name=None):
        return FakeLocator("role", role, name=name)

    def get_by_label(self, label):
        return FakeLocator("label", label)

    def get_by_placeholder(self, text):
        return FakeLocator("placeholder", text)

    def get_by_text(self, text):
        return FakeLocator("text", text)


@pytest.mark.parametrize(
    ("args", "how", "expected"),
    [
        ({"role": "button", "name": "Sign in"}, "role", ("button",)),
        ({"label": "Email"}, "label", ("Email",)),
        ({"placeholder": "Search"}, "placeholder", ("Search",)),
        ({"text": "Next"}, "text", ("Next",)),
        ({"selector": "#go", "role": "button"}, "css", ("#go",)),  # selector wins
    ],
)
def test_locate(args, how, expected) -> None:
    locator = locate(FakePage(), {**args, "nth": 2})
    assert (locator.how, locator.args, locator.index) == (how, expected, 2)


def test_locate_needs_a_target() -> None:
    with pytest.raises(BrowserError):
        locate(FakePage(), {})


def test_chromium_uses_one_profile_and_debug_port(tmp_path: Path) -> None:
    command = chromium_command(9222, tmp_path / "profile")
    assert command[0] == "chromium"
    assert "--remote-debugging-port=9222" in command
    assert "--remote-debugging-address=127.0.0.1" in command
    assert f"--user-data-dir={tmp_path / 'profile'}" in command
    assert "--disable-backgrounding-occluded-windows" in command


@pytest.fixture
def shared(tmp_path: Path) -> SharedBrowser:
    displays = DisplayManager(
        DisplaySettings(backend="simulated"), InMemoryDisplayBackend(), tmp_path / "d.json"
    )
    displays.register(["atlas", "scout"])
    return SharedBrowser(displays, tmp_path / "profile", tmp_path / "downloads")


def test_each_bot_only_sees_its_own_tabs(shared: SharedBrowser) -> None:
    mine, theirs = FakePage("mine"), FakePage("theirs")
    shared._claim("atlas", mine)
    shared._claim("scout", theirs)
    assert shared.tabs("atlas") == [mine]
    assert shared.tabs("scout") == [theirs]
    assert shared.owner(theirs) == "scout"
    mine.closed = True
    assert shared.tabs("atlas") == []


def test_browser_has_its_own_display(shared: SharedBrowser) -> None:
    assert shared.displays.get("browser").name == ":2"


def test_browser_tools_do_not_wake_the_bots_display(shared: SharedBrowser) -> None:
    provider = BrowserTools(shared)
    assert provider.requires_display is False
    names = [t.name for t in provider.tools(ToolContext("atlas"))]
    assert names[:3] == ["browser_open", "browser_snapshot", "browser_click"]
    assert len(names) == 12
