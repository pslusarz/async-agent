from main.exp2.agent import Agent
from main.exp2.tools import temperature

SP = "Tools run in the background. Calling a tool returns a task id, not a result."
Q = "What is the temperature in Warsaw, MO and in Springfield, IL? Check both."


def calls_of(a, q):
    return [c for m in a.board.walk(q.id) for c in m.calls]


def test_two_calls_in_one_response_share_one_node_and_both_results_survive():
    a = Agent(sp=SP, tools=[temperature])
    q = a.post(Q)
    answer = a.wait_for(q)

    made = calls_of(a, q)
    assert len(made) == 2
    assert {c.args["city"] for c in made} == {"Warsaw", "Springfield"}
    assert all(c.result == "72" for c in made)

    # both placeholders hang off the same assistant turn
    assert made[0].msg == made[1].msg
    assert a.board[made[0].msg].parent == q.id
    assert answer.parent == made[0].msg
    assert not a.errors


def test_the_agent_waits_for_every_placeholder_before_answering():
    a = Agent(sp=SP, tools=[temperature])
    q = a.post(Q)
    task = a.wait_for_task(q)
    node = a.board[task.msg]

    assert not a.board.answered(q.id)

    a.wait_for(q)
    assert node.terminal
    assert all(c.terminal for c in node.calls)
    assert a.board.answered(q.id)


def test_interim_text_is_kept_alongside_the_calls():
    a = Agent(sp=SP, tools=[temperature])
    q = a.post(Q)
    a.wait_for(q)

    node = a.board[calls_of(a, q)[0].msg]
    assert node.text
    assert node.display.startswith(node.text)
