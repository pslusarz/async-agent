import threading
import time

from main.exp2.agent import Task
from main.exp3.tools import MAX_SECONDS, timed


class Stub:
    def __init__(self):
        self.tasks = {1: Task(1)}
        self.results = []

    def watch(self, node, tailer):
        self.tasks[node].tail = tailer

    def result(self, node, value):
        self.results.append((node, value))


def test_each_call_picks_its_own_completion_time_inside_the_bounds():
    seen = set()
    for _ in range(20):
        a = Stub()
        t = timed("x", "d", {}, "done", due=(1.0, 4.0))
        a.tasks[1].cancel.set()  # do not actually wait
        t.fn(a, 1)
        spent = a.tasks[1].tail()
        seen.add(spent)
    assert len(seen) > 1  # the due time is random per call


def test_nothing_is_allowed_to_run_longer_than_two_minutes():
    a = Stub()
    t = timed("x", "d", {}, "done", due=(300.0, 600.0))
    a.tasks[1].cancel.set()
    t.fn(a, 1)
    remaining = int(a.tasks[1].tail().split("about ")[1].split("s")[0])
    assert remaining <= MAX_SECONDS


def test_progress_grows_towards_the_completion_time():
    a = Stub()
    t = timed("x", "d", {}, "done", due=(0.8, 0.8))
    threading.Thread(target=t.fn, args=(a, 1), daemon=True).start()

    time.sleep(0.05)
    first = int(a.tasks[1].tail().split("%")[0])
    time.sleep(0.3)
    second = int(a.tasks[1].tail().split("%")[0])

    assert 0 <= first < second < 100
    assert a.tasks[1].tail().endswith("s to go")


def test_the_result_is_produced_when_the_timer_goes_off():
    a = Stub()
    t = timed("x", "d", {}, "done", due=(0.05, 0.05))
    t.fn(a, 1)
    assert a.results == [(1, "done")]


def test_a_killed_call_never_produces_a_result():
    a = Stub()
    t = timed("x", "d", {}, "done", due=(5.0, 5.0))
    threading.Thread(target=t.fn, args=(a, 1), daemon=True).start()
    time.sleep(0.05)
    a.tasks[1].cancel.set()
    time.sleep(0.1)
    assert a.results == []


def test_tool_arguments_reach_the_answer():
    a = Stub()
    quick = timed("temperature", "d", dict(city=dict(type="string")),
                  lambda city, state: f"72F in {city}, {state}", due=(0.05, 0.05))
    quick.fn(a, 1, city="Warsaw", state="MO")
    assert a.results == [(1, "72F in Warsaw, MO")]


def test_the_calendar_answers_for_anyone():
    from main.exp3.tools import free_hours

    assert free_hours("Jane") == "free 9-12"
    assert free_hours("Nobody In The Dict").startswith("free ")
    assert "no calendar" not in free_hours("Zaphod")


def test_the_same_person_always_gets_the_same_hours():
    from main.exp3.tools import free_hours

    assert free_hours("Paul") == free_hours(" paul ") == free_hours("PAUL")
