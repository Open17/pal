from __future__ import annotations

from pathlib import Path

import pytest

from pal.config import DisplaySettings
from pal.displays import DisplayManager, InMemoryDisplayBackend
from pal.tools import ToolContext
from pal.tools.browser import (
    BrowserError,
    Browsers,
    BrowserTools,
    debug_port,
    locate,
    normalize_url,
)


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


def test_addresses_without_a_scheme_get_https() -> None:
    assert normalize_url(" example.com/a ") == "https://example.com/a"
    assert normalize_url("file:///home/pal/a.html") == "file:///home/pal/a.html"
    with pytest.raises(BrowserError):
        normalize_url("  ")


@pytest.fixture
def displays(tmp_path: Path) -> DisplayManager:
    manager = DisplayManager(
        DisplaySettings(backend="simulated"), InMemoryDisplayBackend(), tmp_path / "d.json"
    )
    manager.register(["atlas", "scout"])
    return manager


def test_every_display_has_its_own_browser_port(displays: DisplayManager) -> None:
    # The pal-chromium launcher derives the same port from the display number.
    assert debug_port(displays.get("atlas")) == 9310
    assert debug_port(displays.get("scout")) == 9311
    assert debug_port(displays.get("operator")) == 9301


def test_browser_tools_use_the_bots_own_display(displays: DisplayManager, tmp_path: Path) -> None:
    provider = BrowserTools(Browsers(displays, tmp_path))
    assert provider.requires_display is True
    names = [t.name for t in provider.tools(ToolContext("atlas"))]
    assert names[:3] == ["browser_open", "browser_snapshot", "browser_click"]
    assert len(names) == 12
