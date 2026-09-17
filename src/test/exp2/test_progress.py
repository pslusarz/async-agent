from main.exp2.agent import TOOL_PENDING, Agent
from main.exp2.tools import FINISHED, slow_temperature, tail, temperature

SP = (
    "Tools run in the background. Calling a tool returns a task id, not a result. "
    "When the user asks whether an answer is ready, call tail with that task id and "
    "report exactly what it says. Never start a second task for a question that "
    "already has one running."
)


def probes(a, node):
    return [
        m.text.split(": ", 1)[1]
        for m in a.board.walk(node.id)
        if m.text.startswith("Progress for")
    ]


def test_user_polls_progress_then_the_task_finishes():
    a = Agent(sp=SP, tools=[slow_temperature, tail])
    node = a.post("What is the temperature in Warsaw, MO?")

    assert node.text == TOOL_PENDING
    assert node.tool == "temperature"

    r1 = a.post("Do you know the answer yet?", parent=node.id)
    r2 = a.post("Do you know the answer yet?", parent=node.id)
    r3 = a.post("Do you know the answer yet?", parent=node.id)

    assert probes(a, node)[:3] == ["30% complete", "60% complete", "90% complete"]
    assert "30" in r1.text
    assert "60" in r2.text
    assert "90" in r3.text

    done = a.wait_for(node)
    assert done.result == "72"


def test_progress_is_recorded_in_the_thread_under_the_question_that_asked():
    a = Agent(sp=SP, tools=[slow_temperature, tail])
    node = a.post("What is the temperature in Warsaw, MO?")
    r1 = a.post("Do you know the answer yet?", parent=node.id)

    probe = next(m for m in a.board.walk(node.id) if m.text.startswith("Progress for"))
    assert a.board[probe.parent].text == "Do you know the answer yet?"
    assert a.board.root_of(probe.id) == a.board.root_of(node.id)

    nodes = a.board.walk(node.id)
    assert [m.role for m in nodes] == ["assistant", "user", "user", "assistant"]
    assert nodes[0].text == TOOL_PENDING
    assert nodes[1].text == "Do you know the answer yet?"
    assert nodes[2].text.startswith("Progress for task")
    assert nodes[3].id == r1.id


def test_tail_reports_a_finished_task():
    a = Agent(sp=SP, tools=[temperature, tail])
    node = a.post("What is the temperature in Warsaw, MO?")
    a.wait_for(node)

    tail.fn(a, node.id, task=node.id)

    assert probes(a, node)[-1] == FINISHED
    assert a.board[node.id].result == "72"
