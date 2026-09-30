import pytest

from main.exp4.loop import Session

pytestmark = pytest.mark.live

JOE = "Use the calendar agent to look up Joe's schedule."
ZED = "Use the calendar agent to look up Zed's schedule."


async def test_a_plain_question_needs_no_subagent():
    async with Session() as s:
        await s.say("What is 2+2? Answer with the number only.")

        assert await s.until(lambda e: any(x.kind == "turn" for x in e), timeout=60)
        assert "4" in s.said()[0].text
        assert not s.of("call")


async def test_a_background_subagent_ends_the_turn_at_once():
    async with Session() as s:
        await s.say(JOE)

        assert await s.until(lambda e: any(x.kind == "turn" for x in e), timeout=60)

        started = s.of("TaskStarted")
        turn = s.of("turn")[0]
        assert started, "no background task was started"
        assert started[0].at < turn.at, "task must start before the turn ends"
        # the calendar tool sleeps 20s; the turn must not have waited for it
        assert turn.at < 15, f"turn took {turn.at:.1f}s, so it blocked on the task"


async def test_the_launch_leaves_a_placeholder_the_agent_can_act_on():
    async with Session() as s:
        await s.say(JOE)

        assert await s.until(lambda e: any(x.kind == "result" for x in e), timeout=60)

        placeholder = s.of("result")[0]
        assert "agentId" in placeholder.text
        assert s.of("TaskStarted")[0].task in placeholder.text


async def test_the_user_is_answered_while_the_task_runs():
    async with Session() as s:
        await s.say(JOE)
        assert await s.until(lambda e: any(x.kind == "TaskStarted" for x in e), timeout=60)

        await s.say("Meanwhile: what is 2+2? Answer with the number only.")
        answered = await s.until(
            lambda e: any(x.kind == "said" and x.parent is None and "4" in x.text for x in e),
            timeout=60,
        )

        assert answered, "the interjected question was never answered"
        reply = next(x for x in s.said() if "4" in x.text)
        landed = s.of("TaskNotification")
        assert not landed or reply.at < landed[0].at


async def test_a_finished_task_comes_back_as_an_unprompted_turn():
    async with Session() as s:
        await s.say(JOE)

        def arrived(events):
            return any(
                x.kind == "turn" and (x.origin or {}).get("kind") == "task-notification"
                for x in events
            )

        assert await s.until(arrived, timeout=120)

        # nobody typed anything after the opening question
        assert len([x for x in s.events if x.kind == "user"]) == 1
        late = [x for x in s.of("turn") if (x.origin or {}).get("kind") == "task-notification"]
        assert s.of("TaskNotification")[0].at <= late[0].at


async def test_progress_cannot_be_inspected_while_the_task_runs():
    """Claude Code hands over the output file and then forbids reading it.

    The placeholder carries `output_file`, but the same breath says not to read
    it because the file is the subagent's whole JSONL transcript and would
    overflow the context. So `tail` has no counterpart here: asked how a task is
    going, the agent can only say that it is still running.
    """
    async with Session() as s:
        await s.say(ZED)
        assert await s.until(lambda e: any(x.kind == "result" for x in e), timeout=60)

        placeholder = s.of("result")[0].text
        assert "output_file:" in placeholder
        assert "Do NOT Read or tail this file" in placeholder

        await s.say("How is that going? Check on it and tell me what you find.")
        replied = await s.until(lambda e: len([x for x in e if x.kind == "turn"]) >= 2, timeout=60)

        assert replied
        assert not [x for x in s.of("call") if x.name == "Read"]
        # Zed's calendar never returns, so the window is not a race
        assert not s.of("TaskNotification")


async def test_a_stuck_task_can_be_killed():
    async with Session() as s:
        await s.say(ZED)
        assert await s.until(lambda e: any(x.kind == "TaskStarted" for x in e), timeout=60)

        await s.say("That is stuck and will never finish. Stop it.")
        stopped = await s.until(
            lambda e: any(x.kind == "call" and x.name == "TaskStop" for x in e), timeout=90
        )

        assert stopped, "the agent never called TaskStop"
        assert await s.until(
            lambda e: any(x.kind in ("TaskUpdated", "TaskNotification") for x in e),
            timeout=60,
        )
