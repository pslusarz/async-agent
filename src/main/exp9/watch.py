import os

from langchain.tools import ToolRuntime
from langchain_core.tools import tool
from langgraph_sdk import get_client

SERVER = os.getenv("EXP9_SERVER", "http://127.0.0.1:2024")
SUPERVISOR = "supervisor"
# said by the timer rather than by the person, so the app can keep it off the transcript
NUDGE = "[automatic]"
IDLE = "nothing reported yet"


def client():
    return get_client(url=SERVER)


def words(m: dict) -> str:
    body = m.get("content")
    if isinstance(body, str):
        return body
    return " ".join(b.get("text", "") for b in body or [] if isinstance(b, dict))


@tool
async def peek_async_task(task_id: str) -> str:
    """See what a running task is doing right now: its own latest words, and the tools
    it has started and finished so far. Use this to tell the person how it is going."""
    state = (await client().threads.get_state(task_id))["values"]
    messages = state.get("messages", [])
    done = {m["tool_call_id"] for m in messages if m.get("type") == "tool"}
    started = [
        f"{c['name']}({', '.join(f'{k}={v}' for k, v in c['args'].items())})"
        f" - {'done' if c['id'] in done else 'still running'}"
        for m in messages
        if m.get("type") == "ai"
        for c in m.get("tool_calls") or []
    ]
    latest = next((w for m in reversed(messages) if (w := words(m))), "")
    return "\n".join(filter(None, [latest, *started])) or IDLE


@tool
async def check_back_in(seconds: int, note: str, runtime: ToolRuntime) -> str:
    """Arrange to be woken after `seconds` so you can look at a running task again.
    Always do this when you start a task: nothing else will tell you it has finished.
    `note` is what you want to be reminded to do, in your own words."""
    thread = runtime.config["configurable"]["thread_id"]
    cli = client()
    await disarm(cli, thread)
    await cli.runs.create(
        thread,
        SUPERVISOR,
        input={"messages": [{"role": "user", "content": f"{NUDGE} {note}"}]},
        metadata={"nudge": True},
        multitask_strategy="enqueue",
        after_seconds=int(seconds),
    )
    return f"you will be woken in {seconds}s"


async def disarm(cli, thread: str):
    """Cancel a wake-up that has not fired, so only the newest one is ever armed."""
    for run in await cli.runs.list(thread, status="pending", limit=20):
        if (run.get("metadata") or {}).get("nudge"):
            await cli.runs.cancel(thread, run["run_id"])
