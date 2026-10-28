"""The harness against a scripted model: what it shows, keeps, reports and refuses."""

import json
import threading

from main.exp2.tools import BOOK_ROOM, TEMPERATURE, Answer, Tool
from main.exp2.tools import temperature as instant
from main.exp5.tools import STUCK
from main.exp10.agent import NOTICE, Agent, Call
from main.exp10.tools import kill, stuck_temperature, tail

from .conftest import Script, last_text, say, use

Q = "What is the weather like in Columbia, MO and Washington, DC?"
COLUMBIA = dict(city="Columbia", state="MO", timeout=10)
WASHINGTON = dict(city="Washington", state="DC", timeout=10)


def both(text: str = ""):
    return use("temperature", text, **COLUMBIA) + use("temperature", **WASHINGTON)


def notes(a):
    return [e.text for e in a.log if e.kind == "note"]


def results(a):
    return [
        b["content"] for e in a.log if e.kind == "tool_results" for b in e.content
    ]


def stored(a) -> str:
    return json.dumps([e.content for e in a.log])


def test_a_plain_question_is_answered_without_tools():
    s = Script(say("Hello!"))
    a = Agent(client=s)
    assert a.wait_for("hi").text == "Hello!"
    assert len(s.requests) == 1
    assert NOTICE not in json.dumps(s.requests[0]["messages"])
    a.stop()


def test_the_running_list_is_shown_before_a_turn_and_never_kept(gates):
    tool, open_ = gates
    s = Script(
        both(),
        say("Let me check... hang tight."),
        say("Why did the chicken cross the road?"),
        say("Columbia is 81 and Washington is 64."),
    )
    a = Agent(tools=[tool, tail, kill], client=s)
    q = a.post(Q)
    assert a.wait_until(lambda: a.answer_of(q.id) is not None, 5), a.errors
    assert not a.answered(q.id)

    joke = a.wait_for("tell me a joke while we wait", timeout=5)
    assert "chicken" in joke.text

    shown = last_text(s.requests[2])
    assert shown.startswith(NOTICE)
    assert "task #1 temperature(city='Columbia', state='MO'): still running" in shown
    assert "task #2 temperature(city='Washington', state='DC'): still running" in shown
    assert Q in shown
    assert "still running" not in stored(a)

    open_("Columbia")
    open_("Washington")
    answer = a.wait_for(q, timeout=5)
    assert "81" in answer.text
    # nothing is running any more, so the turn that reports it sees no list
    assert "still running" not in json.dumps(s.requests[3]["messages"])
    assert [who for who, _ in a.transcript()] == ["user", "agent", "user", "agent", "agent"]
    a.stop()


def test_a_batch_wakes_the_agent_once_and_shows_partial_results_meanwhile(gates):
    tool, open_ = gates
    s = Script(both(), say("Checking both."))
    a = Agent(tools=[tool, tail, kill], client=s)
    q = a.post(Q)
    open_("Columbia")
    assert a.wait_until(lambda: 1 in a.calls and a.calls[1].result == "81", 5), a.errors
    assert a.wait_until(lambda: len(s.requests) == 2, 5)

    s.then(say("Columbia is 81; still waiting on Washington."))
    a.wait_for("how is it going?", timeout=5)
    shown = last_text(s.requests[2])
    assert "task #1 temperature(city='Columbia', state='MO'): returned: 81" in shown
    assert "task #2 temperature(city='Washington', state='DC'): still running" in shown
    assert not notes(a), "one result of two must not wake the agent"

    s.then(say("Columbia is 81 and Washington is 64."))
    open_("Washington")
    a.wait_for(q, timeout=5)
    (report,) = notes(a)
    assert "returned: 81" in report and "returned: 64" in report
    a.stop()


def test_a_report_quotes_the_question_only_once_the_conversation_moved_on(gates):
    tool, open_ = gates
    s = Script(use("temperature", **COLUMBIA), say("Checking."), say("It is 81."))
    a = Agent(tools=[tool], client=s)
    q = a.post("What is the temperature in Columbia, MO?")
    assert a.wait_until(lambda: len(s.requests) == 2, 5)
    open_("Columbia")
    a.wait_for(q, timeout=5)
    (report,) = notes(a)
    assert "earlier message" not in report
    a.stop()

    s = Script(
        use("temperature", **COLUMBIA), say("Checking."), say("Sure."), say("It is 81.")
    )
    a = Agent(tools=[tool], client=s)
    q = a.post("What is the temperature in Columbia, MO?")
    a.wait_for("unrelated: what is 2+2?", timeout=5)
    open_("Columbia")
    a.wait_for(q, timeout=5)
    (report,) = notes(a)
    assert "earlier message 'What is the temperature in Columbia, MO?'" in report
    a.stop()


def test_a_call_already_running_is_refused_and_the_way_out_is_named(gates):
    tool, open_ = gates
    s = Script(
        use("temperature", **COLUMBIA),
        say("Checking."),
        use("temperature", **COLUMBIA),
        say("That is already under way."),
    )
    a = Agent(tools=[tool, tail, kill], client=s)
    q = a.post("What is the temperature in Columbia, MO?")
    again = a.wait_for("And what about Columbia, MO?", timeout=5)
    assert again.text == "That is already under way."

    refused = results(a)[-1]
    assert refused.startswith("error: not started")
    assert "already running as task #1" in refused and "kill(task=1)" in refused
    assert list(a.tasks) == [1]
    # the edge case is explained when it happens, not up front in every request
    up_front = json.dumps(s.requests[0]["tools"]) + s.requests[0]["system"]
    assert "already running" not in up_front

    s.then(say("It is 81."), use("temperature", **COLUMBIA), say("Checking again."))
    open_("Columbia")
    a.wait_for(q, timeout=5)
    # once it has returned, the same call is a fresh one
    a.post("Check Columbia once more?")
    assert a.wait_until(lambda: 2 in a.tasks, 5), a.errors
    a.stop()


def test_the_user_stops_one_call_and_keeps_the_other_result(gates):
    tool, open_ = gates
    s = Script(both(), say("Checking both."))
    a = Agent(tools=[tool, tail, kill], client=s)
    q = a.post(Q)
    open_("Columbia")
    assert a.wait_until(lambda: 1 in a.calls and a.calls[1].result == "81", 5)
    assert a.wait_until(lambda: len(s.requests) == 2, 5)

    s.then(use("kill", task=2), say("Stopped Washington."), say("Columbia is 81."))
    a.wait_for("never mind Washington, Columbia is enough", timeout=5)
    answer = a.wait_for(q, timeout=5)
    assert answer.text == "Columbia is 81."
    (report,) = notes(a)
    assert "returned: 81" in report and "was killed before it returned" in report
    a.stop()


def test_a_batch_that_was_all_killed_is_not_reported():
    s = Script(
        use("temperature", **COLUMBIA),
        say("Checking."),
        use("kill", task=1),
        say("Stopped it."),
    )
    a = Agent(tools=[stuck_temperature, tail, kill], client=s)
    q = a.post("What is the temperature in Columbia, MO?")
    a.wait_for("stop that", timeout=5)
    assert a.wait_until(lambda: a.answered(q.id), 5)
    assert not notes(a) and len(s.requests) == 4
    a.stop()


def test_an_overdue_task_is_looked_at_and_killed_without_telling_the_reader():
    s = Script(
        use("temperature", **(COLUMBIA | dict(timeout=0.1))),
        say("Checking."),
        use("tail", task=1),
        use("kill", task=1),
        say("It was stuck, so I stopped it."),
    )
    a = Agent(tools=[stuck_temperature, tail, kill], client=s, timeout_cap=0.2)
    a.post("What is the temperature in Columbia, MO?")
    assert a.wait_until(lambda: len(s.requests) == 5 and len(a.log) >= 9, 5), a.errors

    (nudge,) = notes(a)
    assert "has not finished within the 0.1s" in nudge
    assert STUCK in results(a)[1]
    assert results(a)[2] == "killed"
    assert a.calls[1].killed and not a.timers
    assert "It was stuck, so I stopped it." not in [t for _, t in a.transcript()]
    a.stop()


def test_giving_up_reaches_the_reader_although_the_timer_asked():
    giving_up = "The weather service keeps failing. How would you like to proceed?"
    s = Script(
        use("temperature", **(COLUMBIA | dict(timeout=0.1))),
        say("Checking."),
        use("kill", task=1),
        say(giving_up),
    )
    a = Agent(tools=[stuck_temperature, tail, kill], client=s, timeout_cap=0.2, max_retries=0)
    a.post("What is the temperature in Columbia, MO?")
    assert a.wait_until(lambda: len(s.requests) == 4 and len(a.log) >= 8, 5), a.errors
    assert "keeps failing" in results(a)[1]
    assert ("agent", giving_up) in a.transcript()
    a.stop()


def test_retries_are_counted_per_call_so_side_by_side_calls_do_not_share_them():
    a = Agent(client=Script())
    for cid, city in enumerate(["Columbia", "Washington", "Columbia"], 1):
        a.calls[cid] = Call(cid, "temperature", dict(city=city), 1, 1, killed=True)
    a.calls[4] = Call(4, "temperature", dict(city="Columbia"), 9, 9, killed=True)
    assert [a._attempts(c) for c in (1, 2, 4)] == [2, 1, 1]
    a.stop()


def test_a_chained_call_serves_the_question_that_started_the_chain():
    book = Tool(BOOK_ROOM, lambda start: Answer(f"room 3B is booked at {start}"))
    s = Script(
        use("temperature", city="Columbia", state="MO", timeout=5),
        say("Checking."),
        use("book_room", start="10:00", timeout=5),
        say("Nice out, booking the terrace room."),
        say("Booked 3B at 10:00."),
    )
    a = Agent(tools=[instant, book], client=s)
    q = a.post("If it is warm in Columbia, book a room at ten")
    assert a.wait_for(q, timeout=5).text == "Booked 3B at 10:00."
    assert a.calls[2].question == q.id
    assert len(notes(a)) == 2
    a.stop()


def test_a_chain_that_never_ends_is_capped():
    loop = [use("temperature", city="Columbia", state="MO", timeout=5), say("Again.")]
    s = Script(*loop * 3)
    a = Agent(tools=[instant], client=s, max_auto=2)
    q = a.post("Keep checking Columbia")
    assert a.wait_until(lambda: a.answered(q.id) and len(s.requests) == 6, 5), a.errors
    assert len(notes(a)) == 2 and not s.replies
    a.stop()


def test_a_look_and_a_new_call_can_share_one_breath():
    s = Script(
        use("tail", task=99) + use("temperature", city="Columbia", state="MO", timeout=5),
        say("Checking."),
        say("It is 72."),
    )
    a = Agent(tools=[instant, tail, kill], client=s)
    q = a.post("Columbia?")
    a.wait_for(q, timeout=5)
    looked, began = results(a)[:2]
    assert looked == "no such task #99"
    assert began.startswith("started in the background as task #1")
    a.stop()


def test_a_message_sent_while_a_call_starts_comes_after_its_result():
    entered, go = threading.Event(), threading.Event()

    def slow_start(city, state):
        entered.set()
        go.wait(5)
        return Answer("81")

    s = Script(
        use("temperature", **COLUMBIA),
        say("Checking."),
        say("It is already under way."),
        say("Columbia is 81."),
    )
    a = Agent(tools=[Tool(TEMPERATURE, slow_start)], client=s)
    q = a.post("What is the temperature in Columbia, MO?")
    assert entered.wait(5)
    late = threading.Thread(target=a.post, args=("Could you look up Columbia, MO?",))
    late.start()
    late.join(0.2)
    go.set()
    late.join(5)
    assert a.wait_until(lambda: len(s.requests) == 4 and a.answered(q.id), 5), a.errors
    assert a.errors == []
    a.stop()
