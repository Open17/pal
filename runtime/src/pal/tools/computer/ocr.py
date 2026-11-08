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
    confidence: float


@dataclass(frozen=True)
class Line:
    text: str
    box: Box
    words: tuple[Word, ...]


def parse_words(tsv: str, *, min_confidence: float = 40) -> list[Word]:
    """The confident words in Tesseract TSV output (``tesseract img stdout tsv``)."""

    words = []
    for row in tsv.splitlines()[1:]:
        cols = row.split("\t")
        if len(cols) < 12 or cols[0] != "5":
            continue
        text = cols[11].strip()
        try:
            confidence = float(cols[10])
            box = Box(int(cols[6]), int(cols[7]), int(cols[8]), int(cols[9]))
        except ValueError:
            continue
        if text and confidence >= min_confidence:
            words.append(Word(text, box, confidence))
    return words


def merge(*readings: list[Word]) -> list[Word]:
    """Combine several readings of one image, keeping the surer of overlapping words."""

    kept: list[Word] = []
    for word in sorted((w for words in readings for w in words), key=lambda w: -w.confidence):
        if all(_overlap(word.box, other.box) < 0.5 for other in kept):
            kept.append(word)
    return kept


def group_lines(words: list[Word]) -> list[Line]:
    """Group words into lines by where they are on screen.

    Words join a line when they sit on the same row and follow its last word
    closely; wider gaps (between menu items, table columns) start a new line.
    """

    rows: list[list[Word]] = []
    for word in sorted(words, key=lambda w: w.box.left):
        for row in rows:
            last = row[-1].box
            height = max(last.height, word.box.height)
            gap = word.box.left - (last.left + last.width)
            if abs(_middle(last) - _middle(word.box)) <= height / 2 and -height / 2 <= gap <= (
                height * 1.5
            ):
                row.append(word)
                break
        else:
            rows.append([word])
    lines = []
    for row in rows:
        box = row[0].box
        for word in row[1:]:
            box = box.union(word.box)
        lines.append(Line(" ".join(w.text for w in row), box, tuple(row)))
    lines.sort(key=lambda line: (line.box.top, line.box.left))
    return lines


def parse_tsv(tsv: str, *, min_confidence: float = 40) -> list[Line]:
    """Lines of text in Tesseract TSV output."""

    return group_lines(parse_words(tsv, min_confidence=min_confidence))


def _middle(box: Box) -> float:
    return box.top + box.height / 2


def _overlap(a: Box, b: Box) -> float:
    """Intersection over union of two boxes."""

    width = min(a.left + a.width, b.left + b.width) - max(a.left, b.left)
    height = min(a.top + a.height, b.top + b.height) - max(a.top, b.top)
    if width <= 0 or height <= 0:
        return 0.0
    shared = width * height
    return shared / (a.width * a.height + b.width * b.height - shared)


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
