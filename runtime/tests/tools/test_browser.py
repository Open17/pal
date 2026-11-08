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
    LoginSync,
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


# -- login sync ----------------------------------------------------------------


def cookie(name: str, value: str, domain: str = ".example.com", expires: float = 2e9) -> dict:
    return {
        "name": name,
        "value": value,
        "domain": domain,
        "path": "/",
        "expires": expires,
        "httpOnly": True,
        "secure": True,
        "sameSite": "Lax",
    }


class FakeContext:
    """A browser's cookie jar, as Playwright exposes it."""

    def __init__(self, *cookies: dict) -> None:
        self.store = {(c["name"], c["domain"], c["path"]): dict(c) for c in cookies}
        self.refuse: set[str] = set()

    async def cookies(self) -> list[dict]:
        return [dict(c) for c in self.store.values()]

    async def add_cookies(self, cookies: list[dict]) -> None:
        if any(c["name"] in self.refuse for c in cookies):
            raise RuntimeError("invalid cookie")
        for c in cookies:
            self.store[(c["name"], c["domain"], c["path"])] = dict(c)

    async def clear_cookies(self, *, name=None, domain=None, path=None) -> None:
        self.store.pop((name, domain, path), None)

    def values(self) -> dict[str, str]:
        return {name: c["value"] for (name, _, _), c in self.store.items()}


class FakeBrowsers:
    def __init__(self, contexts: dict[str, FakeContext]) -> None:
        self.contexts = contexts
        self.hooks = []

    def on_connect(self, hook) -> None:
        self.hooks.append(hook)

    async def context(self, owner: str, *, launch: bool = True):
        return self.contexts.get(owner)

    async def restart(self, owner: str, context: FakeContext) -> None:
        self.contexts[owner] = context
        for hook in self.hooks:
            await hook(owner, context)


@pytest.fixture
async def running(displays: DisplayManager) -> DisplayManager:
    for owner in ("operator", "atlas", "scout"):
        await displays.ensure_awake(owner)
    return displays


async def test_a_login_in_one_browser_reaches_the_others(running, tmp_path: Path) -> None:
    atlas, scout, user = FakeContext(), FakeContext(), FakeContext()
    browsers = FakeBrowsers({"atlas": atlas, "scout": scout, "operator": user})
    sync = LoginSync(browsers, running, tmp_path / "logins.json")
    await sync.sync_once()

    user.store[("sid", ".example.com", "/")] = cookie("sid", "signed-in")
    await sync.sync_once()
    assert atlas.values() == scout.values() == {"sid": "signed-in"}

    # A changed login (say, refreshed by a bot) travels the same way.
    await atlas.add_cookies([cookie("sid", "refreshed")])
    await sync.sync_once()
    assert user.values() == scout.values() == {"sid": "refreshed"}

    # Signing out anywhere signs everyone out.
    await scout.clear_cookies(name="sid", domain=".example.com", path="/")
    await sync.sync_once()
    assert atlas.values() == user.values() == {}


async def test_logins_are_kept_for_browsers_started_later(running, tmp_path: Path) -> None:
    atlas = FakeContext(cookie("sid", "abc"))
    sync = LoginSync(FakeBrowsers({"atlas": atlas}), running, tmp_path / "logins.json")
    await sync.sync_once()
    assert oct((tmp_path / "logins.json").stat().st_mode & 0o777) == "0o600"

    # Later, with the runtime restarted, Scout's browser starts empty.
    scout = FakeContext()
    later = LoginSync(FakeBrowsers({"scout": scout}), running, tmp_path / "logins.json")
    await later.sync_once()
    assert scout.values() == {"sid": "abc"}


async def test_a_restarted_browser_losing_session_cookies_is_not_a_sign_out(
    running, tmp_path: Path
) -> None:
    session = cookie("session", "s1", expires=-1)
    atlas, scout = FakeContext(session), FakeContext()
    browsers = FakeBrowsers({"atlas": atlas, "scout": scout})
    sync = LoginSync(browsers, running, tmp_path / "logins.json")
    await sync.sync_once()
    assert scout.values() == {"session": "s1"}

    await browsers.restart("atlas", FakeContext())  # closed and opened again
    await sync.sync_once()
    assert scout.values() == {"session": "s1"}
    assert browsers.contexts["atlas"].values() == {"session": "s1"}


async def test_sleeping_displays_are_left_alone(running, tmp_path: Path) -> None:
    atlas, scout = FakeContext(cookie("sid", "abc")), FakeContext()
    await running.sleep("scout", force=True)
    sync = LoginSync(FakeBrowsers({"atlas": atlas, "scout": scout}), running, tmp_path / "l.json")
    await sync.sync_once()
    assert scout.values() == {}  # frozen; it catches up when it wakes
    await running.ensure_awake("scout")
    await sync.sync_once()
    assert scout.values() == {"sid": "abc"}


async def test_a_cookie_a_browser_refuses_does_not_stop_the_rest(running, tmp_path: Path) -> None:
    atlas = FakeContext(cookie("good", "1"), cookie("odd", "2"))
    scout = FakeContext()
    scout.refuse = {"odd"}
    sync = LoginSync(FakeBrowsers({"atlas": atlas, "scout": scout}), running, tmp_path / "l.json")
    await sync.sync_once()
    assert scout.values() == {"good": "1"}
    await sync.sync_once()  # not retried, and not mistaken for a sign-out
    assert atlas.values() == {"good": "1", "odd": "2"}


async def test_expired_cookies_are_not_copied(running, tmp_path: Path) -> None:
    atlas = FakeContext(cookie("old", "x", expires=1000.0), cookie("sid", "abc"))
    scout = FakeContext()
    sync = LoginSync(FakeBrowsers({"atlas": atlas, "scout": scout}), running, tmp_path / "l.json")
    await sync.sync_once()
    assert scout.values() == {"sid": "abc"}
