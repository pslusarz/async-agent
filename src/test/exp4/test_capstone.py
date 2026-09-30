import pytest

from main.exp4.loop import Session

pytestmark = pytest.mark.live

MEETING = "When can Jane, Jack and Joe meet? Check all three calendars."


def unprompted(events):
    """Turns nobody asked for, driven by a task finishing."""
    return [
        e
        for e in events
        if e.kind == "turn" and (e.origin or {}).get("kind") == "task-notification"
    ]


async def test_three_calendars_run_at_once():
    async with Session() as s:
        await s.say(MEETING)

        assert await s.until(
            lambda e: len([x for x in e if x.kind == "TaskStarted"]) == 3, timeout=60
        )

        started = s.of("TaskStarted")
        first_turn = s.of("turn")[0] if s.of("turn") else None
        assert len({t.task for t in started}) == 3
        # all three go out before the turn that launched them ends
        assert first_turn is None or started[-1].at < first_turn.at


async def test_the_answer_arrives_in_pieces_rather_than_once():
    """exp2 holds a node until every call in it lands, so a three-calendar
    question is answered once. Here each outcome gets its own unprompted turn,
    so the user is told about thirds of the answer as they arrive.
    """
    async with Session() as s:
        await s.say(MEETING)

        assert await s.until(
            lambda e: len([x for x in e if x.kind == "TaskNotification"]) == 3, timeout=150
        )
        assert await s.until(
            lambda e: unprompted(e)
            and unprompted(e)[-1].at > [x for x in e if x.kind == "TaskNotification"][-1].at,
            timeout=60,
        )

        done = s.of("TaskNotification")
        spoken = unprompted(s.events)

        assert len(spoken) > 1, "the agent consolidated, which exp2 does but this should not"
        partial = [t for t in spoken if t.at < done[-1].at]
        assert partial, "nothing was said before the last calendar landed"
