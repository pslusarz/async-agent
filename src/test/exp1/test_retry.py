from main.exp1.agent import Agent
from main.exp1.tools import NEEDS_FULL_STATE, strict_temperature


async def test_failing_tool_triggers_a_retry_loop():
    async with Agent(tools=[strict_temperature]) as a:
        r = await a.ask("What is the temperature in Warsaw, MO?")

    assert "72" in r.text

    calls = [p for p in a.thread.walk() if p.kind == "tool_call"]
    results = [p for p in a.thread.walk() if p.kind == "tool_result"]

    assert len(calls) == 2
    assert calls[0].meta["input"]["state"] == "MO"
    assert calls[1].meta["input"]["state"] == "Missouri"
    assert [p.text for p in results] == [NEEDS_FULL_STATE, "72"]

    assert a.thread.root_of(r.id) == calls[0].parent
    assert [m["role"] for m in a.thread.render()] == [
        "user", "assistant", "user", "assistant", "user", "assistant",
    ]
