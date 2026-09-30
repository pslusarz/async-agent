import asyncio

from claude_agent_sdk import AgentDefinition, create_sdk_mcp_server, tool

FREE = {"jane": "free 9am to 12pm", "jack": "free 10am to 2pm"}
SLOW_PERSON = "joe"
STUCK_PERSON = "zed"
SLOW_SECONDS = 20.0
STUCK_SECONDS = 600.0


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
    return {
        "content": [
            {
                "type": "text",
                "text": f"{args['person']} is {FREE.get(who, 'free 11am to 3pm')}",
            }
        ]
    }


server = create_sdk_mcp_server(name="toys", version="1.0.0", tools=[lookup_calendar])

CALENDAR = AgentDefinition(
    description="Looks up one person's calendar. Use for any question about someone's availability.",
    prompt=(
        "Call lookup_calendar once for the person named, then report exactly what it "
        "returned. Say nothing else."
    ),
    tools=["mcp__toys__lookup_calendar"],
    model="sonnet",
    # the model asks for run_in_background=False; this overrides it
    background=True,
)
