import threading
import time

from ..exp2.run import Work
from ..exp2.tools import KILL, TEMPERATURE, Answer, Stuck, Tool
from ..exp2.tools import TAIL as LOOK

UNCHANGED = (
    "(nothing has moved since you last looked; you will be told when it does, "
    "so there is nothing to gain by looking again now)"
)


def _tail(agent, task: int, lines: int = 5) -> str:
    r = agent.tasks.get(task)
    if r is None:
        return f"no such task #{task}"
    if r.killed:
        return "that task was killed before it returned"
    # the outcome, not a brush-off: being told to call again reads as "the result is lost"
    if r.future.done():
        return f"that task has finished, and returned: {r.future.result()}"
    out = r.tail(lines)
    if out == agent.seen.get(task):
        return f"{out}\n{UNCHANGED}"
    agent.seen[task] = out
    return out


tail = Tool(LOOK, _tail, synchronous=True)

STUCK = "I'm stuck and cannot make progress."
ALMOST = "almost done..."

temperature = Tool(TEMPERATURE, lambda city, state: Answer("72"))
stuck_temperature = Tool(TEMPERATURE, lambda city, state: Stuck(STUCK))


class Fading(Work):
    """Almost done for a while, then stuck for good, and never settles.

    Keyed to the clock rather than to being looked at, so two looks in quick
    succession agree with each other the way a real task would.
    """

    def __init__(self, after: float):
        super().__init__()
        self.due = time.monotonic() + after

    def tail(self, lines: int) -> str:
        self.status = ALMOST if time.monotonic() < self.due else STUCK
        return super().tail(lines)

    def run(self) -> str:
        while True:
            self.beat(0.05)


class Finishing(Work):
    """Almost done, and settles shortly after someone has looked."""

    def __init__(self, value: str):
        super().__init__()
        self.value = value
        self.status = ALMOST
        self._seen = threading.Event()

    def tail(self, lines: int) -> str:
        self._seen.set()
        return super().tail(lines)

    def run(self) -> str:
        while not self._seen.is_set():
            self.beat(0.05)
        self.beat(0.2)
        return self.value


fading_temperature = Tool(TEMPERATURE, lambda city, state: Fading(6.0))
finishing_temperature = Tool(TEMPERATURE, lambda city, state: Finishing("72"))


def _kill(agent, task: int) -> str:
    r = agent.tasks.get(task)
    if r is None:
        return f"no such task #{task}"
    if r.done:
        return "that task is already over, so there was nothing to stop"
    agent.kill(task)
    return agent.note_kill(task)


kill = Tool(KILL, _kill, synchronous=True)


NEW_THREAD = dict(
    name="new_thread",
    description=(
        "Say something in a new thread rather than in the one the conversation is "
        "currently in. Use this when the thread you are in has run its course and "
        "what you have to say starts something fresh."
    ),
    input_schema=dict(
        type="object",
        properties=dict(
            text=dict(type="string", description="What to say, in plain prose")
        ),
        required=["text"],
    ),
)


def _new_thread(agent, text: str) -> str:
    m = agent.board.post("assistant", text)
    return f"said in a new thread, #{m.id}"


new_thread = Tool(NEW_THREAD, _new_thread, synchronous=True)
