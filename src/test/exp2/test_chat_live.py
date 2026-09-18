import time

from main.exp2.agent import Agent
from main.exp2.chat import Chat
from main.exp2.tools import timer

SP = "Tools run in the background. Calling a tool returns a task id, not a result."


def until(cond, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def agent_said(c, needle):
    return any(needle in e.text for e in c.entries() if e.role == "agent")


def test_a_message_appears_when_the_tool_finishes():
    a = Agent(
        sp=SP,
        tools=[timer("build_time", "How long the build takes.", "12 minutes", 2.0)],
    )
    c = Chat(a)
    c.say("how long will the build take?")

    assert until(lambda: any(e.role == "agent" for e in c.entries()))
    before = len(c.entries())

    # nobody types anything; the agent speaks once the timer goes off
    assert until(lambda: agent_said(c, "12 minutes"))
    assert len(c.entries()) > before
    assert c.entries()[-1].role == "agent"
    assert not a.errors


def test_a_late_answer_says_which_question_it_belongs_to():
    a = Agent(
        sp=SP,
        tools=[timer("build_time", "How long the build takes.", "12 minutes", 8.0)],
    )
    c = Chat(a)
    c.say("how long will the build take?")
    assert until(lambda: any(e.role == "agent" for e in c.entries()))

    c.say("meanwhile, what is 2+2?")
    assert until(lambda: agent_said(c, "4"))

    assert until(lambda: agent_said(c, "12 minutes"))
    last = c.entries()[-1]
    assert last.role == "agent"
    assert last.text.startswith("Regarding your earlier question")
    assert "how long will the build take?" in last.text


def test_the_user_can_ask_how_it_is_going_while_it_runs():
    from main.exp2.tools import tail

    a = Agent(
        sp=SP,
        tools=[
            timer("build_time", "How long the build takes.", "12 minutes", 8.0),
            tail,
        ],
    )
    c = Chat(a)
    c.say("how long will the build take?")
    assert until(lambda: any(e.role == "agent" for e in c.entries()))

    before = len(c.entries())
    c.say("how is that coming along?")

    # the tool was actually probed, and the agent answered in its own words
    probed = lambda: [
        p for m in a.board.msgs.values() for p in m.calls if p.tool == "tail"
    ]
    assert until(lambda: any(p.result for p in probed()))
    assert "still running" in probed()[0].result
    assert until(lambda: len(c.entries()) > before + 1)
    assert not any("task #" in e.text.lower() for e in c.entries())
