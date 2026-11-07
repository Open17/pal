from __future__ import annotations

from pathlib import Path

from pal.memory import MemoryEntry, MemoryStore


def make(store: MemoryStore, title: str, body: str = "", **kwargs) -> MemoryEntry:
    return store.put(MemoryEntry(id=store.new_id(title), title=title, body=body, **kwargs))


def test_put_get_delete(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    entry = make(store, "Server address", "10.0.0.5")
    assert store.get(entry.id) == entry
    assert (tmp_path / "server-address.md").is_file()
    assert store.delete(entry.id) is True
    assert store.get(entry.id) is None
    assert store.delete(entry.id) is False


def test_new_ids_do_not_collide(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    first = make(store, "Notes")
    second = make(store, "Notes")
    assert (first.id, second.id) == ("notes", "notes-2")


def test_index_lists_every_entry(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path, title="Shared memory")
    make(store, "Beta", description="second")
    make(store, "Alpha", description="first")
    index = (tmp_path / "INDEX.md").read_text()
    assert index.splitlines() == [
        "# Shared memory",
        "",
        "- [Alpha](alpha.md) — first",
        "- [Beta](beta.md) — second",
    ]


def test_search_ranks_title_and_tags_above_body(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    make(store, "Lunch", "We talked about the deploy schedule")
    make(store, "Deploy checklist", "Steps")
    make(store, "Release", "Steps", tags=("deploy",))
    titles = [hit.entry.title for hit in store.search("deploy")]
    assert titles[-1] == "Lunch"
    assert set(titles[:2]) == {"Deploy checklist", "Release"}


def test_search_without_terms_returns_recent(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    make(store, "One")
    assert [hit.entry.title for hit in store.search("  ")] == ["One"]


def test_unreadable_files_are_skipped(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    make(store, "Good")
    (tmp_path / "broken.md").write_text("not a memory")
    assert [entry.title for entry in store.entries()] == ["Good"]


def test_get_rejects_path_traversal(tmp_path: Path) -> None:
    assert MemoryStore(tmp_path).get("../etc/passwd") is None
