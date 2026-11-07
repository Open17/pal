"""A scripted stand-in for the agent SDK client."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock

Script = Callable[["FakeClient", str], Awaitable[str]]


class FakeClient:
    instances: list[FakeClient] = []

    def __init__(self, options: ClaudeAgentOptions, script: Script, *, fail_resume=False) -> None:
        self.options = options
        self.script = script
        self.fail_resume = fail_resume
        self.prompts: list[str] = []
        self.connected = False
        self.interrupted = False
        FakeClient.instances.append(self)

    async def connect(self, prompt: str | None = None) -> None:
        if self.fail_resume and self.options.resume:
            raise RuntimeError("no such session")
        self.connected = True

    async def query(self, prompt: str) -> None:
        self.prompts.append(prompt)

    async def receive_response(self) -> AsyncIterator[Any]:
        text = await self.script(self, self.prompts[-1])
        yield AssistantMessage(content=[TextBlock(text=text)], model=self.options.model or "")
        yield ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id=self.options.resume or f"session-{len(FakeClient.instances)}",
            result=text,
            total_cost_usd=0.01,
        )

    async def interrupt(self) -> None:
        self.interrupted = True

    async def disconnect(self) -> None:
        self.connected = False
