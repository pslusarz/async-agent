import asyncio

from fasthtml.common import (
    Button,
    Div,
    EventStream,
    Form,
    Input,
    Main,
    Script,
    Span,
    Style,
    Titled,
    fast_app,
    serve,
    sse_message,
)

from ..exp3.tools import schedule, temperature
from ..exp5.tools import kill, new_thread, tail
from .agent import Agent
from .chat import Chat

SP = (
    "Tools run in the background and take a while. Calling one returns a task id, not "
    "a result. When the user asks how something is going, check on it and tell them."
)

CSS = """
#transcript { display:flex; flex-direction:column; gap:.6rem; margin-bottom:1rem; }
.row { display:flex; align-items:center; gap:.5rem; }
.row.user { justify-content:flex-end; }
.bubble { max-width:40rem; padding:.55rem .85rem; border-radius:1rem; white-space:pre-wrap; }
.user .bubble { background:#1f6feb; color:#fff; border-bottom-right-radius:.25rem; }
.agent .bubble { background:#f1f3f5; color:#111; border-bottom-left-radius:.25rem; }
form { display:flex; gap:.5rem; }
input[name=msg] { flex:1; padding:.55rem .75rem; }
.chips { display:flex; align-items:center; gap:.4rem; flex-wrap:wrap; }
.task { display:inline-flex; align-items:center; gap:.35rem; border:1px solid #d0d7de; border-radius:1rem; padding:.2rem .65rem; font-size:.78rem; }
.task .name { font-weight:600; }
.task .args { color:#57606a; }
.dot { width:.7rem; height:.7rem; border-radius:50%; flex:none; }
.dot.done { background:#2da44e; }
.dot.failed { background:#cf222e; }
.spinner { width:.8rem; height:.8rem; flex:none; border:2px solid #d0d7de; border-top-color:#1f6feb; border-radius:50%; animation:spin .8s linear infinite; }
@keyframes spin { to { transform:rotate(360deg); } }
"""

# the agent speaks and its tasks settle without anyone asking, so the page is pushed to
STREAM = """
const es = new EventSource('/events');
es.onmessage = e => { document.getElementById('transcript').outerHTML = e.data; };
"""


def chip(w):
    if w.state == "running":
        return Span(
            Span(cls="spinner"),
            Span(w.tool, cls="name"),
            Span(w.label, cls="args"),
            cls="task",
        )
    return Span(cls=f"dot {w.state}", title=f"{w.tool}({w.label}) {w.state}")


def row(chat, entry):
    chips = [chip(w) for w in chat.calls(entry.id)]
    return Div(
        Span(entry.text, cls="bubble") if entry.text else None,
        Div(*chips, cls="chips") if chips else None,
        cls=f"row {entry.role}",
    )


def transcript(chat):
    return Div(*[row(chat, e) for e in chat.entries()], id="transcript")


def composer():
    return Form(
        Input(
            name="msg",
            placeholder="Ask something...",
            autofocus=True,
            autocomplete="off",
        ),
        Button("Send"),
        hx_post="/say",
        hx_swap="none",
        hx_on__after_request="this.reset()",
    )


def make_app(chat):
    app, rt = fast_app(pico=True, hdrs=(Style(CSS),))

    @rt("/")
    def index():
        return Titled("async agent", Main(transcript(chat), composer()), Script(STREAM))

    @rt("/events")
    async def events():
        async def stream():
            seen = -1
            while True:
                seen = await asyncio.to_thread(chat.wait, seen)
                yield sse_message(transcript(chat))

        return EventStream(stream())

    @rt("/say")
    def say(msg: str = ""):
        if msg.strip():
            chat.say(msg.strip())
        return ""

    return app


chat = Chat(Agent(sp=SP, tools=[temperature, schedule, tail, kill, new_thread]))
app = make_app(chat)

if __name__ == "__main__":
    serve()
