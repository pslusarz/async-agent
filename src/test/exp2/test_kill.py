import threading

from main.exp2.agent import TOOL_PENDING, Agent
from main.exp2.tools import DENIED, FINISHED, TEMPERATURE, Tool, kill, stuck_temperature, tail

SP = (
    "Tools run in the background. Calling a tool returns a task id, not a result. "
    "Use tail with that task id to check progress. If the user asks you to stop or "
    "kill a task, use kill with that task id."
)
Q = "What is the temperature in Warsaw, MO?"


def replies(a, node):
    return [m.text for m in a.board.walk(node.id) if m.text.startswith(("Progress for", "kill("))]


def test_user_can_have_a_stuck_tool_killed():
    a = Agent(sp=SP, tools=[stuck_temperature, tail, kill])
    node = a.post(Q)
    assert node.text == TOOL_PENDING

    r1 = a.post("Do you know the answer yet?", parent=node.id)
    r2 = a.post("That tool is stuck. Please kill it.", parent=node.id)

    task = a.tasks[node.id]
    assert task.done
    assert task.cancel.is_set()
    assert a.board[node.id].killed
    assert a.board[node.id].display.endswith("was killed before it returned]")

    assert DENIED in replies(a, node)[0]
    assert r1.text and r2.text


def test_a_killed_task_is_terminal():
    a = Agent(sp=SP, tools=[stuck_temperature, tail, kill])
    node = a.post(Q)
    a.kill(node.id)

    tail.fn(a, node.id, task=node.id)
    kill.fn(a, node.id, task=node.id)

    assert [m.text.split(": ", 1)[1] for m in a.board.walk(node.id) if m.role == "user"][-2:] == [
        FINISHED,
        FINISHED,
    ]


def test_a_late_result_from_a_killed_task_is_ignored():
    gate = threading.Event()

    def slow(agent, node, city, state):
        agent.watch(node, lambda: "working")
        gate.wait(5)
        agent.result(node, "72")

    a = Agent(sp=SP, tools=[Tool(TEMPERATURE, slow), tail, kill])
    node = a.post(Q)
    a.kill(node.id)

    gate.set()
    a.post("anything new?", parent=node.id)

    assert a.board[node.id].killed
    assert a.board[node.id].result is None
    assert a.board[node.id].terminal


def test_kill_releases_wait_for():
    a = Agent(sp=SP, tools=[stuck_temperature, tail, kill])
    node = a.post(Q)
    threading.Timer(0.2, lambda: a.kill(node.id)).start()

    done = a.wait_for(node, timeout=5)
    assert done.killed


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
    node = a.post(Q)
    assert started.wait(5)

    a.kill(node.id)
    assert stopped.wait(5)
