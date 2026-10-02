import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..exp4.loop import Event, Session

# TaskStarted opens a task and TaskProgress keeps it open; anything else closes it
RUNNING = ("TaskStarted", "TaskProgress")
# the placeholder is a stringified dict, so the path runs up against a literal \n
OUTPUT = re.compile(r"output_file:\s*([^\s\\]+)")
QUIET = "nothing in its transcript yet"


def overdue(task: str, seconds: float, progress: str) -> str:
    return (
        "[automatic notice from the harness, not from the person you are talking to] "
        f"Task {task} has been running {seconds:g}s without finishing. Its transcript "
        f"shows: {progress}. Decide what to do with it: if it is still making progress, "
        "leave it alone. If it cannot make progress, stop it with TaskStop and tell the "
        "person what happened."
    )


def _trace(obj, out: list[str]):
    if isinstance(obj, dict):
        if obj.get("type") == "tool_use":
            out.append(f"called {obj.get('name')}")
        elif obj.get("type") == "text" and obj.get("text", "").strip():
            out.append(obj["text"].strip())
        for v in obj.values():
            _trace(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _trace(v, out)


@dataclass
class Watched(Session):
    """A Session that puts a clock on every background task the agent starts.

    The SDK has no timeout of its own, and the backgrounding schema belongs to the
    framework, so the interval is the harness's policy rather than the agent's
    judgement. Progress comes from the task's own transcript on disk, which the
    agent is forbidden to read but nothing stops the harness from reading.
    """

    after: float = 20.0
    timers: dict[str, asyncio.Task] = field(default_factory=dict)
    nudged: dict[str, int] = field(default_factory=dict)

    def _log(self, kind: str, **kw) -> Event:
        e = super()._log(kind, **kw)
        if kind == "TaskStarted":
            self._arm(e.task)
        elif kind.startswith("Task") and kind not in RUNNING and e.task:
            self._disarm(e.task)
        return e

    def _arm(self, task: str):
        self._disarm(task)
        self.timers[task] = asyncio.create_task(self._fire(task))

    def _disarm(self, task: str):
        t = self.timers.pop(task, None)
        if t is not None:
            t.cancel()

    async def _fire(self, task: str):
        await asyncio.sleep(self.after)
        self.nudged[task] = self.nudged.get(task, 0) + 1
        await self.say(overdue(task, self.after, self.progress(task)))
        # left running rather than stopped, so ask again after the same interval
        self._arm(task)

    def outfile(self, task: str) -> Path | None:
        for e in self.events:
            if e.kind == "result" and task in e.text and (m := OUTPUT.search(e.text)):
                return Path(m.group(1))
        return None

    def progress(self, task: str, keep: int = 2) -> str:
        p = self.outfile(task)
        if p is None or not p.exists():
            return QUIET
        seen: list[str] = []
        for line in p.read_text().splitlines():
            try:
                _trace(json.loads(line), seen)
            except json.JSONDecodeError:
                continue
        return "; ".join(seen[-keep:]) if seen else QUIET
