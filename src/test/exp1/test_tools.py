from main.exp1.agent import Agent
from main.exp1.tools import FINISHED, kill, tail, temperature


async def test_user_gets_answer_from_async_tool():
    async with Agent(tools=[temperature, tail, kill]) as a:
        r = await a.ask("What is the temperature in Warsaw, MO?")

        result = next(p for p in a.thread.walk() if p.kind == "tool_result")
        await tail.fn(a, task=result.id)
        await kill.fn(a, task=result.id)

    assert "72" in r.text

    call = next(p for p in a.thread.walk() if p.kind == "tool_call")
    assert call.meta["name"] == "temperature"
    assert call.meta["input"] == dict(city="Warsaw", state="MO")

    assert result.text == "72"
    assert result.meta["done"] is True
    assert [p.text for p in a.thread.walk() if p.kind == "probe"] == [FINISHED, FINISHED]
