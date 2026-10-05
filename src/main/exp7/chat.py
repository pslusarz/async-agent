import threading
from dataclasses import dataclass, field

from ..exp2.board import Call
from ..exp5.chat import Chat as Threaded

BROKEN = ("failed:", "stopped before finishing:")


@dataclass
class Widget:
    """What the UI knows about one tool call: its name, its arguments, and how it went."""

    id: int
    tool: str
    args: dict = field(default_factory=dict)
    state: str = "running"
    msg: int = 0

    @property
    def label(self) -> str:
        return ", ".join(f"{k}={v}" for k, v in self.args.items())


def outcome(call: Call) -> str:
    if call.killed or (call.result or "").startswith(BROKEN):
        return "failed"
    return "done"


class Chat(Threaded):
    """The transcript, with each tool call kept beside the turn that started it."""

    def __init__(self, agent):
        super().__init__(agent)
        self._calls: dict[int, Widget] = {}
        self.version = 0
        self._moved = threading.Condition()
        agent.listener = self._on_call
        agent.on_change = self._bump

    def say(self, text: str):
        super().say(text)
        self._bump()

    def calls(self, msg: int) -> list[Widget]:
        return [w for w in self._calls.values() if w.msg == msg]

    def _said(self):
        # a turn that only started tools has no words, but it is where they belong
        b = self.agent.board
        return [
            m
            for root in b.threads()
            for m in b.walk(root.id)
            if self._shown(m) or self.calls(m.id)
        ]

    def wait(self, seen: int, timeout: float = 20.0) -> int:
        """Block until the transcript has moved past `seen`, or long enough to say so."""
        with self._moved:
            self._moved.wait_for(lambda: self.version != seen, timeout)
            return self.version

    def _bump(self):
        with self._moved:
            self.version += 1
            self._moved.notify_all()

    def _on_call(self, kind: str, call: Call):
        # meta calls act on tasks rather than becoming one, so there is nothing to watch
        if self.agent.tools[call.tool].meta:
            return
        if kind == "started":
            self._calls[call.id] = Widget(
                call.id, call.tool, dict(call.args), msg=call.msg
            )
        elif call.id in self._calls:
            self._calls[call.id].state = outcome(call)
