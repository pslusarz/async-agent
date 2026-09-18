from main.exp2.agent import Agent
from main.exp2.tools import book_room, schedule

SP = (
    "Tools run in the background. Calling a tool returns a task id, not a result. "
    "Look up every person's calendar in one response, at the same time."
)
Q = "Jane and Jack need to meet today. Find an hour they are both free, then book a room."


def called(a, q):
    return [m for m in a.board.walk(q.id) if m.calls]


def test_a_set_of_calls_is_followed_by_a_further_call_beneath_it():
    a = Agent(sp=SP, tools=[schedule, book_room])
    q = a.post(Q)
    answer = a.wait_for(q)

    nodes = called(a, q)
    assert len(nodes) == 2
    lookups, booking = nodes

    assert [c.tool for c in lookups.calls] == ["schedule", "schedule"]
    assert {c.args["person"].lower() for c in lookups.calls} == {"jane", "jack"}
    assert [c.tool for c in booking.calls] == ["book_room"]

    # the follow-up hangs off the set that motivated it, not off the question
    assert lookups.parent == q.id
    assert booking.parent == lookups.id
    assert answer.parent == booking.id
    assert not a.errors


def test_a_finished_set_wakes_the_agent_once_not_once_per_result():
    a = Agent(sp=SP, tools=[schedule, book_room])
    q = a.post(Q)
    a.wait_for(q)

    lookups = called(a, q)[0]
    assert len(lookups.calls) == 2
    assert len(lookups.children) == 1


def test_the_follow_up_sees_every_result_in_the_set():
    a = Agent(sp=SP, tools=[schedule, book_room])
    q = a.post(Q)
    a.wait_for(q)

    lookups, booking = called(a, q)
    assert all(c.terminal for c in lookups.calls)
    # jane is free 9-12 and jack from 10, so only the overlap can be booked
    assert booking.calls[0].args["start"].startswith(("10", "11"))
    assert all(a.board.answered(m.id) for m in a.board.walk(q.id))
