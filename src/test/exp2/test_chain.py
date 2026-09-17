from main.exp2.agent import Agent
from main.exp2.tools import (
    predict_future,
    prepare_for_earthquake,
    prepare_for_gorgeous_weather,
)

SP = "Tools run in the background. Calling a tool returns a task id, not a result."
TOOLS = [predict_future, prepare_for_earthquake, prepare_for_gorgeous_weather]
Q = "how should I prepare for the future"


def test_one_question_drives_two_chained_tool_calls():
    a = Agent(sp=SP, tools=TOOLS)
    q = a.post(Q)

    assert not a.board.answered(q.id)

    answer = a.wait_for(q)

    chain = [m for m in a.board.walk(q.id) if m.tool]
    assert [m.tool for m in chain] == ["predict_future", "prepare_for_earthquake"]

    # each call hangs off the one that motivated it, ending in prose
    assert chain[0].parent == q.id
    assert chain[1].parent == chain[0].id
    assert answer.parent == chain[1].id
    assert "earthquake" in answer.text.lower()
    assert not a.errors


def test_every_node_in_the_chain_ends_up_answered():
    a = Agent(sp=SP, tools=TOOLS)
    q = a.post(Q)
    a.wait_for(q)

    assert all(a.board.answered(m.id) for m in a.board.walk(q.id))


def test_a_pending_task_leaves_its_ancestors_unanswered():
    a = Agent(sp=SP, tools=TOOLS)
    q = a.post(Q)
    task = a.wait_for_task(q)

    if not task.terminal:
        assert not a.board.answered(task.id)
        assert not a.board.answered(q.id)

    a.wait_for(q)
    assert a.board.answered(q.id)
