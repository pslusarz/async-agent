import asyncio

from main.exp1.agent import Agent
from main.exp1.tools import DENIED, FINISHED, kill, stuck_temperature, tail

SP = (
    "Tools run asynchronously. A tool call returns a task id immediately, not a result. "
    "Use the tail tool on that task id to check progress. If the user asks you to stop or "
    "kill a task, use the kill tool on that task id."
)


async def test_user_can_have_a_stuck_tool_killed():
    async with Agent(sp=SP, tools=[stuck_temperature, tail, kill]) as a:
        a.send("What is the temperature in Warsaw, MO?")
        r1 = await a.ask("Do you know the answer yet?")
        r2 = await a.ask("That tool is stuck. Please kill it.")

        tid = next(p.id for p in a.thread.walk() if p.kind == "tool_result")
        task = a.tasks[tid]

        assert task.done
        assert task.cancel.is_set()
        assert a.thread[tid].text == "killed"
        await asyncio.sleep(0)
        assert task.runner.done()

        await tail.fn(a, task=tid)
        await kill.fn(a, task=tid)

    probes = [p.text for p in a.thread.walk() if p.kind == "probe"]
    assert probes[0] == DENIED
    assert probes[-2:] == [FINISHED, FINISHED]
    assert r1.text and r2.text
