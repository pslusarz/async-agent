import pytest

from main.exp2.agent import Agent
from main.exp2.tools import NEEDS_FULL_STATE, TEMPERATURE, Tool, strict_temperature

SP = "Tools run in the background. Calling a tool returns a task id, not a result."
Q = "What is the temperature in Warsaw, MO?"


def test_a_looping_tool_is_capped():
    calls = []

    def never_happy(agent, node, city, state):
        calls.append(state)
        agent.result(node, NEEDS_FULL_STATE)

    a = Agent(sp=SP, tools=[Tool(TEMPERATURE, never_happy)], max_auto=2)
    q = a.post(Q)

    with pytest.raises(TimeoutError):
        a.wait_for(q, timeout=12)

    assert len(calls) <= a.max_auto + 1
    assert not a.errors


def test_a_human_post_refills_the_budget():
    a = Agent(sp=SP, tools=[strict_temperature])
    q = a.post(Q)
    a.wait_for(q)
    root = a.board.root_of(q.id)

    assert a._auto[root] > 0

    a.wait_for("Just say OK. Do not call any tool.", parent=q.id)
    assert a._auto[root] == 0
    assert not a.errors
