import threading
import time

from main.exp2.run import Stop
from main.exp3.tools import MAX_SECONDS, timed


def test_each_call_picks_its_own_completion_time_inside_the_bounds():
    t = timed("x", "d", {}, "done", due=(1.0, 4.0))
    totals = {t.fn().total for _ in range(20)}

    assert len(totals) > 1  # the due time is random per call
    assert all(1.0 <= s <= 4.0 for s in totals)


def test_nothing_is_allowed_to_run_longer_than_two_minutes():
    t = timed("x", "d", {}, "done", due=(300.0, 600.0))
    assert t.fn().total <= MAX_SECONDS


def test_progress_grows_towards_the_completion_time():
    task = timed("x", "d", {}, "done", due=(0.8, 0.8)).fn()
    threading.Thread(target=task.run, daemon=True).start()

    time.sleep(0.05)
    first = int(task.tail(1).split("%")[0])
    time.sleep(0.3)
    second = int(task.tail(1).split("%")[0])

    assert 0 <= first < second < 100
    assert task.tail(1).endswith("s to go")


def test_the_result_is_produced_when_the_timer_goes_off():
    task = timed("x", "d", {}, "done", due=(0.05, 0.05)).fn()
    assert task.run() == "done"


def test_a_stopped_call_never_produces_a_result():
    task = timed("x", "d", {}, "done", due=(5.0, 5.0)).fn()
    out = []

    def go():
        try:
            out.append(task.run())
        except Stop:
            out.append(Stop)

    t = threading.Thread(target=go, daemon=True)
    t.start()
    time.sleep(0.05)
    task.stop()
    t.join(2)

    assert out == [Stop]


def test_tool_arguments_reach_the_answer():
    quick = timed(
        "temperature",
        "d",
        dict(city=dict(type="string")),
        lambda city, state: f"72F in {city}, {state}",
        due=(0.05, 0.05),
    )
    assert quick.fn(city="Warsaw", state="MO").run() == "72F in Warsaw, MO"


def test_the_calendar_answers_for_anyone():
    from main.exp3.tools import free_hours

    assert free_hours("Jane") == "free 9-12"
    assert free_hours("Nobody In The Dict").startswith("free ")
    assert "no calendar" not in free_hours("Zaphod")


def test_the_same_person_always_gets_the_same_hours():
    from main.exp3.tools import free_hours

    assert free_hours("Paul") == free_hours(" paul ") == free_hours("PAUL")
