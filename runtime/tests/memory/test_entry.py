from __future__ import annotations

import pytest

from pal.memory import MemoryEntry, MemoryFormatError, slugify


def test_round_trip_preserves_fields() -> None:
    entry = MemoryEntry(
        id="favorite-editor",
        title="Favorite editor",
        body="The user prefers a terminal editor.\n\nUse it for quick edits.",
        description="Which editor to open for the user",
        kind="preference",
        tags=("user", "tools"),
        author="atlas",
    )
    parsed = MemoryEntry.from_markdown(entry.id, entry.to_markdown())
    assert parsed == entry


def test_markdown_layout_is_human_readable() -> None:
    text = MemoryEntry(id="a", title="A", body="Body").to_markdown()
    assert text.startswith("---\ntitle: A\n")
    assert text.endswith("---\n\nBody\n")


@pytest.mark.parametrize(
    ("title", "slug"),
    [("Hello, World!", "hello-world"), ("  Café notes ", "cafe-notes"), ("!!!", "memory")],
)
def test_slugify(title: str, slug: str) -> None:
    assert slugify(title) == slug


def test_summary_falls_back_to_first_body_line() -> None:
    entry = MemoryEntry(id="a", title="A", body="\n\nFirst line\nSecond")
    assert entry.summary == "First line"


@pytest.mark.parametrize("text", ["no header", "---\n[unclosed\n---\nbody", "---\n- a list\n---\n"])
def test_invalid_files_raise(text: str) -> None:
    with pytest.raises(MemoryFormatError):
        MemoryEntry.from_markdown("a", text)


def test_invalid_id_rejected() -> None:
    with pytest.raises(MemoryFormatError):
        MemoryEntry(id="../escape", title="x", body="")
