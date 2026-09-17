from main.exp2.agent import TOOL_PENDING, Agent
from main.exp2.tools import NEEDS_FULL_STATE, strict_temperature

SP = "Tools run in the background. Calling a tool returns a task id, not a result."
Q = "What is the temperature in Warsaw, MO?"


def test_a_failed_task_is_retried_with_corrected_arguments():
    a = Agent(sp=SP, tools=[strict_temperature])
    first = a.post(Q)

    assert first.text == TOOL_PENDING
    assert first.args["state"] == "MO"
    assert a.wait_for(first).result == NEEDS_FULL_STATE

    second = a.post("Please deal with that and get the temperature.", parent=first.id)

    assert second.tool == "temperature"
    assert second.args["state"] == "Missouri"
    assert a.wait_for(second).result == "72"

    r = a.post("So what is the temperature?", parent=second.id)
    assert "72" in r.text


def test_both_attempts_stay_in_one_thread():
    a = Agent(sp=SP, tools=[strict_temperature])
    first = a.post(Q)
    a.wait_for(first)
    second = a.post("Please deal with that and get the temperature.", parent=first.id)
    a.wait_for(second)

    assert a.board.root_of(second.id) == a.board.root_of(first.id)
    assert len(a.board.threads()) == 1

    tools = [m for m in a.board.walk(a.board.threads()[0].id) if m.tool]
    assert [m.args["state"] for m in tools] == ["MO", "Missouri"]
    assert [m.result for m in tools] == [NEEDS_FULL_STATE, "72"]
