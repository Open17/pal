from __future__ import annotations

from typing import Any

from pal.tools import ToolContext, ToolProvider


def handlers(provider: ToolProvider, bot_id: str = "atlas") -> dict[str, Any]:
    return {t.name: t.handler for t in provider.tools(ToolContext(bot_id))}


def text(result: dict[str, Any]) -> str:
    return "\n".join(block["text"] for block in result["content"])
