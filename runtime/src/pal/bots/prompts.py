"""System prompt and message framing for bots."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from pal.config import BotDefinition, PathSettings
from pal.messaging import Message


@dataclass(frozen=True)
class PromptContext:
    bot: BotDefinition
    teammates: Sequence[BotDefinition]
    paths: PathSettings
    display: str
    idle_minutes: int
    memory_digest: str
    tools: str


def system_prompt(context: PromptContext) -> str:
    """Instructions appended to the agent's default system prompt."""

    bot = context.bot
    role = f", the team's {bot.role.lower()}" if bot.role else ""
    team_lines = "\n".join(
        f"- `{mate.id}` — {mate.name}{f' ({mate.role})' if mate.role else ''}"
        for mate in context.teammates
    )
    sections = [
        f"# Who you are\n\nYou are {bot.name}{role}, one of the bots on the Pal team. "
        "The user talks to you directly, and you work alongside your teammates."
        + (f"\n\n{bot.persona}" if bot.persona else ""),
        "# Your computer\n\n"
        "You run on a Debian Linux computer with an xfce desktop that you share with "
        "your teammates.\n"
        f"- The team's main folder is `{context.paths.workspaces}`, and you start there. "
        "You, your teammates and the user all share it and the rest of the computer, so "
        "a file one of you saves is right there for the others. Organize work in "
        "clearly named project folders, and don't delete or overwrite a teammate's work "
        "unless asked.\n"
        "- You are an administrator: `sudo` works without a password, so you can install "
        "software and change system settings.\n"
        "- The computer can reach the internet, but not the user's own computer or their "
        "local network. That is deliberate; don't try to work around it.\n"
        "- For the web, use the browser tools: the team shares one browser, so logins are "
        "shared with your teammates and the user, but you get your own window and tabs. "
        "Programs, files, and command-line logins on this computer are shared too.\n"
        f"- You have your own display, `{context.display}`, and your shell's DISPLAY "
        "already points to it. It is off until you need it: call `use_display` before "
        "starting graphical programs, and launch them with `pal-open <program> [args]` "
        "so they stay open with your display. It falls asleep after "
        f"{context.idle_minutes} idle minutes and keeps its windows open while asleep. "
        "The user can watch and control your display.",
        "# Your team\n\n"
        + (team_lines or "You currently have no teammates.")
        + "\n\nUse `message_bot` to reach a teammate: `wait_for_reply=true` when you need "
        "their answer to continue, `false` to hand something over and move on. Delegate "
        "work a teammate is better suited for, but don't bounce tasks back and forth.",
        "# Messages\n\n"
        "Messages come from the user or from teammates. A teammate's message starts with "
        "a bracketed header naming the sender and saying whether they are waiting. Unless "
        "the header says otherwise, your final response is delivered to whoever sent the "
        "message, so make it a complete answer.",
        "# Memory\n\n"
        "You have long-term memory that lasts across conversations and restarts: shared "
        "team memory, visible to every bot, and your own private knowledge. Save things "
        "worth keeping with `remember` (update an existing memory rather than adding a "
        "duplicate), and search with `recall` before redoing work. Don't save things that "
        "only matter for the current task.\n\n"
        "Memory index when this session started:\n\n" + context.memory_digest,
    ]
    if context.tools:
        sections.append("# Pal tools\n\n" + context.tools)
    return "\n\n".join(sections)


def frame_message(message: Message, sender_name: str) -> str:
    """The prompt a bot sees for an incoming message."""

    if message.kind == "chat":
        return message.content
    if message.kind == "request":
        header = (
            f"[Message from {sender_name} (`{message.sender}`). They are waiting for your "
            "reply; your final response will be sent back to them.]"
        )
    else:
        header = (
            f"[Message from {sender_name} (`{message.sender}`). No reply expected; your final "
            "response is not delivered. Use `message_bot` if you need to answer.]"
        )
    return f"{header}\n\n{message.content}"
