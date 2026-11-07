from __future__ import annotations

from pathlib import Path

import pytest

from pal.memory import MemoryAccessError, MemoryService


@pytest.fixture
def memory(tmp_path: Path) -> MemoryService:
    return MemoryService(tmp_path)


async def test_private_knowledge_is_isolated(memory: MemoryService) -> None:
    await memory.remember(author="atlas", scope="private", title="Secret plan", body="x")
    assert [e.title for e in await memory.list("private", "atlas")] == ["Secret plan"]
    assert await memory.list("private", "scout") == []
    hits = await memory.recall("scout", "secret plan")
    assert hits == []


async def test_shared_memory_is_visible_to_all(memory: MemoryService) -> None:
    await memory.remember(author="scout", scope="shared", title="Wifi password", body="hunter2")
    hits = await memory.recall("forge", "wifi")
    assert [(hit.scope, hit.entry.author) for hit in hits] == [("shared", "scout")]


async def test_recall_merges_scopes(memory: MemoryService) -> None:
    await memory.remember(author="atlas", scope="shared", title="Project goals", body="ship")
    await memory.remember(author="atlas", scope="private", title="My goals", body="learn")
    hits = await memory.recall("atlas", "goals")
    assert {hit.scope for hit in hits} == {"shared", "private"}


async def test_update_existing_entry(memory: MemoryService) -> None:
    created = await memory.remember(author="atlas", scope="shared", title="Status", body="red")
    updated = await memory.remember(
        author="forge", scope="shared", title="", body="green", entry_id=created.id
    )
    assert updated.id == created.id
    assert updated.title == "Status"
    assert updated.body == "green"
    assert updated.author == "atlas"
    assert updated.created_at == created.created_at


async def test_tags_are_normalised(memory: MemoryService) -> None:
    entry = await memory.remember(
        author="atlas", scope="shared", title="T", body="", tags=[" Work ", "work", "", "Home"]
    )
    assert entry.tags == ("work", "home")


async def test_forget(memory: MemoryService) -> None:
    entry = await memory.remember(author="atlas", scope="private", title="Temp", body="")
    assert await memory.forget("private", "atlas", entry.id) is True
    assert await memory.read("private", "atlas", entry.id) is None


async def test_private_scope_requires_owner(memory: MemoryService) -> None:
    with pytest.raises(MemoryAccessError):
        await memory.list("private", None)


async def test_digest_lists_both_sections(memory: MemoryService) -> None:
    await memory.remember(author="atlas", scope="private", title="Mine", body="a")
    await memory.remember(author="scout", scope="shared", title="Ours", description="d", body="b")
    digest = memory.digest("atlas")
    assert "### Your private knowledge\n- `mine` — Mine: a" in digest
    assert "### Shared team memory\n- `ours` — Ours: d" in digest
    assert "(empty)" in MemoryService(memory.root / "other").digest("atlas")
