import asyncio

from main.exp1.agent import Agent


async def test_ask_returns_reply():
    async with Agent(sp="Answer with one word.") as a:
        r = await a.ask("Say OK and nothing else.")
        assert r.kind == "assistant"
        assert "OK" in r.text


async def test_stream_sees_replies_in_order():
    async with Agent(sp="Answer with one word.") as a:
        seen = []

        async def watch():
            async for ev in a.stream():
                seen.append(ev)

        t = asyncio.create_task(watch())
        await asyncio.sleep(0)
        e1 = a.send("Say ONE and nothing else.")
        e2 = a.send("Say TWO and nothing else.")
        await a.stop()
        await t

    assert [p.parent for p in seen] == [e1.id, e2.id]


async def test_history_is_retained_across_turns():
    async with Agent(sp="Answer with a single name and nothing else.") as a:
        r1 = await a.ask("John is the son of Mary. Who is John's mother?")
        r2 = await a.ask("Anne is John's daughter. Who is her dad?")
        r3 = await a.ask("Who is Anne's grandmother?")

    assert "Mary" in r1.text
    assert "John" in r2.text
    assert "Mary" in r3.text

    assert [p.id for p in a.thread.walk()] == [
        r1.parent, r1.id, r2.parent, r2.id, r3.parent, r3.id,
    ]
    assert [m["role"] for m in a.thread.render()] == [
        "user", "assistant", "user", "assistant", "user", "assistant",
    ]
