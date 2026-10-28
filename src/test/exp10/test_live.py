"""The model against the harness. Recorded once, then replayed from llm_cache.jsonl.

Tools are gated rather than timed, so what the running list shows at each turn is
decided by the test and a replay sends exactly the request that was recorded.
"""

import pytest

from main.exp5.tools import STUCK
from main.exp10.agent import Agent
from main.exp10.tools import kill, stuck_temperature, tail

pytestmark = pytest.mark.live

Q = "What is the weather like in Columbia, MO and Washington, DC?"


def tool_results(a):
    return [b["content"] for e in a.log if e.kind == "tool_results" for b in e.content]


def test_a_joke_while_two_lookups_run_then_one_answer_for_both(gates):
    tool, open_ = gates
    a = Agent(tools=[tool, tail, kill])
    q = a.post(Q)
    assert a.wait_until(lambda: len(a.calls) == 2, 60), a.errors

    joke = a.wait_for("tell me a joke while we wait", timeout=60)
    assert joke.text and "81" not in joke.text

    open_("Columbia")
    open_("Washington")
    answer = a.wait_for(q, timeout=60)
    assert "81" in answer.text and "64" in answer.text
    assert len([e for e in a.log if e.kind == "note"]) == 1
    a.stop()


def test_progress_is_answered_from_the_running_list(gates):
    tool, open_ = gates
    a = Agent(tools=[tool, tail, kill])
    q = a.post(Q)
    assert a.wait_until(lambda: len(a.calls) == 2, 60), a.errors
    open_("Columbia")
    assert a.wait_until(lambda: a.calls[1].result is not None, 10)

    reply = a.wait_for("how is it going?", timeout=60)
    # the partial result is in the list, so no look is needed to give it
    assert "81" in reply.text
    open_("Washington")
    a.wait_for(q, timeout=60)
    a.stop()


def test_asking_again_does_not_start_a_second_lookup(gates):
    tool, open_ = gates
    a = Agent(tools=[tool, tail, kill])
    q = a.post("What is the temperature in Columbia, MO?")
    assert a.wait_until(lambda: len(a.calls) == 1, 60), a.errors
    a.wait_for("Could you look up Columbia, MO for me?", timeout=60)
    # either the list told it so, or the refusal did
    assert len(a.tasks) == 1
    open_("Columbia")
    assert "81" in a.wait_for(q, timeout=60).text
    a.stop()


def test_the_user_drops_one_city_and_gets_the_other(gates):
    tool, open_ = gates
    a = Agent(tools=[tool, tail, kill])
    q = a.post(Q)
    assert a.wait_until(lambda: len(a.calls) == 2, 60), a.errors
    open_("Columbia")
    assert a.wait_until(lambda: a.calls[1].result is not None, 10)

    a.wait_for("never mind Washington, Columbia is all I need", timeout=60)
    dc = next(c for c in a.calls.values() if c.args["city"] == "Washington")
    assert dc.killed
    assert "81" in a.wait_for(q, timeout=60).text
    a.stop()


def test_an_overdue_lookup_is_inspected_and_killed():
    a = Agent(tools=[stuck_temperature, tail, kill], timeout_cap=1.0)
    a.post("What is the temperature in Columbia, MO?")
    assert a.wait_until(lambda: 1 in a.calls and a.calls[1].killed, 90), a.errors
    assert any(STUCK in r for r in tool_results(a))
    a.stop()


def test_starting_the_lookups_is_not_followed_by_a_second_message(gates):
    tool, open_ = gates
    a = Agent(tools=[tool, tail, kill])
    q = a.post(Q)
    assert a.wait_until(lambda: len(a.calls) == 2, 60), a.errors
    open_("Columbia")
    open_("Washington")
    a.wait_for(q, timeout=60)
    a.stop()
    report = next(e.id for e in a.log if e.kind == "note")
    before = [e.text for e in a.log if a._spoken(e) and e.id < report]
    assert len(before) <= 1, before
