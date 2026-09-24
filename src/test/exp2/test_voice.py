from main.exp2.agent import Agent
from main.exp2.board import Board
from main.exp2.chat import Chat
from main.exp2.tools import build_time, kill, schedule, stuck_temperature, tail

MARKUP = ("+--", "|  ", "[#")

SP = (
    "Tools run in the background. Calling a tool returns a task id, not a result. "
    "Use tail with that task id to check progress. If the user asks you to stop or "
    "kill a task, use kill with that task id."
)


def leaks(text: str) -> list[str]:
    return [m for m in MARKUP if m in text]


def spoken(a) -> list[str]:
    return [m.text for m in a.board.msgs.values() if m.role == "assistant" and m.text]


def test_the_agent_does_not_speak_in_board_markup_when_asked_to_kill_a_stuck_tool():
    a = Agent(sp=SP, tools=[stuck_temperature, tail, kill])
    q = a.post("What is the temperature in Warsaw, MO?")
    task = a.wait_for_task(q)
    a.wait_for("Do you know the answer yet?", parent=task.msg)
    a.wait_for("That tool is stuck. Please kill it.", parent=task.msg)

    assert spoken(a)
    assert {t: leaks(t) for t in spoken(a) if leaks(t)} == {}


def test_a_follow_up_while_a_tool_runs_reads_plainly():
    a = Agent(sp=SP, tools=[build_time, tail, kill])
    c = Chat(a)
    c.say("how long will the build take?")
    q = a.board.msgs[1]
    a.wait_for_task(q)
    c.say("tell me a corny joke while we wait")

    a.wait_for(a.board.walk(q.id)[-1], timeout=60)

    said = [e.text for e in c.entries() if e.role == "agent"]
    assert said
    assert {t: leaks(t) for t in said if leaks(t)} == {}


def test_a_reply_is_never_stored_with_a_prefix_so_rendering_cannot_double_it():
    a = Agent(sp=SP, tools=[schedule, tail, kill])
    q = a.post("when can Jane, Jack and Joe meet?")
    task = a.wait_for_task(q)
    a.wait_for("how is that going?", parent=task.msg)

    for m in a.board.render():
        assert m["content"].count("+-- [#") <= 1


def test_the_board_never_attributes_structure_to_the_agent():
    b = Board()
    q = b.post("user", "temperature in Warsaw, MO?")
    n = b.post("assistant", "Let me look that up.", parent=q.id)
    c = b.add_call(n.id, "temperature", dict(city="Warsaw", state="MO"), actions=("tail",))
    f = b.post("user", "Do you know the answer yet?", parent=n.id)

    msgs = b.render()

    assert {m["role"] for m in msgs} == {"user"}
    assert msgs[0]["content"] == f"+-- [#{q.id}] [user] temperature in Warsaw, MO?"
    assert msgs[1]["content"].startswith(f"|   +-- [#{n.id}] [assistant] Let me look that up.")
    assert msgs[2]["content"] == (
        f"|   |   +-- [#{f.id}] [this message is in reference to task #{c.id} started earlier]"
        " [user] Do you know the answer yet?"
    )
