from types import SimpleNamespace

from main.exp5.agent import Agent, how_to_call, not_started
from main.exp5.tools import kill, tail, temperature

SP = "Tools run in the background. Calling one returns a task id, not a result."


def block(kind, **kw):
    return SimpleNamespace(type=kind, **kw)


def reply(*blocks):
    return SimpleNamespace(content=list(blocks))


def test_the_agent_is_told_which_tools_answer_at_once():
    a = Agent(sp=SP, tools=[temperature, tail, kill])
    assert how_to_call(("tail", "kill")) in a.sp
    assert "tail, kill are synchronous" in a.sp
    assert "Do not mix the two in one turn" in a.sp
    a.stop()


def test_a_background_call_made_alongside_a_synchronous_one_is_not_lost():
    """The turn that killed a task may ask to restart it in the same breath.

    Only the synchronous call runs, but the agent is told the rest did not, so the
    next turn can reissue it rather than believing work is under way that is not.
    """
    a = Agent(sp=SP, tools=[temperature, tail, kill], timeout_cap=60.0)
    node = a.board.post("assistant")
    doomed = a.board.add_call(node.id, "temperature", dict(city="Warsaw", state="MO"))
    a.board.kill(doomed.id)

    turns = [
        reply(
            block("text", text="Stopping that and trying again."),
            block("tool_use", name="kill", input=dict(task=doomed.id)),
            block(
                "tool_use",
                name="temperature",
                input=dict(city="Warsaw", state="MO", timeout=10),
            ),
        ),
        reply(block("text", text="All stopped.")),
    ]
    notes = []

    def fake(focus, schemas, note=None):
        notes.append(note)
        return turns.pop(0)

    a._call = fake
    a._take_turn(node.id)

    assert notes[0] is None
    assert notes[1] == not_started(["temperature"])
    assert not a.tasks, "the background call must not have been started"
    a.stop()
