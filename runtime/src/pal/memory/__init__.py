"""File-backed long-term memory: shared team memory and per-bot knowledge."""

from .entry import MemoryEntry, MemoryFormatError, slugify
from .service import SCOPES, MemoryAccessError, MemoryService, RecallHit, Scope
from .store import MemoryStore, SearchHit

__all__ = [
    "SCOPES",
    "MemoryAccessError",
    "MemoryEntry",
    "MemoryFormatError",
    "MemoryService",
    "MemoryStore",
    "RecallHit",
    "Scope",
    "SearchHit",
    "slugify",
]
