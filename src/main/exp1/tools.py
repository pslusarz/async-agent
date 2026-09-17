import asyncio
from dataclasses import dataclass
from typing import Callable

FINISHED = (
    "task is finished and cannot be further interacted with, "
    "call tool with new arguments to get a new id"
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


async def _temperature(agent, task: int, city: str, state: str):
    await agent.complete(task, "72")


temperature = Tool(TEMPERATURE, _temperature)


async def _slow_temperature(agent, task: int, city: str, state: str):
    steps = iter(["30% complete", "60% complete", "90% complete"])

    async def tail():
        s = next(steps, "100% complete")
        if s.startswith("90"):
            agent.spawn(agent.complete(task, "72"))
        return s

    agent.watch(task, tail)


slow_temperature = Tool(TEMPERATURE, _slow_temperature)


NEEDS_FULL_STATE = (
    "error: state must be spelled out in full, not abbreviated. "
    "Retry this tool with the full state name."
)


async def _strict_temperature(agent, task: int, city: str, state: str):
    if len(state) <= 2:
        await agent.complete(task, NEEDS_FULL_STATE)
    else:
        await agent.complete(task, "72")


strict_temperature = Tool(TEMPERATURE, _strict_temperature)


DENIED = "Connecting to server.... access denied... retrying"


async def _stuck_temperature(agent, task: int, city: str, state: str):
    async def tail():
        return DENIED

    agent.watch(task, tail)
    cancel = agent.tasks[task].cancel
    while not cancel.is_set():
        await asyncio.sleep(0.05)


stuck_temperature = Tool(TEMPERATURE, _stuck_temperature)


TAIL = dict(
    name="tail",
    description="Check the latest progress output of a running task. Pass the task id given in the 'started task N' result.",
    input_schema=dict(
        type="object",
        properties=dict(task=dict(type="integer", description="Task id to inspect")),
        required=["task"],
    ),
)


async def _tail(agent, task: int):
    t = agent.tasks.get(task)
    if t is None:
        return
    if t.done:
        agent.emit(agent.thread.post("probe", FINISHED, parent=task))
        return
    if t.tail is None:
        return
    agent.emit(agent.thread.post("probe", await t.tail(), parent=task))


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


async def _kill(agent, task: int):
    t = agent.tasks.get(task)
    if t is None:
        return
    if t.done:
        agent.emit(agent.thread.post("probe", FINISHED, parent=task))
        return
    await agent.kill(task)


kill = Tool(KILL, _kill, meta=True)
