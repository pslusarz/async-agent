import pytest

from main.exp4.loop import Session
from main.exp4.tools import NEEDS_FULL_STATE

pytestmark = pytest.mark.live

WARSAW = "Use the weather agent for the temperature in Warsaw, MO."
FUSSY = "Use the strict-weather agent for the temperature in Warsaw, MO."


def unprompted(events):
    return [
        e
        for e in events
        if e.kind == "turn" and (e.origin or {}).get("kind") == "task-notification"
    ]


def calls_to(session, tool):
    return [e for e in session.of("call") if e.name.endswith(tool)]


async def test_an_instant_tool_still_goes_through_the_background_path():
    """Nothing here short-circuits for a tool that answers at once.

    exp2 settles a fast call on the spot; the launch, the notification and the
    unprompted turn all happen here even though the tool never waits.
    """
    async with Session() as s:
        await s.say(WARSAW)

        assert await s.until(lambda e: unprompted(e), timeout=120)

        assert s.of("TaskStarted")
        assert s.of("TaskNotification")
        assert any("72" in x.text for x in s.said())


async def test_a_tool_error_is_corrected_inside_the_subagent():
    """The parent delegates once and never learns the first call was wrong.

    exp2 retries in the main thread, so both attempts sit in the transcript the
    agent answers from. Here the subagent owns the correction in its own
    context, and only the final answer is handed back.
    """
    async with Session() as s:
        await s.say(FUSSY)

        assert await s.until(lambda e: unprompted(e), timeout=150)

        tried = calls_to(s, "strict_temperature")
        assert len(tried) >= 2, "the subagent never retried"
        assert tried[0].args["state"] == "MO"
        assert len(tried[1].args["state"]) > 2

        spoken = " ".join(x.text for x in s.said())
        assert "72" in spoken
        assert NEEDS_FULL_STATE not in spoken
