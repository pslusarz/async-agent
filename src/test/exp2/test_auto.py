import pytest

from main.exp2.agent import Agent
from main.exp2.tools import NEEDS_FULL_STATE, TEMPERATURE, Tool, strict_temperature

SP = "Tools run in the background. Calling a tool returns a task id, not a result."
Q = "What is the temperature in Warsaw, MO?"


def test_one_post_drives_the_whole_react_loop():
    a = Agent(sp=SP, tools=[strict_temperature], auto=True)
    first = a.post(Q)

    assert first.args["state"] == "MO"
    answer = a.wait_for_reply(first)

    assert "72" in answer.text
    tools = [m for m in a.board.walk(a.board.threads()[0].id) if m.tool]
    assert [m.args["state"] for m in tools] == ["MO", "Missouri"]
    assert [m.result for m in tools] == [NEEDS_FULL_STATE, "72"]


def test_without_auto_nothing_happens_until_asked():
    a = Agent(sp=SP, tools=[strict_temperature])
    first = a.post(Q)
    a.wait_for(first)

    with pytest.raises(TimeoutError):
        a.wait_for_reply(first, timeout=2)


def test_a_looping_tool_is_capped():
    calls = []

    def never_happy(agent, node, city, state):
        calls.append(state)
        agent.result(node, NEEDS_FULL_STATE)

    a = Agent(sp=SP, tools=[Tool(TEMPERATURE, never_happy)], auto=True, max_auto=2)
    first = a.post(Q)
    a.wait_for(first)

    a.stop()
    assert len(calls) <= a.max_auto + 1
    assert not a.errors


def test_a_human_post_refills_the_budget():
    a = Agent(sp=SP, tools=[strict_temperature], auto=True)
    first = a.post(Q)
    a.wait_for_reply(first)
    root = a.board.root_of(first.id)

    assert a._auto[root] > 0

    a.post("Just say OK. Do not call any tool.", parent=first.id)
    assert a._auto[root] == 0
    assert not a.errors
