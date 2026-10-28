"""Chat with the exp10 agent beside a debugger showing what it is doing underneath.

    LLM_CACHE=off uv run uvicorn main.exp10.app:app --port 8000

The left side is the conversation. The right side is the current state (every call,
and the messages the model would be sent if it were asked now), then the timeline:
each entry stored, each event queued and each model call, newest first.
"""

import asyncio
import time

from fasthtml.common import (
    H3,
    Button,
    Details,
    Div,
    EventStream,
    Form,
    Input,
    Main,
    P,
    Pre,
    Script,
    Span,
    Style,
    Summary,
    Table,
    Td,
    Th,
    Titled,
    Tr,
    fast_app,
    serve,
    sse_message,
)

from ..bedrock import raw_client
from ..exp3.tools import schedule
from .agent import Agent
from .tools import kill, tail, weather
from .trace import Trace, dump

CSS = """
main.container { max-width:none; }
#view { display:grid; grid-template-columns:minmax(20rem,1fr) minmax(28rem,1.2fr); gap:1.5rem; }
#transcript { display:flex; flex-direction:column; gap:.6rem; margin-bottom:1rem; }
.row { display:flex; }
.row.user { justify-content:flex-end; }
.bubble { max-width:40rem; padding:.55rem .85rem; border-radius:1rem; white-space:pre-wrap; }
.user .bubble { background:#1f6feb; color:#fff; border-bottom-right-radius:.25rem; }
.agent .bubble { background:#f1f3f5; color:#111; border-bottom-left-radius:.25rem; }
form { display:flex; gap:.5rem; }
input[name=msg] { flex:1; padding:.55rem .75rem; }
.debug { font-size:.78rem; max-height:85vh; overflow:auto; }
.debug pre { font-size:.72rem; padding:.5rem; margin:.25rem 0 .5rem; white-space:pre-wrap; }
.debug details { margin:0 0 .2rem; }
.debug summary { cursor:pointer; }
.debug td, .debug th { padding:.15rem .4rem; font-size:.75rem; }
.k { display:inline-block; min-width:4.5rem; font-weight:600; }
.k.entry { color:#1a7f37; } .k.event { color:#9a6700; } .k.request { color:#0969da; }
.k.response { color:#8250df; } .k.error { color:#cf222e; }
.t { color:#57606a; margin-right:.4rem; }
"""

# the agent speaks and its tasks settle without anyone asking, so the page is pushed
# to: one event per step, added where it belongs, and nothing already on the page is
# drawn again. The step number is the SSE id, so a reconnect resumes where it left off
STREAM = """
const es = new EventSource('/events?after=' + AFTER);
const on = (name, put) => es.addEventListener(name, m =>
  put(document.createRange().createContextualFragment(m.data)));
on('step', f => document.getElementById('steps').prepend(f));
on('said', f => document.getElementById('transcript').append(f));
on('state', f => {
  const open = document.getElementById('model-view')?.open;
  document.getElementById('state').replaceWith(f);
  if (open) document.getElementById('model-view').open = true;
});
"""


def bubble(said):
    who, text = said
    return Div(Span(text, cls="bubble"), cls=f"row {who}")


def transcript(steps):
    return Div(*[bubble(s.said) for s in steps if s.said], id="transcript")


def composer():
    return Form(
        Input(name="msg", placeholder="Ask something...", autofocus=True, autocomplete="off"),
        Button("Send"),
        hx_post="/say",
        hx_swap="none",
        hx_on__after_request="this.reset()",
    )


def state(agent):
    with agent._cv:
        calls = list(agent.calls.values())
        owed = sorted(agent.owed)
        errors = [repr(e) for e in agent.errors]
        view = agent.render() if agent.log else []
    rows = [
        Tr(
            Td(f"#{c.id}"),
            Td(c.sig),
            Td(f"q#{c.question}"),
            Td(f"b#{c.batch}"),
            Td("killed" if c.killed else "returned" if c.result is not None else "running"),
        )
        for c in calls
    ]
    return Div(
        H3("state now"),
        Table(Tr(Th("task"), Th("call"), Th("question"), Th("breath"), Th("state")), *rows)
        if rows
        else P("no calls yet"),
        P(f"batches not yet reported: {owed or 'none'}"),
        *[Pre(e) for e in errors],
        Details(
            Summary(f"what the model would be sent now ({len(view)} messages)"),
            Pre(dump(view)),
            id="model-view",
        ),
        id="state",
    )


def item(s):
    return Details(
        Summary(
            Span(time.strftime("%H:%M:%S", time.localtime(s.at)), cls="t"),
            Span(s.kind, cls=f"k {s.kind}"),
            s.title,
        ),
        Pre(s.body or "(empty)"),
        id=f"step-{s.n}",
    )


def timeline(steps):
    return Div(H3("timeline"), Div(*[item(s) for s in steps[::-1]], id="steps"), id="timeline")


def sse(event: str, elm, id: int | None = None) -> str:
    head = f"id: {id}\n" if id is not None else ""
    return head + sse_message(elm, event)


def frames(agent, trace, after: int, upto: int) -> list[str]:
    """What the page has not seen yet: each step after `after`, then the state now."""
    out = []
    for s in trace.steps[after:upto]:
        out.append(sse("step", item(s), id=s.n))
        if s.said:
            out.append(sse("said", bubble(s.said)))
    return out + [sse("state", state(agent))]


def make_app(agent, trace):
    app, rt = fast_app(pico=True, hdrs=(Style(CSS),))

    @rt("/")
    def index():
        steps = trace.steps[: trace.version]
        return Titled(
            "exp10, with the debugger",
            Main(
                Div(
                    Div(transcript(steps), composer()),
                    Div(state(agent), timeline(steps), cls="debug"),
                    id="view",
                )
            ),
            Script(f"const AFTER = {len(steps)};\n{STREAM}"),
        )

    @rt("/events")
    async def events(request, after: int = 0):
        # a reconnect says which step it saw last, and that wins over the page's own
        seen = int(request.headers.get("last-event-id") or after)

        async def stream():
            nonlocal seen
            while True:
                now = await asyncio.to_thread(trace.wait, seen)
                if now != seen:
                    for f in frames(agent, trace, seen, now):
                        yield f
                    seen = now

        return EventStream(stream())

    @rt("/say")
    def say(msg: str = ""):
        if msg.strip():
            agent.post(msg.strip())
        return ""

    return app


trace = Trace()
agent = trace.attach(Agent(tools=[weather, schedule, tail, kill],client=trace.client(raw_client())))
app = make_app(agent, trace)

if __name__ == "__main__":
    serve()
