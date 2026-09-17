from dataclasses import dataclass
from typing import Callable


FINISHED = (
    "task is finished and cannot be further interacted with, "
    "call the tool with new arguments to get a new id"
)


@dataclass
class Tool:
    schema: dict
    fn: Callable
    meta: bool = False

    @property
    def name(self) -> str:
        return self.schema["name"]


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


def _temperature(agent, node: int, city: str, state: str):
    agent.result(node, "72")


temperature = Tool(TEMPERATURE, _temperature)


def _slow_temperature(agent, node: int, city: str, state: str):
    steps = iter(["30% complete", "60% complete", "90% complete"])

    def tail():
        s = next(steps, "100% complete")
        if s.startswith("90"):
            agent.result(node, "72")
        return s

    agent.watch(node, tail)


slow_temperature = Tool(TEMPERATURE, _slow_temperature)


NEEDS_FULL_STATE = (
    "error: state must be spelled out in full, not abbreviated. "
    "Retry this tool with the full state name."
)


def _strict_temperature(agent, node: int, city: str, state: str):
    agent.result(node, "72" if len(state) > 2 else NEEDS_FULL_STATE)


strict_temperature = Tool(TEMPERATURE, _strict_temperature)


DENIED = "Connecting to server.... access denied... retrying"


def _stuck_temperature(agent, node: int, city: str, state: str):
    agent.watch(node, lambda: DENIED)
    cancel = agent.tasks[node].cancel
    while not cancel.wait(0.05):
        pass


stuck_temperature = Tool(TEMPERATURE, _stuck_temperature)


TAIL = dict(
    name="tail",
    description="Check the latest progress of a running task. Pass the id shown as [task #N].",
    input_schema=dict(
        type="object",
        properties=dict(task=dict(type="integer", description="Task id to inspect")),
        required=["task"],
    ),
)


def _tail(agent, task: int) -> str:
    t = agent.tasks.get(task)
    if t is None:
        return f"no such task #{task}"
    if t.done:
        return FINISHED
    return t.tail() if t.tail else "no progress reported yet"


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
    t = agent.tasks.get(task)
    if t is None:
        return f"no such task #{task}"
    if t.done:
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


def _predict_future(agent, node: int):
    agent.result(node, "a major earthquake is coming")


def _prepare_for_earthquake(agent, node: int):
    agent.result(node, "store water, secure heavy shelves, keep shoes by the bed")


def _prepare_for_gorgeous_weather(agent, node: int):
    agent.result(node, "plan a picnic and pack sunscreen")


predict_future = Tool(
    _noargs("predict_future", "Predict what is coming. Call this before preparing."),
    _predict_future,
)
prepare_for_earthquake = Tool(
    _noargs("prepare_for_earthquake", "Get advice for preparing for an earthquake."),
    _prepare_for_earthquake,
)
prepare_for_gorgeous_weather = Tool(
    _noargs("prepare_for_gorgeous_weather", "Get advice for preparing for lovely weather."),
    _prepare_for_gorgeous_weather,
)
