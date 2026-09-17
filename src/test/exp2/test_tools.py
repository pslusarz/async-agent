import threading

import pytest

from main.exp2.agent import TOOL_PENDING, Agent
from main.exp2.tools import TEMPERATURE, Tool, temperature

SP = "Answer in one short sentence."
Q = "What is the temperature in Warsaw, MO?"


def test_a_tool_call_becomes_a_task_node_that_later_holds_the_result():
    a = Agent(sp=SP, tools=[temperature])
    q = a.post(Q)
    task = a.wait_for_task(q)

    assert task.text == TOOL_PENDING
    assert task.role == "assistant"
    assert task.parent == q.id

    answer = a.wait_for(q)
    assert "72" in answer.text
    assert a.board[task.id].result == "72"


def test_post_returns_before_the_tool_finishes():
    gate = threading.Event()

    def slow(agent, node, city, state):
        gate.wait(5)
        agent.result(node, "72")

    a = Agent(sp=SP, tools=[Tool(TEMPERATURE, slow)])
    q = a.post(Q)
    task = a.wait_for_task(q)

    assert task.result is None
    with pytest.raises(TimeoutError):
        a.wait_for(q, timeout=1)

    gate.set()
    assert "72" in a.wait_for(q).text


def test_followup_sees_the_result_on_the_board():
    a = Agent(sp=SP, tools=[temperature])
    q = a.post(Q)
    a.wait_for(q)
    task = a.wait_for_task(q)

    r = a.wait_for("So what is the temperature? Answer with the number.", parent=task.id)
    assert "72" in r.text
    assert a.board.root_of(r.id) == a.board.root_of(q.id)


def test_plain_question_still_answers_without_a_tool():
    a = Agent(sp=SP, tools=[temperature])
    r = a.wait_for("What is the capital of France?")

    assert "Paris" in r.text
    assert r.result is None
