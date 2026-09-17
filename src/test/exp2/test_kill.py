import threading

from main.exp2.agent import Agent
from main.exp2.tools import (
    DENIED,
    FINISHED,
    TEMPERATURE,
    Tool,
    kill,
    stuck_temperature,
    tail,
)

SP = (
    "Tools run in the background. Calling a tool returns a task id, not a result. "
    "Use tail with that task id to check progress. If the user asks you to stop or "
    "kill a task, use kill with that task id."
)
Q = "What is the temperature in Warsaw, MO?"


def replies(a, task):
    return [
        c.result
        for m in a.board.walk(task.msg)
        for c in m.calls
        if c.tool in ("tail", "kill")
    ]


def test_user_can_have_a_stuck_tool_killed():
    a = Agent(sp=SP, tools=[stuck_temperature, tail, kill])
    q = a.post(Q)
    task = a.wait_for_task(q)

    r1 = a.wait_for("Do you know the answer yet?", parent=task.msg)
    r2 = a.wait_for("That tool is stuck. Please kill it.", parent=task.msg)

    t = a.tasks[task.id]
    assert t.done
    assert t.cancel.is_set()
    assert a.board.calls[task.id].killed
    assert a.board.calls[task.id].display.endswith("was killed before it returned]")

    assert DENIED in replies(a, task)[0]
    assert r1.text and r2.text


def test_a_killed_task_is_terminal():
    a = Agent(sp=SP, tools=[stuck_temperature, tail, kill])
    q = a.post(Q)
    task = a.wait_for_task(q)
    a.kill(task.id)

    assert tail.fn(a, task=task.id) == FINISHED
    assert kill.fn(a, task=task.id) == FINISHED


def test_a_late_result_from_a_killed_task_is_ignored():
    gate = threading.Event()

    def slow(agent, node, city, state):
        agent.watch(node, lambda: "working")
        gate.wait(5)
        agent.result(node, "72")

    a = Agent(sp=SP, tools=[Tool(TEMPERATURE, slow), tail, kill])
    q = a.post(Q)
    task = a.wait_for_task(q)
    a.kill(task.id)

    gate.set()
    a.wait_for("anything new?", parent=task.msg)

    assert a.board.calls[task.id].killed
    assert a.board.calls[task.id].result is None
    assert a.board.calls[task.id].terminal


def test_kill_stops_a_looping_tool():
    started = threading.Event()
    stopped = threading.Event()

    def looper(agent, node, city, state):
        agent.watch(node, lambda: "working")
        started.set()
        while not agent.tasks[node].cancel.wait(0.02):
            pass
        stopped.set()

    a = Agent(sp=SP, tools=[Tool(TEMPERATURE, looper), tail, kill])
    q = a.post(Q)
    task = a.wait_for_task(q)
    assert started.wait(5)

    a.kill(task.id)
    assert stopped.wait(5)
