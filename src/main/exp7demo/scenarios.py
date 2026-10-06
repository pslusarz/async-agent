from dataclasses import dataclass
from typing import Callable

from ..exp2.tools import TEMPERATURE, Tool
from .script import Scripted, reply, scripted, use

BUILD_TIME = dict(
    name="build_time",
    description="Find out how long the current build will take.",
    input_schema=dict(type="object", properties={}, required=[]),
)

SP = (
    "Tools run in the background and take a while. Calling one returns a task id, not "
    "a result. When the user asks how something is going, check on it and tell them."
)


@dataclass
class Says:
    """One scripted user message, held back until its cue has played."""

    text: str
    delay: float = 0.8
    after: str = ""


@dataclass
class Scenario:
    key: str
    title: str
    blurb: str
    says: list[Says]
    build: Callable
    sp: str = SP


def _one_call(director):
    tools = [
        scripted(
            director,
            BUILD_TIME,
            [
                ("queued behind two other jobs", 1.6),
                ("compiling, 40% done", 1.6),
                ("compiling, 80% done", 1.6),
            ],
            "12 minutes",
        )
    ]
    replies = [
        reply(
            "agent starts build_time",
            1.2,
            "Let me find out.",
            use("build_time", timeout=60),
        ),
        reply("agent answers", 1.4, "The build needs about 12 minutes."),
    ]
    return tools, replies


ONE_CALL = Scenario(
    key="one-call",
    title="One tool call",
    blurb=(
        "The simplest shape: a question, a tool that takes a while, and the answer "
        "arriving on its own once the task settles."
    ),
    says=[Says("how long will the build take?")],
    build=_one_call,
)


REPORTS = "agent reports progress"

CITIES = {
    "New York": (
        "NY",
        [
            ("looking up station KNYC", 1.2),
            ("station reached, reading sensors", 1.4),
            ("averaging the last hour", 1.4),
            ("cross-checking a neighbouring station", 1.4),
        ],
        "61F in New York, NY",
    ),
    "San Francisco": (
        "CA",
        [
            ("looking up station KSFO", 1.2),
            ("station busy, retrying", 1.4),
            ("station reached, reading sensors", 1.4),
            ("averaging the last hour", 1.4),
            ("cross-checking a neighbouring station", 1.4),
        ],
        "57F in San Francisco, CA",
    ),
    "Chicago": (
        "IL",
        [
            ("looking up station KORD", 1.2),
            ("station reached, reading sensors", 1.4),
            ("sensors disagree, taking a third reading", 1.4),
            ("averaging the last hour", 1.4),
            ("cross-checking a neighbouring station", 1.4),
            ("rounding", 1.2),
        ],
        "48F in Chicago, IL",
    ),
}

JOKE = (
    "A background task walks into a bar. The bartender says, 'we close in an hour.' "
    "The task says, 'that's fine, I'll let you know.'"
)


def _weather(director):
    order = list(CITIES)

    def make(city, state):
        _, steps, answer = CITIES[city]
        return Scripted(
            director,
            f"temperature({city})",
            list(steps),
            answer,
            lead=0.12 * order.index(city),
            # none of the three may land before the agent has said how they are doing
            settle_after=REPORTS,
        )

    replies = [
        reply(
            "agent starts three lookups",
            1.2,
            "Checking all three.",
            *(
                use("temperature", city=c, state=s, timeout=60)
                for c, (s, _, _) in CITIES.items()
            ),
        ),
        reply("agent tells the joke", 1.6, JOKE),
        reply(
            "agent tails all three tasks",
            1.2,
            "",
            *(use("tail", task=tid) for tid in (3, 4, 5)),
        ),
        reply(
            REPORTS,
            1.4,
            "All three are still going. San Francisco had to retry a busy station, "
            "and none of them has landed yet - I'll tell you the moment they do.",
        ),
        reply(
            "agent answers with all three",
            1.4,
            "All in: 61F in New York, 57F in San Francisco, 48F in Chicago.",
        ),
    ]
    return [Tool(TEMPERATURE, make)], replies


WEATHER = Scenario(
    key="weather",
    title="Three at once, with a conversation over the top",
    blurb=(
        "Three lookups start together and the conversation carries on regardless: a "
        "joke while they run, a progress check that makes the agent tail every task, "
        "and then the answer arriving on its own once the last one settles."
    ),
    says=[
        Says("what's the weather in New York, San Francisco and Chicago?"),
        Says(
            "while that's going, tell me a joke",
            after="temperature(Chicago): looking up",
        ),
        Says(
            "any luck with the weather?",
            after="temperature(Chicago): sensors disagree",
        ),
    ],
    build=_weather,
)

SCENARIOS = [ONE_CALL, WEATHER]
BY_KEY = {s.key: s for s in SCENARIOS}
