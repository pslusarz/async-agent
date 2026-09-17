from main.exp1.agent import Agent
from main.exp1.tools import slow_temperature, tail

SP = (
    "Tools run asynchronously. A tool call returns a task id immediately, not a result. "
    "When the user asks whether an answer is ready, use the tail tool on that task id to "
    "check progress, then report what you found. Never start a second task for a question "
    "that already has one running, and always reply to the user in the same turn."
)


async def test_user_probes_a_running_tool_then_gets_the_answer():
    async with Agent(sp=SP, tools=[slow_temperature, tail]) as a:
        q = a.send("What is the temperature in Warsaw, MO?")

        r1 = await a.ask("Do you know the answer yet?")
        r2 = await a.ask("Do you know the answer yet?")
        r3 = await a.ask("Do you know the answer yet?")

        answer = await a.reply(q)

    probes = [p.text for p in a.thread.walk() if p.kind == "probe"]
    assert probes[:3] == ["30% complete", "60% complete", "90% complete"]

    assert "30" in r1.text
    assert "60" in r2.text
    assert "90" in r3.text
    assert "72" in answer.text

    result = next(p for p in a.thread.walk() if p.kind == "tool_result")
    assert result.text == "72"
    assert not [p for p in a.thread.walk() if p.meta.get("name") == "tail"]
