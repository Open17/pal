"""Find text on screen with Tesseract's word boxes."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Box:
    left: int
    top: int
    width: int
    height: int

    @property
    def center(self) -> tuple[int, int]:
        return self.left + self.width // 2, self.top + self.height // 2

    def union(self, other: Box) -> Box:
        left, top = min(self.left, other.left), min(self.top, other.top)
        right = max(self.left + self.width, other.left + other.width)
        bottom = max(self.top + self.height, other.top + other.height)
        return Box(left, top, right - left, bottom - top)

    def scaled(self, factor: float) -> Box:
        return Box(
            *(round(value / factor) for value in (self.left, self.top, self.width, self.height))
        )


@dataclass(frozen=True)
class Word:
    text: str
    box: Box
    line: tuple[int, int, int]  # block, paragraph, line


@dataclass(frozen=True)
class Line:
    text: str
    box: Box
    words: tuple[Word, ...]


def parse_tsv(tsv: str, *, min_confidence: float = 40) -> list[Line]:
    """Group Tesseract TSV output (``tesseract img stdout tsv``) into lines."""

    lines: dict[tuple[int, int, int], list[Word]] = {}
    for row in tsv.splitlines()[1:]:
        cols = row.split("\t")
        if len(cols) < 12 or cols[0] != "5":
            continue
        text = cols[11].strip()
        try:
            confidence = float(cols[10])
            key = (int(cols[2]), int(cols[3]), int(cols[4]))
            box = Box(int(cols[6]), int(cols[7]), int(cols[8]), int(cols[9]))
        except ValueError:
            continue
        if text and confidence >= min_confidence:
            lines.setdefault(key, []).append(Word(text, box, key))
    result = []
    for words in lines.values():
        box = words[0].box
        for word in words[1:]:
            box = box.union(word.box)
        result.append(Line(" ".join(w.text for w in words), box, tuple(words)))
    result.sort(key=lambda line: (line.box.top, line.box.left))
    return result


def _normalize(text: str) -> list[str]:
    return [token for token in re.split(r"\W+", text.lower()) if token]


def find(lines: list[Line], query: str) -> list[tuple[Line, Box]]:
    """Every place ``query`` appears, as the line and the box of the matching words."""

    wanted = _normalize(query)
    if not wanted:
        return []
    matches = []
    for line in lines:
        tokens = [_normalize(word.text) for word in line.words]
        flat = [(i, token) for i, parts in enumerate(tokens) for token in parts]
        for start in range(len(flat) - len(wanted) + 1):
            window = [token for _, token in flat[start : start + len(wanted)]]
            exact = window[:-1] == wanted[:-1] and window[-1].startswith(wanted[-1])
            if exact:
                first, last = flat[start][0], flat[start + len(wanted) - 1][0]
                box = line.words[first].box
                for word in line.words[first + 1 : last + 1]:
                    box = box.union(word.box)
                matches.append((line, box))
    return matches
