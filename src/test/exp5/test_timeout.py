import pytest

from main.exp5.agent import Agent, with_timeout
from main.exp5.tools import (
    ALMOST,
    STUCK,
    TEMPERATURE,
    fading_temperature,
    finishing_temperature,
    kill,
    new_thread,
    stuck_temperature,
    tail,
    temperature,
)

SP = "Tools run in the background. Calling one returns a task id, not a result."
Q = "What is the temperature in Warsaw, MO?"


def meta_calls(a, name):
    return [c for m in a.board.msgs.values() for c in m.calls if c.tool == name]


def test_schema_asks_for_an_expected_interval():
    s = with_timeout(TEMPERATURE)
    assert "timeout" in s["input_schema"]["required"]
    assert "seconds" in s["input_schema"]["properties"]["timeout"]["description"]
    assert "timeout" not in TEMPERATURE["input_schema"]["properties"]


def test_a_finished_task_leaves_no_pending_nudge():
    a = Agent(sp=SP, tools=[temperature, tail, kill], timeout_cap=0.5)
    q = a.post(Q)
    task = a.wait_for_task(q)
    a.wait_for(q)
    assert a.timers.get(task.id) is None
    assert not meta_calls(a, "tail")
    a.stop()


def test_an_overdue_task_is_inspected_and_killed():
    a = Agent(sp=SP, tools=[stuck_temperature, tail, kill], timeout_cap=1.0)
    q = a.post(Q)
    task = a.wait_for_task(q)

    assert a.wait_until(lambda: task.killed, timeout=90), a.errors

    tails = meta_calls(a, "tail")
    assert tails and STUCK in tails[0].result
    assert meta_calls(a, "kill")
    assert a.tasks[task.id].killed
    a.stop()


def test_a_tool_that_keeps_failing_goes_back_to_the_user_in_a_new_thread():
    a = Agent(
        sp=SP,
        tools=[stuck_temperature, tail, kill, new_thread],
        timeout_cap=1.0,
        max_retries=1,
    )
    q = a.post(Q)
    a.wait_for_task(q)

    assert a.wait_until(lambda: len(a.board.threads()) > 1, timeout=120), a.errors
    assert len(meta_calls(a, "kill")) == 2
    assert meta_calls(a, "new_thread")

    opener = a.board.threads()[-1]
    assert opener.role == "assistant" and opener.parent is None
    # the fresh branch has no killed ancestors, so a retry there is affordable again
    retry = a.board.add_call(
        a.board.post("assistant", parent=opener.id).id, "temperature", {}
    )
    assert a._attempts(retry.id) == 1
    a.stop()


def test_calls_made_side_by_side_do_not_spend_each_others_retries():
    a = Agent(sp=SP, tools=[stuck_temperature, tail, kill], timeout_cap=60.0)
    node = a.board.post("assistant")
    both = [
        a.board.add_call(node.id, "temperature", dict(city=c, state="MO"))
        for c in ("Warsaw", "Austin")
    ]
    for c in both:
        a.board.kill(c.id)

    assert [a._attempts(c.id) for c in both] == [1, 1]

    deeper = a.board.add_call(
        a.board.post("assistant", parent=node.id).id, "temperature", {}
    )
    a.board.kill(deeper.id)
    assert a._attempts(deeper.id) == 2
    a.stop()


@pytest.mark.realtime
def test_a_task_that_looks_almost_done_is_left_running_and_asked_about_again():
    a = Agent(
        sp=SP,
        tools=[fading_temperature, tail, kill, new_thread],
        timeout_cap=1.0,
        max_retries=0,
    )
    q = a.post(Q)
    task = a.wait_for_task(q)

    assert a.wait_until(lambda: task.killed, timeout=120), a.errors

    seen = [c.result for c in meta_calls(a, "tail")]
    assert seen[0] == ALMOST and STUCK in seen
    # the first nudge left it running, so a second one had to come from the timer
    assert a.nudged[task.id] >= 2
    assert not a.timers
    a.stop()


def test_a_task_left_running_is_allowed_to_finish():
    a = Agent(
        sp=SP, tools=[finishing_temperature, tail, kill, new_thread], timeout_cap=1.0
    )
    q = a.post(Q)
    task = a.wait_for_task(q)

    assert a.wait_until(lambda: task.result is not None, timeout=120), a.errors

    assert task.result == "72"
    assert [c.result for c in meta_calls(a, "tail")][0] == ALMOST
    assert not meta_calls(a, "kill")
    assert not a.timers
    a.stop()
