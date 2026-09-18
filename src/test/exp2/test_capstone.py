import time

from main.exp2.agent import Agent
from main.exp2.tools import CALENDAR_STUCK, kill, schedule, tail

SP = (
    "Tools run in the background. Calling a tool returns a task id, not a result. "
    "Use tail with a task id to check progress, and kill with a task id to stop a "
    "task the user no longer wants."
)
Q = "find me the earliest time when Jane, Jack and Joe can meet"


def until(cond, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def calls_of(a, q):
    return [c for m in a.board.walk(q.id) for c in m.calls]


def person(c):
    return c.args["person"].strip().lower()


def test_meeting_is_scheduled_after_the_stuck_lookup_is_abandoned():
    a = Agent(sp=SP, tools=[schedule, tail, kill])
    q = a.post(Q)

    # the agent asks for all three calendars in one turn
    first = a.wait_for_task(q)
    node = a.board[first.msg]
    assert {person(c) for c in node.calls} == {"jane", "jack", "joe"}

    # Jane and Jack come back, Joe hangs
    joe = next(c for c in node.calls if person(c) == "joe")
    assert until(lambda: all(c.terminal for c in node.calls if c is not joe))
    assert not joe.terminal
    assert not node.terminal
    assert not a.board.answered(q.id)

    # user asks how it is going, and the agent reports Joe is stuck
    progress = a.wait_for("how is that going?", parent=node.id)
    probes = [c.result for m in a.board.walk(node.id) for c in m.calls if c.tool == "tail"]
    assert CALENDAR_STUCK in probes
    assert progress.text

    # user gives up on Joe
    a.wait_for("fine, forget Joe, just get me a time for Jane and Jack", parent=node.id)
    assert joe.killed
    assert a.tasks[joe.id].cancel.is_set()
    assert node.terminal

    # with every placeholder resolved the agent can answer the original question
    answer = a.wait_for(q)
    assert "10" in answer.text
    assert not a.errors
