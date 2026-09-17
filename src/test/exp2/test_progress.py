from main.exp2.agent import Agent
from main.exp2.tools import FINISHED, slow_temperature, tail, temperature

SP = (
    "Tools run in the background. Calling a tool returns a task id, not a result. "
    "When the user asks whether an answer is ready, call tail with that task id and "
    "report exactly what it says. Never start a second task for a question that "
    "already has one running."
)
Q = "What is the temperature in Warsaw, MO?"


def probes(a, node):
    return [c.result for m in a.board.walk(node) for c in m.calls if c.tool == "tail"]


def test_user_polls_progress_then_the_task_finishes():
    a = Agent(sp=SP, tools=[slow_temperature, tail])
    q = a.post(Q)
    task = a.wait_for_task(q)

    assert task.tool == "temperature"

    r1 = a.wait_for("Do you know the answer yet?", parent=task.msg)
    r2 = a.wait_for("Do you know the answer yet?", parent=task.msg)
    r3 = a.wait_for("Do you know the answer yet?", parent=task.msg)

    assert probes(a, task.msg)[:3] == ["30% complete", "60% complete", "90% complete"]
    assert "30" in r1.text
    assert "60" in r2.text
    assert "90" in r3.text

    assert a.board.calls[task.id].result == "72"


def test_progress_is_recorded_in_the_thread_under_the_question_that_asked():
    a = Agent(sp=SP, tools=[slow_temperature, tail])
    q = a.post(Q)
    task = a.wait_for_task(q)
    r1 = a.wait_for("Do you know the answer yet?", parent=task.msg)

    probe = next(m for m in a.board.walk(task.msg) if any(c.tool == "tail" for c in m.calls))
    assert a.board[probe.parent].text == "Do you know the answer yet?"
    assert a.board.root_of(probe.id) == a.board.root_of(task.msg)

    nodes = a.board.walk(task.msg)
    assert [m.role for m in nodes] == ["assistant", "user", "assistant", "assistant"]
    assert nodes[2].calls[0].tool == "tail"
    assert nodes[3].id == r1.id


def test_tail_reports_a_finished_task():
    a = Agent(sp=SP, tools=[temperature, tail])
    q = a.post(Q)
    a.wait_for(q)
    task = a.wait_for_task(q)

    assert tail.fn(a, task=task.id) == FINISHED
    assert a.board.calls[task.id].result == "72"
