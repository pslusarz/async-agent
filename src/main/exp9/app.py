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
from langgraph_sdk import get_client

from .watch import NUDGE, SERVER

TICK = 1.5
DOT = {"success": "done", "error": "failed", "cancelled": "failed"}

CSS = """
#transcript { display:flex; flex-direction:column; gap:.6rem; margin-bottom:1rem; }
.row { display:flex; align-items:center; gap:.5rem; }
.row.human { justify-content:flex-end; }
.bubble { max-width:40rem; padding:.55rem .85rem; border-radius:1rem; white-space:pre-wrap; }
.human .bubble { background:#1f6feb; color:#fff; border-bottom-right-radius:.25rem; }
.ai .bubble { background:#f1f3f5; color:#111; border-bottom-left-radius:.25rem; }
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
.crew { display:flex; flex-direction:column; gap:.3rem; border:1px solid #d0d7de; border-radius:.75rem; padding:.45rem .7rem; max-width:30rem; }
.crew .head { display:flex; align-items:center; gap:.4rem; font-size:.8rem; }
.crew .name { font-weight:600; }
.crew .brief { color:#57606a; font-size:.78rem; }
.crew .note { font-size:.75rem; font-style:italic; }
"""

STREAM = """
const es = new EventSource('/events');
es.onmessage = e => { document.getElementById('transcript').outerHTML = e.data; };
"""

cli = get_client(url=SERVER)
session: dict = {"thread": None}


def text_of(m: dict) -> str:
    body = m.get("content")
    if isinstance(body, str):
        return body
    return " ".join(b.get("text", "") for b in body or [] if isinstance(b, dict))


def answered(messages: list[dict]) -> set[str]:
    return {m["tool_call_id"] for m in messages if m.get("type") == "tool"}


def chip(name: str, label: str, state: str):
    if state == "running":
        return Span(
            Span(cls="spinner"),
            Span(name, cls="name"),
            Span(label, cls="args"),
            cls="task",
        )
    return Span(cls=f"dot {state}", title=f"{name}({label}) {state}")


def chips_of(messages: list[dict]) -> list:
    done = answered(messages)
    return [
        chip(
            c["name"],
            ", ".join(f"{k}={v}" for k, v in c["args"].items())[:60],
            "done" if c["id"] in done else "running",
        )
        for m in messages
        if m.get("type") == "ai"
        for c in m.get("tool_calls") or []
    ]


async def crew(task: dict):
    """What the subagent's own thread says it is doing, read back over the SDK."""
    state = (await cli.threads.get_state(task["thread_id"]))["values"]
    messages = state.get("messages", [])
    brief = next((text_of(m) for m in messages if m.get("type") == "human"), "")
    note = next(
        (
            text_of(m)
            for m in reversed(messages)
            if m.get("type") == "ai" and text_of(m)
        ),
        "",
    )
    status = task["status"]
    head = (
        Span(cls="spinner")
        if status == "running"
        else Span(cls=f"dot {DOT.get(status, 'failed')}")
    )
    return Div(
        Div(
            head,
            Span(task["agent_name"], cls="name"),
            Span(status, cls="brief"),
            cls="head",
        ),
        Div(brief, cls="brief"),
        Div(note, cls="note"),
        Div(*chips_of(messages), cls="chips"),
        cls="crew",
    )


def row(m: dict, extra=None):
    body = text_of(m)
    return Div(
        Span(body, cls="bubble") if body else None,
        extra,
        cls=f"row {m['type']}",
    )


async def transcript():
    if session["thread"] is None:
        return Div(id="transcript")
    state = (await cli.threads.get_state(session["thread"]))["values"]
    messages = [
        m for m in state.get("messages", []) if m.get("type") in ("human", "ai")
    ]
    rows = [
        row(m, Div(*chips_of([m]), cls="chips") if m.get("tool_calls") else None)
        for m in messages
        if (text_of(m) or m.get("tool_calls")) and not text_of(m).startswith(NUDGE)
    ]
    cards = [await crew(t) for t in state.get("async_tasks", {}).values()]
    return Div(*rows, Div(*cards, cls="chips"), id="transcript")


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


app, rt = fast_app(pico=True, hdrs=(Style(CSS),))


@rt("/")
async def index():
    return Titled(
        "async subagents on langgraph",
        Main(await transcript(), composer()),
        Script(STREAM),
    )


@rt("/events")
async def events():
    async def stream():
        while True:
            yield sse_message(await transcript())
            await asyncio.sleep(TICK)

    return EventStream(stream())


@rt("/say")
async def say(msg: str = ""):
    if not msg.strip():
        return ""
    if session["thread"] is None:
        session["thread"] = (await cli.threads.create())["thread_id"]
    # the person speaks while a run may still be going, so turns queue rather than clash
    await cli.runs.create(
        session["thread"],
        "supervisor",
        input={"messages": [{"role": "user", "content": msg.strip()}]},
        multitask_strategy="enqueue",
    )
    return ""


if __name__ == "__main__":
    serve()
