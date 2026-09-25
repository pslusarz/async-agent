import threading
import time
from dataclasses import dataclass
from typing import Callable

from .run import Work

FINISHED = (
    "task is finished and cannot be further interacted with, "
    "call the tool with new arguments to get a new id"
)


@dataclass
class Tool:
    """A tool the agent can call.

    A plain tool's `fn` takes the model's arguments and returns a Task for the
    harness to run on its own thread. A meta tool's `fn` takes the agent and
    returns a string at once, because it acts on tasks rather than becoming one.
    """

    schema: dict
    fn: Callable
    meta: bool = False

    @property
    def name(self) -> str:
        return self.schema["name"]


class Answer(Work):
    """Settles immediately."""

    def __init__(self, value: str):
        super().__init__()
        self.value = value

    def run(self) -> str:
        return self.value


class Waiting(Work):
    """Runs until `until` is set, reporting `status` in the meantime."""

    def __init__(self, value: str, until, status: str = ""):
        super().__init__()
        self.value = value
        self.until = until
        self.status = status

    def run(self) -> str:
        while not self.until.is_set():
            self.beat(0.02)
        return self.value


TEMPERATURE = dict(
    name="temperature",
    description="Get the current temperature in Fahrenheit for a US city.",
    input_schema=dict(
        type="object",
        properties=dict(
            city=dict(type="string", description="City name"),
            state=dict(type="string", description="Two-letter state code"),
        ),
        required=["city", "state"],
    ),
)

temperature = Tool(TEMPERATURE, lambda city, state: Answer("72"))


class Stepped(Work):
    """Advances one step every time it is tailed, then settles.

    Progress driven by the reader rather than the clock, so a test can decide
    exactly how far along the task is.
    """

    def __init__(self, steps: list[str], value: str, last: str):
        super().__init__()
        self.value = value
        self.last = last
        self._steps = iter(steps)
        self._arrived = threading.Event()

    def tail(self, lines: int) -> str:
        self.status = next(self._steps, "100% complete")
        if self.status.startswith(self.last):
            self._arrived.set()
        return super().tail(lines)

    def run(self) -> str:
        while not self._arrived.is_set():
            self.beat(0.02)
        return self.value


slow_temperature = Tool(
    TEMPERATURE,
    lambda city, state: Stepped(
        ["30% complete", "60% complete", "90% complete"], "72", "90"
    ),
)


NEEDS_FULL_STATE = (
    "error: state must be spelled out in full, not abbreviated. "
    "Retry this tool with the full state name."
)

strict_temperature = Tool(
    TEMPERATURE,
    lambda city, state: Answer("72" if len(state) > 2 else NEEDS_FULL_STATE),
)


DENIED = "Connecting to server.... access denied... retrying"


class Stuck(Work):
    """Never settles on its own, but winds down when asked."""

    def __init__(self, status: str):
        super().__init__()
        self.status = status

    def run(self) -> str:
        while True:
            self.beat(0.05)


stuck_temperature = Tool(TEMPERATURE, lambda city, state: Stuck(DENIED))


TAIL = dict(
    name="tail",
    description=(
        "Check on a running task. Pass the id shown as [task #N], and how many of its "
        "most recent output lines you want to see."
    ),
    input_schema=dict(
        type="object",
        properties=dict(
            task=dict(type="integer", description="Task id to inspect"),
            lines=dict(
                type="integer",
                description="How many recent lines to show, newest last. Defaults to 5.",
            ),
        ),
        required=["task"],
    ),
)


def _tail(agent, task: int, lines: int = 5) -> str:
    r = agent.tasks.get(task)
    if r is None:
        return f"no such task #{task}"
    if r.done:
        return FINISHED
    return r.tail(lines)


tail = Tool(TAIL, _tail, meta=True)


KILL = dict(
    name="kill",
    description="Stop a running task that is stuck or cannot make progress. Pass the task id.",
    input_schema=dict(
        type="object",
        properties=dict(task=dict(type="integer", description="Task id to stop")),
        required=["task"],
    ),
)


def _kill(agent, task: int) -> str:
    r = agent.tasks.get(task)
    if r is None:
        return f"no such task #{task}"
    if r.done:
        return FINISHED
    agent.kill(task)
    return "killed"


kill = Tool(KILL, _kill, meta=True)


def _noargs(name: str, description: str) -> dict:
    return dict(
        name=name,
        description=description,
        input_schema=dict(type="object", properties={}, required=[]),
    )


predict_future = Tool(
    _noargs("predict_future", "Predict what is coming. Call this before preparing."),
    lambda: Answer("a major earthquake is coming"),
)
prepare_for_earthquake = Tool(
    _noargs("prepare_for_earthquake", "Get advice for preparing for an earthquake."),
    lambda: Answer("store water, secure heavy shelves, keep shoes by the bed"),
)
prepare_for_gorgeous_weather = Tool(
    _noargs(
        "prepare_for_gorgeous_weather", "Get advice for preparing for lovely weather."
    ),
    lambda: Answer("plan a picnic and pack sunscreen"),
)


FREE = {"jane": "free 9-12", "jack": "free 10-14"}
STUCK_PERSON = "joe"
CALENDAR_STUCK = "connecting to calendar server... no response yet... retrying"

SCHEDULE = dict(
    name="schedule",
    description="Look up one person's free hours today. Call once per person.",
    input_schema=dict(
        type="object",
        properties=dict(person=dict(type="string", description="First name")),
        required=["person"],
    ),
)


def _schedule(person: str):
    who = person.strip().lower()
    if who == STUCK_PERSON:
        return Stuck(CALENDAR_STUCK)
    return Answer(FREE.get(who, "no calendar found"))


schedule = Tool(SCHEDULE, _schedule)


BOOK_ROOM = dict(
    name="book_room",
    description=(
        "Book a meeting room. Only call this once you know an hour that suits everyone. "
        "A booking does not exist until this tool has been called."
    ),
    input_schema=dict(
        type="object",
        properties=dict(
            start=dict(type="string", description="Start of the meeting, like '10:00'")
        ),
        required=["start"],
    ),
)

book_room = Tool(BOOK_ROOM, lambda start: Answer(f"room 3B is booked at {start}"))


class Countdown(Work):
    """Settles when its timer goes off, and reports how long is left."""

    def __init__(self, value: str, seconds: float):
        super().__init__()
        self.value = value
        self.seconds = seconds

    def run(self) -> str:
        due = time.monotonic() + self.seconds
        while (left := due - time.monotonic()) > 0:
            self.status = f"still running, about {max(0, round(left))}s to go"
            self.beat(min(0.05, left))
        return self.value


def timer(name: str, description: str, result: str, seconds: float = 5.0) -> Tool:
    return Tool(_noargs(name, description), lambda: Countdown(result, seconds))


build_time = timer(
    "build_time", "Find out how long the current build will take.", "12 minutes", 5.0
)
