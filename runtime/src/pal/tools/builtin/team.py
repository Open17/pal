"""Tools for talking to the other bots on the team."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from claude_agent_sdk import SdkMcpTool, tool

from ..base import ToolContext, ToolProvider, ToolResult, error_result, text_result


@dataclass(frozen=True)
class TeamMember:
    id: str
    name: str
    role: str
    status: str


class TeamMessagingError(RuntimeError):
    """A message could not be delivered or answered; the text is shown to the bot."""


class TeamGateway(Protocol):
    """What the team tools need from the bot team."""

    def roster(self) -> list[TeamMember]: ...

    async def send(
        self, sender: str, recipient: str, content: str, *, wait_for_reply: bool
    ) -> str | None:
        """Deliver a message; return the reply when ``wait_for_reply`` is set."""
        ...

    async def react(self, bot_id: str, emoji: str) -> Any:
        """React to the message the bot is handling."""
        ...


class TeamTools(ToolProvider):
    name = "team"
    description = "talk to teammates and react to messages: list_bots, message_bot, react"

    def __init__(self, team: TeamGateway) -> None:
        self.team = team

    def tools(self, context: ToolContext) -> list[SdkMcpTool[Any]]:
        team, bot_id = self.team, context.bot_id

        @tool("list_bots", "List your teammates, their roles, and whether they are busy.", {})
        async def list_bots(args: dict[str, Any]) -> ToolResult:
            lines = [
                f"- {member.id} ({member.name}, {member.role or 'no role'}): {member.status}"
                for member in team.roster()
                if member.id != bot_id
            ]
            return text_result("\n".join(lines) or "You have no teammates.")

        @tool(
            "message_bot",
            "Send a message to a teammate. With wait_for_reply=true you get their answer back "
            "(use it to ask questions or delegate work you need the result of). With "
            "wait_for_reply=false the message is queued for them and you continue immediately.",
            {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Teammate id."},
                    "message": {"type": "string"},
                    "wait_for_reply": {"type": "boolean"},
                },
                "required": ["to", "message", "wait_for_reply"],
            },
        )
        async def message_bot(args: dict[str, Any]) -> ToolResult:
            try:
                reply = await team.send(
                    bot_id,
                    args["to"],
                    args["message"],
                    wait_for_reply=bool(args.get("wait_for_reply")),
                )
            except TeamMessagingError as exc:
                return error_result(str(exc))
            if reply is None:
                return text_result(f"Message queued for {args['to']}.")
            return text_result(f"Reply from {args['to']}:\n\n{reply}")

        @tool(
            "react",
            "React to the message you are answering with one emoji, like a tapback (👍 ❤️ 😂 "
            "🎉 👀 ✅). It shows on that message. When a reaction says everything (thanks, "
            "an acknowledgement, a simple 'ok'), react and end your turn without writing any "
            "text: then no message is sent. A new reaction replaces your earlier one.",
            {
                "type": "object",
                "properties": {"emoji": {"type": "string", "description": "A single emoji."}},
                "required": ["emoji"],
            },
        )
        async def react(args: dict[str, Any]) -> ToolResult:
            try:
                await team.react(bot_id, str(args.get("emoji", "")))
            except TeamMessagingError as exc:
                return error_result(str(exc))
            return text_result(
                f"Reacted {args['emoji'].strip()}. If that says it all, end your turn with no "
                "text and no message is sent."
            )

        return [list_bots, message_bot, react]
