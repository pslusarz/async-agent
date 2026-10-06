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

SCHEDULE = dict(
    name="schedule",
    description="Look up one person's free hours today. Call once per person.",
    input_schema=dict(
        type="object",
        properties=dict(person=dict(type="string", description="First name")),
        required=["person"],
    ),
)

MEETS = "agent answers the meeting question"

AUSTIN = [
    ("looking up station KAUS", 1.2),
    ("station reached, reading sensors", 1.4),
    ("averaging the last hour", 1.4),
    ("cross-checking a neighbouring station", 1.4),
    ("applying the shade correction", 1.4),
]

PEOPLE = {
    "Jane": (
        [
            ("opening Jane's calendar", 1.2),
            ("merging two shared calendars", 1.4),
        ],
        "free 9-12",
    ),
    "Jack": (
        [
            ("opening Jack's calendar", 1.2),
            ("waiting on the room-booking service", 1.4),
            ("merging two shared calendars", 1.4),
        ],
        "free 10-14",
    ),
}


def _overlap(director):
    order = list(PEOPLE)

    def weather(city, state):
        # outlives the whole scheduling exchange, so its answer lands out of order
        return Scripted(
            director,
            f"temperature({city})",
            list(AUSTIN),
            f"72F in {city}, {state}",
            settle_after=MEETS,
        )

    def calendar(person):
        steps, answer = PEOPLE[person]
        return Scripted(
            director,
            f"schedule({person})",
            list(steps),
            answer,
            lead=0.12 * order.index(person),
        )

    replies = [
        reply(
            "agent starts the Austin lookup",
            1.2,
            "Let me check.",
            use("temperature", city="Austin", state="TX", timeout=60),
        ),
        reply(
            "agent starts two calendar lookups",
            1.4,
            "Sure - I'll look both of them up while that runs.",
            *(use("schedule", person=p, timeout=60) for p in PEOPLE),
        ),
        reply(
            MEETS,
            1.4,
            "Jane is free 9-12 and Jack 10-14, so between 10 and 12 suits them both.",
        ),
        reply(
            "agent answers the Austin question",
            1.4,
            "72F in Austin, TX.",
        ),
    ]
    return [Tool(TEMPERATURE, weather), Tool(SCHEDULE, calendar)], replies


OVERLAP = Scenario(
    key="overlap",
    title="A second question, about something else entirely",
    blurb=(
        "A weather lookup is still running when the user asks an unrelated scheduling "
        "question, so two different tools are in flight at once. The calendars come "
        "back first and are answered on the spot; the weather lands afterwards and "
        "has to say which question it belongs to."
    ),
    says=[
        Says("what's the temperature in Austin?"),
        Says(
            "while that's running - when can Jane and Jack meet today?",
            after="temperature(Austin): station reached",
        ),
    ],
    build=_overlap,
)


SCENARIOS = [ONE_CALL, WEATHER, OVERLAP]
BY_KEY = {s.key: s for s in SCENARIOS}
