import asyncio

from claude_agent_sdk import AgentDefinition, create_sdk_mcp_server, tool

FREE = {"jane": "free 9am to 12pm", "jack": "free 10am to 2pm"}
SLOW_PERSON = "joe"
STUCK_PERSON = "zed"
SLOW_SECONDS = 20.0
STUCK_SECONDS = 600.0

NEEDS_FULL_STATE = (
    "error: state must be spelled out in full, not abbreviated. "
    "Retry this tool with the full state name."
)


def _text(s: str) -> dict:
    return {"content": [{"type": "text", "text": s}]}


@tool(
    "temperature",
    "Get the current temperature in Fahrenheit for a US city.",
    {"city": str, "state": str},
)
async def temperature(args):
    return _text("72")


@tool(
    "strict_temperature",
    "Get the current temperature in Fahrenheit for a US city.",
    {"city": str, "state": str},
)
async def strict_temperature(args):
    return _text("72" if len(args["state"]) > 2 else NEEDS_FULL_STATE)


@tool(
    "lookup_calendar",
    "Look up one person's free hours today. Call once per person.",
    {"person": str},
)
async def lookup_calendar(args):
    who = args["person"].strip().lower()
    if who == STUCK_PERSON:
        await asyncio.sleep(STUCK_SECONDS)
    elif who not in FREE:
        await asyncio.sleep(SLOW_SECONDS)
    return _text(f"{args['person']} is {FREE.get(who, 'free 11am to 3pm')}")


server = create_sdk_mcp_server(
    name="tools",
    version="1.0.0",
    tools=[lookup_calendar, temperature, strict_temperature],
)

CALENDAR = AgentDefinition(
    description="Looks up one person's calendar. Use for any question about someone's availability.",
    prompt=(
        "Call lookup_calendar once for the person named, then report exactly what it "
        "returned. Say nothing else."
    ),
    tools=["mcp__tools__lookup_calendar"],
    model="sonnet",
    # the model asks for run_in_background=False; this overrides it
    background=True,
)

WEATHER = AgentDefinition(
    description="Reports the current temperature for a US city.",
    prompt=(
        "Call temperature for the city named, then report exactly what it returned. "
        "Say nothing else."
    ),
    tools=["mcp__tools__temperature"],
    model="sonnet",
    background=True,
)

STRICT_WEATHER = AgentDefinition(
    description="Reports the current temperature for a US city from a fussy service.",
    prompt=(
        "Call strict_temperature for the city named. If it answers with an error that "
        "tells you how to correct the call, fix the arguments and call it again. Report "
        "exactly what it finally returned. Say nothing else."
    ),
    tools=["mcp__tools__strict_temperature"],
    model="sonnet",
    background=True,
)
