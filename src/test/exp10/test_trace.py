"""The play-by-play the debugger shows: every stored entry, queued event and model call."""

from starlette.testclient import TestClient

from main.exp10.agent import NOTICE, Agent
from main.exp10.app import frames, make_app
from main.exp10.tools import kill, tail
from main.exp10.trace import Trace

from .conftest import Script, say, use

COLUMBIA = dict(city="Columbia", state="MO", timeout=10)


def traced(script, tools=()):
    t = Trace()
    a = t.attach(Agent(tools=list(tools), client=t.client(script)))
    return t, a


def kinds(t):
    return [s.kind for s in t.steps]


def test_a_plain_turn_is_a_stored_entry_a_request_a_response_and_a_reply():
    t, a = traced(Script(say("Hello!")))
    a.wait_for("hi")
    a.stop()
    assert kinds(t) == ["entry", "event", "request", "response", "entry"]
    assert "hi" in t.steps[0].body
    assert "Hello!" in t.steps[-1].body


def test_a_background_call_shows_its_start_result_and_report(gates):
    tool, open_ = gates
    s = Script(use("temperature", **COLUMBIA), say("Checking."), say("It is 81."))
    t, a = traced(s, [tool, tail, kill])
    q = a.post("What is the temperature in Columbia, MO?")
    assert a.wait_until(lambda: a.answer_of(q.id) is not None, 5), a.errors
    open_("Columbia")
    assert "81" in a.wait_for(q, timeout=5).text
    a.stop()
    titles = [s.title for s in t.steps]
    assert any("result #1" in x for x in titles)
    assert any("batch" in x for x in titles)
    assert any("note" in x for x in titles)
    assert any("tool_results" in x for x in titles)


def test_a_request_marks_the_running_notice_as_never_stored(gates):
    tool, open_ = gates
    s = Script(use("temperature", **COLUMBIA), say("Checking."), say("Fine."), say("81."))
    t, a = traced(s, [tool, tail, kill])
    q = a.post("What is the temperature in Columbia, MO?")
    assert a.wait_until(lambda: a.answer_of(q.id) is not None, 5), a.errors
    a.wait_for("how is it going?", timeout=5)
    open_("Columbia")
    a.wait_for(q, timeout=5)
    a.stop()
    requests = [s for s in t.steps if s.kind == "request"]
    assert "not stored" in requests[2].title
    assert NOTICE in requests[2].body
    # only what is new since the previous request is shown: the question is not
    assert "5 messages, 3 new" in requests[2].title


def test_a_failed_model_call_is_recorded():
    t, a = traced(Script())
    a.post("hi")
    assert a.wait_until(lambda: a.errors, 5)
    a.stop()
    assert t.steps[-1].kind == "error"


def test_the_page_shows_the_chat_and_the_debugger():
    t, a = traced(Script(say("Hello!")))
    c = TestClient(make_app(a, t))
    assert c.post("/say", data=dict(msg="hi")).status_code == 200
    a.wait_until(lambda: a.answered(1), 5)
    page = c.get("/").text
    a.stop()
    assert "Hello!" in page
    assert 'id="timeline"' in page and 'id="state"' in page


def test_the_steps_that_are_said_out_loud_carry_who_said_what():
    t, a = traced(Script(say("Hello!")))
    a.wait_for("hi")
    a.stop()
    assert [s.said for s in t.steps if s.said] == [("user", "hi"), ("agent", "Hello!")]


def test_the_stream_sends_each_step_once_with_its_id_then_the_state():
    t, a = traced(Script(say("Hello!")))
    a.wait_for("hi")
    a.stop()
    sent = frames(a, t, 0, len(t.steps))
    steps = [f for f in sent if f.startswith("id: ")]
    assert [f.split("\n")[0] for f in steps] == [f"id: {n}" for n in range(1, 6)]
    assert sum("event: said" in f for f in sent) == 2
    assert "event: state" in sent[-1]
    assert 'name="msg"' not in "".join(sent)
    # a reconnect after step 4 is sent step 5 and nothing before it
    again = frames(a, t, 4, len(t.steps))
    assert [f.split("\n")[0] for f in again if f.startswith("id: ")] == ["id: 5"]
