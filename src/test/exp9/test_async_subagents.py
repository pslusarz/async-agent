import asyncio

import pytest
from langgraph_sdk import get_client

from main.exp9.watch import NUDGE, disarm

pytestmark = pytest.mark.live

Q = "When can Jane, Jack and Joe meet today?"
INSTEAD = "Hold on, leave Joe out of it - just Jane and Jack."


async def turn(cli, thread: str, text: str) -> dict:
    return await cli.runs.wait(
        thread,
        "supervisor",
        input={"messages": [{"role": "user", "content": text}]},
        multitask_strategy="enqueue",
    )


def calls(state: dict, name: str) -> list[dict]:
    return [
        c
        for m in state["messages"]
        if m.get("type") == "ai"
        for c in m.get("tool_calls") or []
        if c["name"] == name
    ]


def said(state: dict) -> str:
    text = state["messages"][-1]["content"]
    return text if isinstance(text, str) else " ".join(b.get("text", "") for b in text)


def spoken(state: dict) -> list[str]:
    out = []
    for m in state["messages"]:
        if m.get("type") != "ai":
            continue
        body = m["content"]
        text = (
            body if isinstance(body, str) else " ".join(b.get("text", "") for b in body)
        )
        if text:
            out.append(text)
    return out


async def waited(cli, thread: str, pred, timeout: float = 180.0) -> dict | None:
    due = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < due:
        state = (await cli.threads.get_state(thread))["values"]
        if pred(state):
            return state
        await asyncio.sleep(2)
    return None


async def test_the_supervisor_launches_a_task_and_goes_on_talking(server):
    cli = get_client(url=server)
    thread = (await cli.threads.create())["thread_id"]

    state = await turn(cli, thread, Q)

    assert calls(state, "start_async_task")
    tasks = state["async_tasks"]
    assert len(tasks) == 1
    task = next(iter(tasks.values()))
    assert task["agent_name"] == "researcher" and task["status"] == "running"
    # it answered the person rather than waiting for the subagent
    assert said(state)
    # and asked to be woken, because nothing else would tell it the task had finished
    assert calls(state, "check_back_in")
    assert await cli.runs.list(thread, status="pending", limit=10)


async def test_the_answer_arrives_without_being_asked_for(server):
    cli = get_client(url=server)
    thread = (await cli.threads.create())["thread_id"]

    state = await turn(cli, thread, Q)
    before = len(spoken(state))

    # nothing more is said to it from here: the wake-up it armed brings it back
    state = await waited(
        cli, thread, lambda s: any("11" in w for w in spoken(s)[before:])
    )
    assert state, "the supervisor never came back with the answer on its own"
    assert state["async_tasks"][next(iter(state["async_tasks"]))]["status"] == "success"


async def test_progress_can_be_reported_while_the_task_runs(server):
    cli = get_client(url=server)
    thread = (await cli.threads.create())["thread_id"]

    await turn(cli, thread, Q)
    state = await turn(cli, thread, "How is that going?")

    assert calls(state, "peek_async_task") or calls(state, "check_async_task")


async def test_a_change_of_mind_goes_to_the_running_task(server):
    cli = get_client(url=server)
    thread = (await cli.threads.create())["thread_id"]

    state = await turn(cli, thread, Q)
    task = next(iter(state["async_tasks"]))

    state = await turn(cli, thread, INSTEAD)

    told = calls(state, "update_async_task")
    assert told and told[0]["args"]["task_id"] == task
    # the task keeps its id, and its history, across the update
    assert set(state["async_tasks"]) == {task}


async def test_a_task_can_be_called_off(server):
    cli = get_client(url=server)
    thread = (await cli.threads.create())["thread_id"]

    state = await turn(cli, thread, Q)
    task = next(iter(state["async_tasks"]))

    state = await turn(
        cli, thread, "Never mind, stop looking - I will ask them myself."
    )

    assert calls(state, "cancel_async_task")
    assert state["async_tasks"][task]["status"] == "cancelled"


async def test_only_the_newest_wake_up_stays_armed(server):
    cli = get_client(url=server)
    thread = (await cli.threads.create())["thread_id"]
    for _ in range(2):
        await cli.runs.create(
            thread,
            "supervisor",
            input={"messages": [{"role": "user", "content": f"{NUDGE} look again"}]},
            metadata={"nudge": True},
            multitask_strategy="enqueue",
            after_seconds=600,
        )
    assert len(await cli.runs.list(thread, status="pending", limit=10)) == 2

    await disarm(cli, thread)

    assert not await cli.runs.list(thread, status="pending", limit=10)
