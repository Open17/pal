"""How fast the bots type, so people watching can follow along."""

from __future__ import annotations

#: Milliseconds between keys for short text: a quick human typist.
KEY_DELAY_MS = 45
#: Long text speeds up to finish within about this long...
TYPING_BUDGET_MS = 15000
#: ...but never faster than this between keys.
MIN_KEY_DELAY_MS = 8


def key_delay_ms(length: int) -> int:
    """The pause between keystrokes for typing ``length`` characters."""

    if length <= 0:
        return KEY_DELAY_MS
    return max(MIN_KEY_DELAY_MS, min(KEY_DELAY_MS, TYPING_BUDGET_MS // length))
