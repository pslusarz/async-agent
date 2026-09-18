import random
import time

from ..exp2.tools import Tool

MAX_SECONDS = 120.0
DUE = (6.0, 45.0)


def timed(name: str, description: str, properties: dict, answer, due=DUE) -> Tool:
    """A tool that settles on a random completion time when called and reports progress."""
    lo = min(min(due), MAX_SECONDS)
    hi = min(max(due), MAX_SECONDS)

    def fn(agent, node: int, **kw):
        total = random.uniform(lo, hi)
        started = time.monotonic()

        def tail():
            spent = time.monotonic() - started
            pct = min(99, int(100 * spent / total))
            return f"{pct}% done, about {max(1, round(total - spent))}s to go"

        agent.watch(node, tail)
        if not agent.tasks[node].cancel.wait(total):
            agent.result(node, answer(**kw) if callable(answer) else answer)

    return Tool(
        dict(
            name=name,
            description=description,
            input_schema=dict(
                type="object",
                properties=properties,
                required=list(properties),
            ),
        ),
        fn,
    )


FREE = {"jane": "free 9-12", "jack": "free 10-14", "joe": "free 11-15"}


def free_hours(person: str) -> str:
    who = person.strip().lower()
    if who in FREE:
        return FREE[who]
    # seeded by name, so asking twice about the same person agrees
    r = random.Random(who)
    start = r.randint(8, 13)
    return f"free {start}-{start + r.randint(2, 5)}"


temperature = timed(
    "temperature",
    "Get the current temperature in Fahrenheit for a US city.",
    dict(
        city=dict(type="string", description="City name"),
        state=dict(type="string", description="Two-letter state code"),
    ),
    lambda city, state: f"72F in {city}, {state}",
)

schedule = timed(
    "schedule",
    "Look up one person's free hours today. Call once per person.",
    dict(person=dict(type="string", description="First name")),
    lambda person: free_hours(person),
)

build_time = timed(
    "build_time",
    "Find out how long the current build will take.",
    {},
    "12 minutes",
)

TOOLS = [temperature, schedule, build_time]
