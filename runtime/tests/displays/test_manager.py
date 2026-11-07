from __future__ import annotations

import json
from pathlib import Path

import pytest

from pal.config import DisplaySettings
from pal.displays import DisplayManager, InMemoryDisplayBackend, UnknownDisplayError
from pal.messaging import EventBus


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def backend() -> InMemoryDisplayBackend:
    return InMemoryDisplayBackend()


def make_manager(tmp_path: Path, backend, clock, bus=None) -> DisplayManager:
    manager = DisplayManager(
        DisplaySettings(backend="simulated"),
        backend,
        tmp_path / "displays.json",
        bus,
        clock=clock,
    )
    manager.register(["atlas", "scout"])
    return manager


def test_allocation_is_stable_across_restarts(tmp_path: Path, backend, clock) -> None:
    manager = make_manager(tmp_path, backend, clock)
    numbers = {d.owner: d.number for d in manager.all()}
    assert numbers == {"operator": 1, "atlas": 10, "scout": 11}
    assert manager.get("atlas").vnc_public_port == 5910
    assert manager.get("atlas").vnc_internal_port == 15910

    again = DisplayManager(DisplaySettings(), backend, tmp_path / "displays.json", clock=clock)
    again.register(["forge", "scout"])  # atlas removed, forge added
    numbers = {d.owner: d.number for d in again.all()}
    assert numbers["scout"] == 11
    assert numbers["forge"] == 12  # does not reuse a number still recorded for atlas


def test_unknown_owner(tmp_path: Path, backend, clock) -> None:
    with pytest.raises(UnknownDisplayError):
        make_manager(tmp_path, backend, clock).get("nobody")


async def test_displays_start_lazily(tmp_path: Path, backend, clock) -> None:
    manager = make_manager(tmp_path, backend, clock)
    assert all(d.state == "stopped" for d in manager.all())
    assert backend.calls == []
    display = await manager.ensure_awake("atlas")
    assert display.state == "running"
    assert backend.calls == [("start", "atlas")]
    await manager.ensure_awake("atlas")
    assert backend.calls == [("start", "atlas")]  # already running: nothing to do
    assert manager.environment("atlas") == {"DISPLAY": ":10"}


async def test_idle_displays_sleep_and_wake(tmp_path: Path, backend, clock) -> None:
    manager = make_manager(tmp_path, backend, clock)
    await manager.ensure_awake("atlas")

    clock.now += 479
    assert await manager.sleep_idle() == []
    clock.now += 1
    assert await manager.sleep_idle() == ["atlas"]
    assert manager.get("atlas").state == "sleeping"

    await manager.ensure_awake("atlas")
    assert manager.get("atlas").state == "running"
    assert backend.calls == [("start", "atlas"), ("freeze", "atlas"), ("thaw", "atlas")]


async def test_activity_postpones_sleep(tmp_path: Path, backend, clock) -> None:
    manager = make_manager(tmp_path, backend, clock)
    await manager.ensure_awake("atlas")
    clock.now += 400
    manager.touch("atlas")
    clock.now += 400
    assert await manager.sleep_idle() == []


async def test_viewers_keep_displays_awake(tmp_path: Path, backend, clock) -> None:
    manager = make_manager(tmp_path, backend, clock)
    await manager.ensure_awake("atlas")
    manager.viewer_connected("atlas")
    clock.now += 3600
    assert await manager.sleep_idle() == []
    assert await manager.sleep("atlas") is False
    manager.viewer_disconnected("atlas")
    clock.now += 480
    assert await manager.sleep_idle() == ["atlas"]


async def test_live_displays_are_restored_after_reboot(tmp_path: Path, backend, clock) -> None:
    manager = make_manager(tmp_path, backend, clock)
    await manager.ensure_awake("atlas")
    await manager.ensure_awake("scout")
    await manager.sleep("scout", force=True)
    state = json.loads((tmp_path / "displays.json").read_text())
    assert state["displays"]["atlas"] == {"number": 10, "live": True}

    rebooted = InMemoryDisplayBackend()  # nothing is running after a reboot
    restored = make_manager(tmp_path, rebooted, clock)
    await restored.restore()
    assert {d.owner: d.state for d in restored.all()} == {
        "operator": "stopped",
        "atlas": "running",
        "scout": "running",
    }
    assert sorted(rebooted.calls) == [("start", "atlas"), ("start", "scout")]


async def test_running_displays_are_adopted_after_runtime_restart(
    tmp_path: Path, backend, clock
) -> None:
    manager = make_manager(tmp_path, backend, clock)
    await manager.ensure_awake("atlas")
    await manager.sleep("atlas")
    backend.calls.clear()

    restarted = make_manager(tmp_path, backend, clock)
    await restarted.restore()
    assert restarted.get("atlas").state == "sleeping"
    assert backend.calls == []


async def test_stop_marks_display_not_live(tmp_path: Path, backend, clock) -> None:
    manager = make_manager(tmp_path, backend, clock)
    await manager.ensure_awake("atlas")
    await manager.sleep("atlas")
    await manager.stop("atlas")
    assert backend.calls[-2:] == [("thaw", "atlas"), ("stop", "atlas")]
    state = json.loads((tmp_path / "displays.json").read_text())
    assert state["displays"]["atlas"]["live"] is False


async def test_state_changes_are_published(tmp_path: Path, backend, clock) -> None:
    bus = EventBus()
    manager = make_manager(tmp_path, backend, clock, bus)
    with bus.subscribe() as events:
        await manager.ensure_awake("atlas")
        states = [(await events.get()).data["display"]["state"] for _ in range(2)]
    assert states == ["starting", "running"]
