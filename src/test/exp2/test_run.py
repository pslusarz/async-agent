import threading
import time

from main.exp2.agent import Agent
from main.exp2.run import IDLE, Runner, Stop, Work
from main.exp2.tools import TEMPERATURE, Tool

SP = "Tools run in the background. Calling a tool returns a task id, not a result."
Q = "What is the temperature in Warsaw, MO?"


def until(cond, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class Returns(Work):
    def run(self) -> str:
        return "value"


class Raises(Work):
    def run(self) -> str:
        raise RuntimeError("server exploded")


class Forever(Work):
    def __init__(self):
        super().__init__()
        self.started = threading.Event()

    def run(self) -> str:
        self.started.set()
        while True:
            self.beat(0.02)


def test_a_returned_value_settles_the_task_and_notifies_once():
    seen = []
    r = Runner(7, Returns(), seen.append)
    r.start()

    assert r.future.result(5) == "value"
    assert until(lambda: seen == [r])
    assert r.done


def test_a_raised_exception_settles_as_a_result_instead_of_hanging():
    r = Runner(1, Raises(), lambda _: None)
    r.start()
    out = r.future.result(5)

    assert out.startswith("failed:")
    assert "server exploded" in out


def test_a_stopped_task_settles_rather_than_running_on():
    task = Forever()
    r = Runner(1, task, lambda _: None)
    r.start()
    assert task.started.wait(5)

    r.kill()

    assert r.killed
    assert r.future.result(5).startswith("stopped before finishing")


def test_stop_is_delivered_at_the_next_beat():
    task = Forever()
    out = []

    def go():
        try:
            task.run()
        except Stop:
            out.append("stopped")

    t = threading.Thread(target=go, daemon=True)
    t.start()
    task.stop()
    t.join(2)

    assert out == ["stopped"]


def test_tail_shows_the_status_and_only_the_lines_asked_for():
    w = Work()
    assert w.tail(5) == IDLE

    w.status = "working"
    for i in range(4):
        w.log(f"line {i}")

    assert w.tail(0) == "working"
    assert w.tail(2) == "working\nline 2\nline 3"
    assert w.tail(99).count("\n") == 4


def test_the_log_is_bounded_so_a_chatty_task_cannot_grow_forever():
    w = Work(keep=3)
    for i in range(10):
        w.log(f"line {i}")

    assert w.tail(99) == "line 7\nline 8\nline 9"


def test_a_failing_tool_reaches_the_board_as_a_result():
    a = Agent(
        sp=SP, tools=[Tool(TEMPERATURE, lambda city, state: Raises())], max_auto=1
    )
    q = a.post(Q)
    task = a.wait_for_task(q)

    assert until(lambda: a.board.calls[task.id].result is not None, timeout=15)
    assert "server exploded" in a.board.calls[task.id].result
    assert a.board.calls[task.id].terminal
