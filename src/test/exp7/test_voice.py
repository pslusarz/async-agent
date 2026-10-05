import pytest

from main.exp2.board import Board
from main.exp2.tools import Tool
from main.exp5.agent import speaks
from main.exp5.tools import finishing_temperature, kill, tail
from main.exp7.agent import Agent
from main.exp7.chat import Chat

Q = "What is the temperature in Warsaw, MO?"


class Stub:
    """An agent that never calls a model: the board is written by the test."""

    def __init__(self):
        self.board = Board()
        self.tools = {
            "temperature": Tool(dict(name="temperature"), None),
            "tail": Tool(dict(name="tail"), None, meta=True),
        }
        self.listener = None
        self.on_change = None

    def post(self, text, parent=None):
        return self.board.post("user", text, parent=parent)


def spoken(c):
    return [e.text for e in c.entries() if e.text]


def start(c, a, parent, aside=False, **args):
    node = a.board.post("assistant", "", parent=parent, aside=aside)
    call = a.board.add_call(node.id, "temperature", args)
    c._on_call("started", call)
    return node, call


@pytest.mark.parametrize(
    "trigger,did,said",
    [
        ("user", "look", False),
        ("user", "work", True),
        ("user", "word", True),
        ("result", "look", False),
        ("result", "work", False),
        ("result", "word", True),
        ("overdue", "look", False),
        ("overdue", "work", False),
        ("overdue", "word", False),
    ],
)
def test_who_the_agent_is_talking_to(trigger, did, said):
    assert speaks(trigger, did) is said


def test_a_look_the_timer_asked_for_stays_off_the_transcript():
    a = Stub()
    c = Chat(a)
    c.say(Q)
    q = a.board.msgs[1]
    a.board.post("assistant", "Let me check on that!", parent=q.id, aside=True)
    a.board.post("assistant", "It is 70% done.", parent=q.id, aside=True)

    assert spoken(c) == [Q]


def test_a_look_the_user_asked_for_is_answered_once_not_twice():
    a = Stub()
    c = Chat(a)
    c.say(Q)
    q = a.board.msgs[1]
    peek = a.board.post("assistant", "Let me take a peek!", parent=q.id, aside=True)
    a.board.add_call(peek.id, "tail", dict(task=1))
    a.board.post("assistant", "It is 70% done.", parent=peek.id)

    assert spoken(c) == [Q, "It is 70% done."]


def test_a_restart_says_nothing_but_still_shows_its_task():
    a = Stub()
    c = Chat(a)
    c.say(Q)
    q = a.board.msgs[1]
    node, _ = start(c, a, q.id, aside=True, city="Warsaw")

    assert spoken(c) == [Q]
    assert [w.tool for w in c.calls(node.id)] == ["temperature"]
    assert node.id in [e.id for e in c.entries()]


def test_an_answer_to_a_result_is_spoken():
    a = Stub()
    c = Chat(a)
    c.say(Q)
    q = a.board.msgs[1]
    node, call = start(c, a, q.id, city="Warsaw")
    a.board.set_result(call.id, "72F")
    c._on_call("settled", call)
    a.board.post("assistant", "It is 72F in Warsaw.", parent=node.id)

    assert spoken(c) == [Q, "It is 72F in Warsaw."]
    assert [w.state for w in c.calls(node.id)] == ["done"]


def test_giving_up_reaches_the_reader_even_though_the_timer_asked():
    a = Stub()
    c = Chat(a)
    c.say(Q)
    q = a.board.msgs[1]
    a.board.post("assistant", "Let me kill that.", parent=q.id, aside=True)
    a.board.post("assistant", "The lookup keeps failing. How shall we proceed?")

    assert spoken(c) == [Q, "The lookup keeps failing. How shall we proceed?"]


def test_a_nudged_turn_is_on_the_board_but_not_in_the_transcript():
    a = Agent(
        sp="Tools run in the background. Calling one returns a task id, not a result.",
        tools=[finishing_temperature, tail, kill],
        timeout_cap=1.0,
    )
    c = Chat(a)
    c.say(Q)
    q = a.board.msgs[1]
    a.wait_for(q, timeout=120)

    looked = [m for m in a.board.msgs.values() if any(x.tool == "tail" for x in m.calls)]
    assert looked, "the timer never nudged"
    assert all(m.aside and m.text for m in looked)
    assert not {m.id for m in looked} & {e.id for e in c.entries()}
    assert spoken(c)[-1] != looked[-1].text
    a.stop()
