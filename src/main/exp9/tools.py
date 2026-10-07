import asyncio
import random

from langchain_core.tools import tool

DUE = (6.0, 20.0)
FREE = {"jane": "free 9-12", "jack": "free 10-14", "joe": "free 11-15"}


async def takes_a_while():
    await asyncio.sleep(random.uniform(*DUE))


@tool
async def temperature(city: str, state: str) -> str:
    """Get the current temperature in Fahrenheit for a US city."""
    await takes_a_while()
    return f"72F in {city}, {state}"


@tool
async def schedule(person: str) -> str:
    """Look up one person's free hours today. Call once per person."""
    await takes_a_while()
    who = person.strip().lower()
    if who in FREE:
        return FREE[who]
    r = random.Random(who)
    start = r.randint(8, 13)
    return f"free {start}-{start + r.randint(2, 5)}"


@tool
async def build_time() -> str:
    """Find out how long the current build will take."""
    await takes_a_while()
    return "12 minutes"


TOOLS = [temperature, schedule, build_time]
