"""Tools for reading and writing long-term memory."""

from __future__ import annotations

from typing import Any

from claude_agent_sdk import SdkMcpTool, tool

from pal.memory import MemoryService, RecallHit

from ..base import ToolContext, ToolProvider, ToolResult, error_result, text_result

_SCOPE = {
    "type": "string",
    "enum": ["shared", "private"],
    "description": "'shared' is visible to the whole team; 'private' is your own knowledge.",
}


class MemoryTools(ToolProvider):
    name = "memory"
    description = "long-term memory: remember, recall, read_memory, forget"

    def __init__(self, memory: MemoryService) -> None:
        self.memory = memory

    def tools(self, context: ToolContext) -> list[SdkMcpTool[Any]]:
        memory, bot_id = self.memory, context.bot_id

        @tool(
            "remember",
            "Save something worth keeping beyond this conversation: facts about the user, "
            "decisions, how-tos, where things are. Pass `id` to update an existing memory "
            "instead of creating a duplicate.",
            {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short, specific title."},
                    "content": {"type": "string", "description": "The memory itself (markdown)."},
                    "description": {
                        "type": "string",
                        "description": "One line used to decide relevance later.",
                    },
                    "scope": _SCOPE,
                    "kind": {
                        "type": "string",
                        "description": "e.g. fact, preference, decision, howto, reference",
                    },
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "id": {"type": "string", "description": "Existing memory id to update."},
                },
                "required": ["title", "content", "scope"],
            },
        )
        async def remember(args: dict[str, Any]) -> ToolResult:
            entry = await memory.remember(
                author=bot_id,
                scope=args["scope"],
                title=args["title"],
                body=args["content"],
                description=args.get("description", ""),
                kind=args.get("kind") or "note",
                tags=args.get("tags") or (),
                entry_id=args.get("id"),
            )
            return text_result(f"Saved {args['scope']} memory `{entry.id}` ({entry.title}).")

        @tool(
            "recall",
            "Search shared memory and your private knowledge by keywords.",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "scope": {"type": "string", "enum": ["all", "shared", "private"]},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 25},
                },
                "required": ["query"],
            },
        )
        async def recall(args: dict[str, Any]) -> ToolResult:
            scope = args.get("scope", "all")
            scopes = ("shared", "private") if scope == "all" else (scope,)
            hits = await memory.recall(
                bot_id, args["query"], scopes=scopes, limit=int(args.get("limit", 8))
            )
            if not hits:
                return text_result("No matching memories.")
            return text_result("\n\n".join(_format_hit(hit) for hit in hits))

        @tool(
            "read_memory",
            "Read one memory in full by id.",
            {
                "type": "object",
                "properties": {"id": {"type": "string"}, "scope": _SCOPE},
                "required": ["id", "scope"],
            },
        )
        async def read_memory(args: dict[str, Any]) -> ToolResult:
            entry = await memory.read(args["scope"], bot_id, args["id"])
            if entry is None:
                return error_result(f"No {args['scope']} memory with id `{args['id']}`.")
            return text_result(entry.to_markdown())

        @tool(
            "forget",
            "Delete a memory that is wrong or no longer useful.",
            {
                "type": "object",
                "properties": {"id": {"type": "string"}, "scope": _SCOPE},
                "required": ["id", "scope"],
            },
        )
        async def forget(args: dict[str, Any]) -> ToolResult:
            if await memory.forget(args["scope"], bot_id, args["id"]):
                return text_result(f"Forgot `{args['id']}`.")
            return error_result(f"No {args['scope']} memory with id `{args['id']}`.")

        return [remember, recall, read_memory, forget]


def _format_hit(hit: RecallHit) -> str:
    entry = hit.entry
    when = f"{entry.updated_at:%Y-%m-%d}"
    header = f"[{hit.scope}] `{entry.id}` — {entry.title} (by {entry.author}, {when})"
    body = entry.body if len(entry.body) <= 1200 else entry.body[:1200] + " …(use read_memory)"
    return f"{header}\n{body}"
