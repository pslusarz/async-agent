import pytest

from main.exp6.watch import Watched

# the timer is wall-clock, so a replay fires it at a different point in the sequence
pytestmark = [pytest.mark.live, pytest.mark.realtime]

ZED = "Use the calendar agent to look up Zed's schedule."
JOE = "Use the calendar agent to look up Joe's schedule."


async def test_the_harness_times_out_a_stuck_task_and_the_agent_stops_it():
    async with Watched(after=20.0) as s:
        await s.say(ZED)
        assert await s.until(lambda e: any(x.kind == "TaskStarted" for x in e), timeout=60)

        stopped = await s.until(
            lambda e: any(x.kind == "call" and x.name == "TaskStop" for x in e),
            timeout=180,
        )

        assert stopped, "the agent never called TaskStop"
        assert s.nudged, "no task was ever timed out"
        # the only thing a person typed was the opening question
        typed = [x for x in s.events if x.kind == "user"]
        assert len(typed) == 1 + sum(s.nudged.values())


async def test_the_harness_can_read_the_progress_the_agent_may_not():
    async with Watched(after=20.0) as s:
        await s.say(ZED)
        assert await s.until(lambda e: any(x.kind == "result" for x in e), timeout=60)

        task = s.of("TaskStarted")[0].task
        assert s.outfile(task) is not None
        assert await s.until(lambda e: any(x.kind == "user" and "automatic notice" in x.text for x in e), timeout=90)

        notice = next(x for x in s.events if x.kind == "user" and "automatic notice" in x.text)
        assert "lookup_calendar" in notice.text


async def test_a_task_that_finishes_in_time_is_never_timed_out():
    async with Watched(after=90.0) as s:
        await s.say(JOE)

        assert await s.until(lambda e: any(x.kind == "TaskNotification" for x in e), timeout=120)
        assert not s.nudged
        assert not s.timers
