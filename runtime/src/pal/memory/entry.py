"""A single memory, stored on disk as a markdown file with a YAML header."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

import yaml

ENTRY_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
MAX_TITLE_LENGTH = 120
MAX_DESCRIPTION_LENGTH = 300
_FRONTMATTER = re.compile(r"\A---\n(?P<header>.*?)\n---\n?(?P<body>.*)\Z", re.DOTALL)


class MemoryFormatError(ValueError):
    """Raised when a memory file cannot be parsed."""


def utcnow() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def slugify(text: str, *, max_length: int = 60) -> str:
    """Turn a title into a stable, file-name-safe id."""

    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    slug = slug[:max_length].rstrip("-")
    return slug or "memory"


def is_valid_entry_id(value: str) -> bool:
    return bool(ENTRY_ID_PATTERN.match(value))


@dataclass(frozen=True)
class MemoryEntry:
    id: str
    title: str
    body: str
    description: str = ""
    kind: str = "note"
    tags: tuple[str, ...] = ()
    author: str = "user"
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        if not is_valid_entry_id(self.id):
            raise MemoryFormatError(f"invalid memory id {self.id!r}")
        if not self.title.strip():
            raise MemoryFormatError("memory title must not be empty")

    @property
    def summary(self) -> str:
        """The one-line description, falling back to the first line of the body."""

        if self.description:
            return self.description
        first_line = next((line.strip() for line in self.body.splitlines() if line.strip()), "")
        return first_line[:MAX_DESCRIPTION_LENGTH]

    def updated(self, **changes: Any) -> MemoryEntry:
        return replace(self, updated_at=utcnow(), **changes)

    def to_markdown(self) -> str:
        header = {
            "title": self.title,
            "description": self.description,
            "kind": self.kind,
            "tags": list(self.tags),
            "author": self.author,
            "created": self.created_at.isoformat(),
            "updated": self.updated_at.isoformat(),
        }
        rendered = yaml.safe_dump(header, sort_keys=False, allow_unicode=True).strip()
        body = self.body.rstrip() + "\n" if self.body.strip() else ""
        return f"---\n{rendered}\n---\n\n{body}"

    @classmethod
    def from_markdown(cls, entry_id: str, text: str) -> MemoryEntry:
        match = _FRONTMATTER.match(text)
        if not match:
            raise MemoryFormatError(f"{entry_id}: missing frontmatter header")
        try:
            header = yaml.safe_load(match.group("header")) or {}
        except yaml.YAMLError as exc:
            raise MemoryFormatError(f"{entry_id}: invalid frontmatter: {exc}") from exc
        if not isinstance(header, dict):
            raise MemoryFormatError(f"{entry_id}: frontmatter must be a mapping")
        return cls(
            id=entry_id,
            title=str(header.get("title") or entry_id),
            body=match.group("body").strip(),
            description=str(header.get("description") or ""),
            kind=str(header.get("kind") or "note"),
            tags=tuple(str(tag) for tag in header.get("tags") or ()),
            author=str(header.get("author") or "user"),
            created_at=_parse_time(header.get("created")),
            updated_at=_parse_time(header.get("updated")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "kind": self.kind,
            "tags": list(self.tags),
            "author": self.author,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "body": self.body,
        }


def _parse_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return utcnow()
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return utcnow()
