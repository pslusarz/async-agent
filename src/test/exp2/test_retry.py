from main.exp2.agent import Agent
from main.exp2.tools import NEEDS_FULL_STATE, strict_temperature

SP = "Tools run in the background. Calling a tool returns a task id, not a result."
Q = "What is the temperature in Warsaw, MO?"


def test_one_post_drives_the_whole_react_loop():
    a = Agent(sp=SP, tools=[strict_temperature])
    q = a.post(Q)

    answer = a.wait_for(q)
    assert "72" in answer.text

    tried = [c for m in a.board.walk(q.id) for c in m.calls]
    assert [c.args["state"] for c in tried] == ["MO", "Missouri"]
    assert [c.result for c in tried] == [NEEDS_FULL_STATE, "72"]
    assert not a.errors


def test_both_attempts_stay_in_one_thread():
    a = Agent(sp=SP, tools=[strict_temperature])
    q = a.post(Q)
    answer = a.wait_for(q)

    assert a.board.root_of(answer.id) == q.id
    assert len(a.board.threads()) == 1
