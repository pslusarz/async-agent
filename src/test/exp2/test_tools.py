import threading

import pytest

from main.exp2.agent import TOOL_PENDING, Agent
from main.exp2.tools import TEMPERATURE, Tool, temperature

SP = "Answer in one short sentence."
Q = "What is the temperature in Warsaw, MO?"


def test_tool_call_returns_a_pending_node_that_later_holds_the_result():
    a = Agent(sp=SP, tools=[temperature])
    node = a.post(Q)

    assert node.text == TOOL_PENDING
    assert node.role == "assistant"
    assert a.board[node.parent].role == "user"

    done = a.wait_for(node)
    assert done.id == node.id
    assert done.result == "72"


def test_post_returns_before_the_tool_finishes():
    gate = threading.Event()

    def slow(agent, node, city, state):
        gate.wait(5)
        agent.result(node, "72")

    a = Agent(sp=SP, tools=[Tool(TEMPERATURE, slow)])
    node = a.post(Q)

    assert node.text == TOOL_PENDING
    assert a.board[node.id].result is None

    gate.set()
    assert a.wait_for(node).result == "72"


def test_followup_sees_the_result_on_the_board():
    a = Agent(sp=SP, tools=[temperature])
    node = a.post(Q)
    a.wait_for(node)

    r = a.post("So what is the temperature? Answer with the number.", parent=node.id)
    assert "72" in r.text
    assert a.board.root_of(r.id) == a.board.root_of(node.id)


def test_wait_for_times_out_when_no_result_arrives():
    def never(agent, node, city, state):
        pass

    a = Agent(sp=SP, tools=[Tool(TEMPERATURE, never)])
    node = a.post(Q)

    with pytest.raises(TimeoutError):
        a.wait_for(node, timeout=0.3)


def test_plain_question_still_answers_without_a_tool():
    a = Agent(sp=SP, tools=[temperature])
    r = a.post("What is the capital of France?")

    assert "Paris" in r.text
    assert r.result is None
