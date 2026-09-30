import asyncio
import os
import time
from dataclasses import dataclass, field

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from . import toys

MODEL = os.getenv("ANTHROPIC_MODEL", "us.anthropic.claude-sonnet-4-6")
SP = (
    "You are a scheduling assistant. Be brief. Use the calendar agent for any "
    "question about someone's availability."
)


def options(sp: str = SP) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        model=MODEL,
        system_prompt=sp,
        mcp_servers={"toys": toys.server},
        allowed_tools=["Agent", "Read", "TaskStop", "mcp__toys__lookup_calendar"],
        agents={"calendar": toys.CALENDAR},
        setting_sources=[],
        permission_mode="bypassPermissions",
    )


@dataclass
class Event:
    """One thing the session saw, with the offset it was seen at."""

    at: float
    kind: str
    text: str = ""
    name: str = ""
    task: str = ""
    parent: str | None = None
    origin: dict | None = None
    file: str = ""
    raw: object = None


@dataclass
class Session:
    opts: ClaudeAgentOptions = field(default_factory=options)
    events: list[Event] = field(default_factory=list)

    async def __aenter__(self):
        self._t0 = time.monotonic()
        self._q: asyncio.Queue = asyncio.Queue()
        self._client = ClaudeSDKClient(self.opts)
        # connect() spawns the input stream as a task; query() would await it inline
        await self._client.connect(self._outbound())
        self._reader = asyncio.create_task(self._read())
        return self

    async def __aexit__(self, *exc):
        self._reader.cancel()
        await self._client.disconnect()
        return False

    async def _outbound(self):
        while True:
            text = await self._q.get()
            self._log("user", text=text)
            yield {"type": "user", "message": {"role": "user", "content": text}}

    def _log(self, kind: str, **kw) -> Event:
        e = Event(at=time.monotonic() - self._t0, kind=kind, **kw)
        self.events.append(e)
        return e

    async def _read(self):
        async for m in self._client.receive_messages():
            name = type(m).__name__
            if isinstance(m, AssistantMessage):
                for b in m.content:
                    if isinstance(b, TextBlock) and b.text.strip():
                        self._log("said", text=b.text.strip(), parent=m.parent_tool_use_id)
                    elif isinstance(b, ToolUseBlock):
                        self._log("call", name=b.name, raw=b.input)
            elif isinstance(m, UserMessage):
                for b in m.content if isinstance(m.content, list) else []:
                    if isinstance(b, ToolResultBlock):
                        self._log("result", text=str(b.content), raw=b)
            elif isinstance(m, ResultMessage):
                self._log("turn", text=m.subtype, origin=m.origin)
            elif name.startswith("Task"):
                self._log(
                    name.replace("Message", ""),
                    task=getattr(m, "task_id", ""),
                    text=str(getattr(m, "status", "")),
                    file=getattr(m, "output_file", "") or "",
                )
            elif isinstance(m, SystemMessage):
                self._log("system", text=m.subtype)

    async def say(self, text: str):
        await self._q.put(text)

    async def until(self, pred, timeout: float = 90) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if pred(self.events):
                return True
            await asyncio.sleep(0.05)
        return False

    def of(self, *kinds: str) -> list[Event]:
        return [e for e in self.events if e.kind in kinds]

    def said(self) -> list[Event]:
        """What the main agent told the user, excluding subagent chatter."""
        return [e for e in self.events if e.kind == "said" and e.parent is None]
