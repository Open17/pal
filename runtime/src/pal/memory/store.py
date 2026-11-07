"""A directory of memory files with atomic, locked writes and keyword search."""

from __future__ import annotations

import contextlib
import fcntl
import os
import re
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from pal.log import get_logger

from .entry import MemoryEntry, MemoryFormatError, is_valid_entry_id, slugify

log = get_logger(__name__)

INDEX_FILE = "INDEX.md"
LOCK_FILE = ".lock"
_WORD = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class SearchHit:
    entry: MemoryEntry
    score: float


class MemoryStore:
    """Memories stored as ``<id>.md`` files in one directory.

    Every write takes an exclusive ``flock`` on the directory's lock file and
    replaces files atomically, so concurrent writers (the runtime, a CLI, or a
    bot editing files directly) never see a half-written memory.
    """

    def __init__(self, root: Path, *, title: str = "Memory") -> None:
        self.root = root
        self.title = title

    # -- reading ---------------------------------------------------------

    def path_for(self, entry_id: str) -> Path:
        if not is_valid_entry_id(entry_id):
            raise ValueError(f"invalid memory id {entry_id!r}")
        return self.root / f"{entry_id}.md"

    def get(self, entry_id: str) -> MemoryEntry | None:
        try:
            path = self.path_for(entry_id)
        except ValueError:
            return None
        if not path.is_file():
            return None
        return MemoryEntry.from_markdown(entry_id, path.read_text(encoding="utf-8"))

    def entries(self) -> list[MemoryEntry]:
        """All readable memories, most recently updated first."""

        if not self.root.is_dir():
            return []
        entries: list[MemoryEntry] = []
        for path in self.root.glob("*.md"):
            if path.name == INDEX_FILE or not is_valid_entry_id(path.stem):
                continue
            try:
                entries.append(MemoryEntry.from_markdown(path.stem, path.read_text("utf-8")))
            except (OSError, MemoryFormatError) as exc:
                log.warning("skipping unreadable memory %s: %s", path, exc)
        entries.sort(key=lambda entry: entry.updated_at, reverse=True)
        return entries

    def search(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        """Rank memories by keyword overlap with ``query``.

        Matches in the title and tags weigh most, then the description, then
        the body. An empty query returns the most recent memories.
        """

        terms = set(_WORD.findall(query.lower()))
        entries = self.entries()
        if not terms:
            return [SearchHit(entry, 0.0) for entry in entries[:limit]]
        hits: list[SearchHit] = []
        for entry in entries:
            score = _score(entry, terms)
            if score > 0:
                hits.append(SearchHit(entry, score))
        hits.sort(key=lambda hit: (hit.score, hit.entry.updated_at), reverse=True)
        return hits[:limit]

    # -- writing ---------------------------------------------------------

    def new_id(self, title: str) -> str:
        base = slugify(title)
        candidate, counter = base, 2
        while self.path_for(candidate).exists():
            candidate = f"{base}-{counter}"
            counter += 1
        return candidate

    def put(self, entry: MemoryEntry) -> MemoryEntry:
        with self._locked():
            _atomic_write(self.path_for(entry.id), entry.to_markdown())
            self._write_index()
        return entry

    def delete(self, entry_id: str) -> bool:
        with self._locked():
            try:
                self.path_for(entry_id).unlink()
            except (FileNotFoundError, ValueError):
                return False
            self._write_index()
        return True

    # -- internals -------------------------------------------------------

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / LOCK_FILE).open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _write_index(self) -> None:
        lines = [f"# {self.title}", ""]
        for entry in sorted(self.entries(), key=lambda item: item.title.lower()):
            lines.append(f"- [{entry.title}]({entry.id}.md) — {entry.summary}")
        _atomic_write(self.root / INDEX_FILE, "\n".join(lines) + "\n")


def _score(entry: MemoryEntry, terms: set[str]) -> float:
    title = set(_WORD.findall(entry.title.lower()))
    tags = {word for tag in entry.tags for word in _WORD.findall(tag.lower())}
    description = set(_WORD.findall(entry.description.lower()))
    body_words = _WORD.findall(entry.body.lower())
    score = 0.0
    for term in terms:
        score += 3.0 * (term in title) + 3.0 * (term in tags) + 2.0 * (term in description)
        score += min(body_words.count(term), 5) * 0.5
    return score


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise
