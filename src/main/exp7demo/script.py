import threading
from dataclasses import dataclass, field

from ..exp2.run import Work
from ..exp2.tools import Tool
from ..exp5.agent import DEFAULT_TIMEOUT
from ..exp7.agent import Agent as Live
from .director import REPLY


@dataclass
class Text:
    text: str
    type: str = "text"


@dataclass
class Use:
    name: str
    input: dict
    type: str = "tool_use"
    id: str = "scripted"


@dataclass
class Reply:
    """One canned model response, and how long the agent appears to think before it."""

    label: str
    delay: float
    content: list = field(default_factory=list)


def use(name: str, **args) -> Use:
    return Use(name, args)


def reply(label: str, delay: float, text: str = "", *uses: Use) -> Reply:
    return Reply(label, delay, ([Text(text)] if text else []) + list(uses))


class Script:
    """Stands in for the Anthropic client, handing back canned replies in order."""

    def __init__(self, replies: list[Reply], director):
        self.replies = list(replies)
        self.director = director
        self.seen: list[dict] = []
        self.messages = self

    def create(self, **kw) -> Reply:
        self.seen.append(kw)
        if not self.replies:
            raise RuntimeError("the script ran out of replies")
        r = self.replies.pop(0)
        self.director.gate(r.label, r.delay, REPLY)
        return r


class Scripted(Work):
    """A task whose progress is a list of lines, each one a beat of the demo.

    An `answer` of None is a task that never finishes: it runs out of progress and
    stalls, leaving the harness to notice and the agent to decide what to do.
    """

    def __init__(
        self,
        director,
        name: str,
        steps: list[tuple[str, float]],
        answer: str | None,
        lead: float = 0.0,
        settle_after: str = "",
        overdue_after: str = "",
    ):
        super().__init__()
        self.director = director
        self.name = name
        self.steps = steps
        self.answer = answer
        self.lead = lead
        self.settle_after = settle_after
        self.overdue_after = overdue_after

    def run(self) -> str:
        # tasks started together reach the gate in the order they were called in
        self.beat(self.lead)
        for status, delay in self.steps:
            self.director.gate(f"{self.name}: {status}", delay)
            self.beat()
            self.status = status
        while self.answer is None:
            self.beat(0.05)
        if self.settle_after:
            self.director.wait_played(self.settle_after)
            self.beat()
        self.director.gate(f"{self.name} returns {self.answer!r}", 1.0)
        self.beat()
        return self.answer


def scripted(director, schema: dict, steps, answer: str) -> Tool:
    name = schema["name"]
    return Tool(schema, lambda **kw: Scripted(director, name, list(steps), answer))


class Agent(Live):
    """exp7's agent with the model replaced by a script and its timer by the director.

    A wall-clock timeout would go off while the demo is paused and ask the script for
    a reply it does not have, so overdue is a beat like any other. Only a task that
    names an `overdue_after` cue is ever nudged about; everything else is left alone.
    """

    def __init__(self, cli, director, **kw):
        self._cli = cli
        self.director = director
        super().__init__(**kw)

    def _client(self):
        return self._cli

    def _arm(self, cid: int, due):
        task = self.tasks[cid].task
        cue = getattr(task, "overdue_after", "")
        if not cue:
            return
        # one-shot, so a task left running is not nudged about forever
        task.overdue_after = ""
        threading.Thread(
            target=self._nudge_after, args=(cid, cue, due), daemon=True
        ).start()

    def _nudge_after(self, cid: int, cue: str, due):
        self.director.wait_played(cue)
        if self.tasks[cid].done or self.director.aborted:
            return
        self.director.gate(f"harness notices task #{cid} is overdue", 1.4, REPLY)
        if self.tasks[cid].done or self.director.aborted:
            return
        self._fire(cid, float(due or DEFAULT_TIMEOUT))
