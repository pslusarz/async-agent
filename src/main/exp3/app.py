from fasthtml.common import (
    Button,
    Div,
    Form,
    Input,
    Main,
    Script,
    Span,
    Style,
    Titled,
    fast_app,
    serve,
)

from ..exp2.agent import Agent
from ..exp2.chat import Chat
from .tools import TOOLS

SP = (
    "Tools run in the background and take a while. Calling one returns a task id, not "
    "a result. When the user asks how something is going, check on it and tell them."
)

CSS = """
#transcript { display:flex; flex-direction:column; gap:.6rem; margin-bottom:1rem; }
.row { display:flex; }
.row.user { justify-content:flex-end; }
.bubble { max-width:46rem; padding:.55rem .85rem; border-radius:1rem; white-space:pre-wrap; }
.user .bubble { background:#1f6feb; color:#fff; border-bottom-right-radius:.25rem; }
.agent .bubble { background:#f1f3f5; color:#111; border-bottom-left-radius:.25rem; }
form { display:flex; gap:.5rem; }
input[name=msg] { flex:1; padding:.55rem .75rem; }
"""


def bubble(entry):
    return Div(Span(entry.text, cls="bubble"), cls=f"row {entry.role}")


def transcript(chat):
    return Div(
        *[bubble(e) for e in chat.entries()],
        id="transcript",
        hx_get="/messages",
        hx_trigger="every 1s",
        hx_swap="outerHTML",
    )


def composer():
    return Form(
        Input(name="msg", placeholder="Ask something...", autofocus=True, autocomplete="off"),
        Button("Send"),
        hx_post="/say",
        hx_target="#transcript",
        hx_swap="outerHTML",
        hx_on__after_request="this.reset()",
    )


def make_app(chat):
    app, rt = fast_app(pico=True, hdrs=(Style(CSS),))

    @rt("/")
    def index():
        return Titled("async agent", Main(transcript(chat), composer()))

    @rt("/messages")
    def messages():
        return transcript(chat)

    @rt("/say")
    def say(msg: str = ""):
        if msg.strip():
            chat.say(msg.strip())
        return transcript(chat)

    return app


chat = Chat(Agent(sp=SP, tools=TOOLS))
app = make_app(chat)

if __name__ == "__main__":
    serve()
