import asyncio
import os
import secrets
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from fasthtml.common import (
    H2,
    H3,
    A,
    Button,
    Div,
    EventStream,
    Img,
    Input,
    Li,
    Main,
    P,
    Pre,
    Redirect,
    Script,
    Span,
    Style,
    Titled,
    Ul,
    fast_app,
    serve,
    sse_message,
)

from .demo import Demo
from .scenarios import BY_KEY, SCENARIOS

REPO = "https://github.com/pslusarz/async-agent"
POST = "https://pslusarz.github.io/articles/2026/10/01/an-agent-you-can-interrupt.html"
SHOT = "/demo.png"
# a stream is recycled rather than held open forever; the browser reconnects itself
STREAM_TTL = 300.0

CSS = """
body { max-width:none; }
main { max-width:76rem; margin:0 auto; }
#stage { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,25rem); gap:1.5rem; align-items:start; }
.bar { grid-column:1/-1; display:flex; align-items:center; gap:.5rem; flex-wrap:wrap; border:1px solid #d0d7de; border-radius:.5rem; padding:.6rem .8rem; }
.bar button { width:auto; margin:0; padding:.3rem .9rem; font-size:.85rem; }
.bar .on { background:#1f6feb; border-color:#1f6feb; }
.bar .cue { margin-left:auto; font-size:.8rem; color:#57606a; font-family:monospace; }
#transcript { display:flex; flex-direction:column; gap:.6rem; margin-bottom:1rem; }
.row { display:flex; align-items:center; gap:.5rem; }
.row.user { justify-content:flex-end; }
.bubble { max-width:40rem; padding:.55rem .85rem; border-radius:1rem; white-space:pre-wrap; }
.user .bubble { background:#1f6feb; color:#fff; border-bottom-right-radius:.25rem; }
.agent .bubble { background:#f1f3f5; color:#111; border-bottom-left-radius:.25rem; }
.composer input { pointer-events:none; }
.chips { display:flex; align-items:center; gap:.4rem; flex-wrap:wrap; }
.task { display:inline-flex; align-items:center; gap:.35rem; border:1px solid #d0d7de; border-radius:1rem; padding:.2rem .65rem; font-size:.78rem; }
.task .name { font-weight:600; }
.task .args { color:#57606a; }
.dot { width:.7rem; height:.7rem; border-radius:50%; flex:none; }
.dot.done { background:#2da44e; }
.dot.failed { background:#cf222e; }
.spinner { width:.8rem; height:.8rem; flex:none; border:2px solid #d0d7de; border-top-color:#1f6feb; border-radius:50%; animation:spin .8s linear infinite; }
@keyframes spin { to { transform:rotate(360deg); } }
.side h3 { font-size:.8rem; text-transform:uppercase; letter-spacing:.06em; color:#57606a; margin:0 0 .4rem; }
.side > div { margin-bottom:1.2rem; }
.side pre { font-size:.72rem; line-height:1.45; white-space:pre-wrap; overflow-wrap:anywhere; background:#f6f8fa; padding:.6rem; margin:0; max-height:22rem; overflow-y:auto; }
.card { border:1px solid #d0d7de; border-radius:.4rem; padding:.45rem .6rem; margin-bottom:.4rem; font-size:.78rem; }
.card .head { display:flex; gap:.4rem; align-items:center; margin-bottom:.3rem; }
.card .st { margin-left:auto; font-size:.7rem; padding:0 .4rem; border-radius:.6rem; background:#eaeef2; }
.card .st.running { background:#ddf4ff; }
.card .st.done { background:#dafbe1; }
.card .st.killed { background:#ffebe9; }
.shot { border:1px solid #d0d7de; border-radius:.5rem; width:100%; height:auto; display:block; }
.pick { border:1px solid #d0d7de; border-radius:.5rem; padding:.8rem 1rem; margin-bottom:.8rem; }
.pick h3 { margin:0 0 .3rem; }
.pick p { margin:0 0 .6rem; color:#57606a; font-size:.9rem; }
@media (max-width:70rem) { #stage { grid-template-columns:minmax(0,1fr); } }
"""

STREAM = """
const es = new EventSource(STREAM_URL);
es.onmessage = e => {
  document.getElementById('stage').outerHTML = e.data;
  htmx.process(document.getElementById('stage'));
};
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


def composer(demo):
    return Div(
        Input(value=demo.typing, placeholder="the demo types here...", readonly=True),
        cls="composer",
    )


def controls(demo, key: str):
    d = demo.director
    cue = "scenario over" if demo.over and not d.queue else (d.next_up or "waiting...")
    return Div(
        Button(
            "Play",
            cls="on" if d.mode == "play" else "secondary",
            hx_post=f"/s/{key}/play",
            hx_swap="none",
        ),
        Button(
            "Pause",
            cls="on" if d.mode == "pause" else "secondary",
            hx_post=f"/s/{key}/pause",
            hx_swap="none",
        ),
        Button("Step", cls="secondary", hx_post=f"/s/{key}/step", hx_swap="none"),
        Button("Restart", cls="contrast", hx_post=f"/s/{key}/restart", hx_swap="none"),
        Span(f"next: {cue}", cls="cue"),
        cls="bar",
    )


def board_lines(agent) -> str:
    b = agent.board
    return (
        "\n".join(b.line(m) for root in b.threads() for m in b.walk(root.id))
        or "(nothing posted yet)"
    )


def task_card(agent, cid: int):
    r = agent.tasks[cid]
    call = agent.board.calls[cid]
    state = "killed" if r.killed else ("done" if r.future.done() else "running")
    return Div(
        Div(
            Span(f"#{cid} {call.sig}", cls="name"),
            Span(state, cls=f"st {state}"),
            cls="head",
        ),
        Pre(r.tail(3)),
        cls="card",
    )


def sidebar(demo):
    cards = [task_card(demo.agent, cid) for cid in demo.agent.tasks]
    return Div(
        Div(H3("the board, as the model sees it"), Pre(board_lines(demo.agent))),
        Div(H3("tasks"), *(cards or [P("none yet")])),
        Div(
            H3("beats played"), Pre("\n".join(demo.director.history[-12:]) or "(none)")
        ),
        cls="side",
    )


def stage(demo, key: str):
    return Div(
        controls(demo, key),
        Div(
            Div(*[row(demo.chat, e) for e in demo.chat.entries()], id="transcript"),
            composer(demo),
        ),
        sidebar(demo),
        id="stage",
    )


class Stage:
    """One viewer's run of one scenario, plus whoever is currently watching it."""

    def __init__(self, scenario):
        self.scenario = scenario
        self.touched = time.monotonic()
        self._watchers: set = set()
        self._lock = threading.Lock()
        self.demo = Demo(scenario, on_change=self.bump).start()

    @property
    def watched(self) -> bool:
        with self._lock:
            return bool(self._watchers)

    def bump(self):
        with self._lock:
            watching = list(self._watchers)
        for wake in watching:
            wake()

    @contextmanager
    def watch(self, wake):
        with self._lock:
            self._watchers.add(wake)
        try:
            yield
        finally:
            with self._lock:
                self._watchers.discard(wake)
            self.touched = time.monotonic()

    def restart(self):
        old = self.demo
        self.demo = Demo(self.scenario, on_change=self.bump).start()
        self.bump()
        old.stop()

    def stop(self):
        self.demo.stop()


class Stages:
    """One run per browser session per scenario, reaped once nobody is looking."""

    TTL = 15 * 60
    MAX = 200

    def __init__(self):
        self._by: dict[tuple[str, str], Stage] = {}
        self._lock = threading.Lock()

    def get(self, sid: str, key: str) -> Stage:
        with self._lock:
            gone = self._cull()
            st = self._by.get((sid, key))
            if st is None:
                st = self._by[(sid, key)] = Stage(BY_KEY[key])
            st.touched = time.monotonic()
        # outside the lock: winding a run down joins its threads
        for s in gone:
            s.stop()
        return st

    def _cull(self) -> list[Stage]:
        now = time.monotonic()
        idle = sorted(
            (k for k, s in self._by.items() if not s.watched),
            key=lambda k: self._by[k].touched,
        )
        over = max(0, len(self._by) - self.MAX)
        drop = set(idle[:over])
        drop |= {k for k in idle if now - self._by[k].touched > self.TTL}
        return [self._by.pop(k) for k in drop]


def sid_of(session) -> str:
    if "sid" not in session:
        session["sid"] = secrets.token_urlsafe(12)
    return session["sid"]


def landing():
    return Main(
        P(
            "A harness where the agent keeps talking to you while its tools are still "
            "running. Tool calls do not block the conversation: they become tasks the "
            "agent can look in on, report about, and be asked to abandon."
        ),
        P(
            "Everything here is canned. No model is called, so the same thing happens "
            "every time and nobody's bill moves. What is real is the harness: the same "
            "board, the same background tasks and the same widgets the live version "
            "uses. The panel on the right shows the board the model would have been "
            "handed on each turn."
        ),
        P(
            "Use ",
            Span("Play", cls="name"),
            " to watch it in real time, ",
            Span("Pause", cls="name"),
            " to stop the clock for everything at once, and ",
            Span("Step", cls="name"),
            " to advance one beat at a time.",
        ),
        Img(src=SHOT, cls="shot", alt="the demo running three tool calls at once"),
        H2("Scenarios"),
        *[
            Div(
                H3(A(s.title, href=f"/s/{s.key}")),
                P(s.blurb),
                A("Run it", href=f"/s/{s.key}", role="button"),
                cls="pick",
            )
            for s in SCENARIOS
        ],
        H2("More"),
        Ul(
            Li(A("Read the write-up", href=POST)),
            Li(A("Source on GitHub", href=REPO)),
        ),
    )


def make_app(stages: Stages):
    here = Path(__file__).parent
    app, rt = fast_app(
        pico=True,
        hdrs=(Style(CSS),),
        static_path=str(here / "static"),
        secret_key=os.getenv("DEMO_SECRET_KEY"),
    )

    def pick(key: str, session) -> Stage | None:
        return stages.get(sid_of(session), key) if key in BY_KEY else None

    @rt("/")
    def index():
        return Titled("Towards a responsive agentic behavior", landing())

    @rt("/s/{key}")
    def scenario(key: str, session):
        st = pick(key, session)
        if st is None:
            return Redirect("/")
        return Titled(
            st.scenario.title,
            Main(
                P(A("< all scenarios", href="/")),
                P(st.scenario.blurb),
                stage(st.demo, key),
            ),
            Script(f'const STREAM_URL = "/s/{key}/events";' + STREAM),
        )

    @rt("/s/{key}/events")
    async def events(key: str, session):
        st = pick(key, session)
        if st is None:
            return Redirect("/")

        async def stream():
            loop = asyncio.get_running_loop()
            moved = asyncio.Event()

            def wake():
                try:
                    loop.call_soon_threadsafe(moved.set)
                except RuntimeError:
                    pass  # the loop has gone; this viewer is already leaving

            # watching rather than polling, so a viewer who closes the tab parks
            # no thread and is let go as soon as the generator is cancelled
            with st.watch(wake):
                yield sse_message(stage(st.demo, key))
                ends = time.monotonic() + STREAM_TTL
                while (left := ends - time.monotonic()) > 0:
                    try:
                        await asyncio.wait_for(moved.wait(), left)
                    except TimeoutError:
                        break  # EventSource reconnects on its own and re-renders
                    moved.clear()
                    yield sse_message(stage(st.demo, key))

        return EventStream(stream())

    @rt("/s/{key}/play")
    def play(key: str, session):
        if st := pick(key, session):
            st.demo.director.play()
        return ""

    @rt("/s/{key}/pause")
    def pause(key: str, session):
        if st := pick(key, session):
            st.demo.director.pause()
        return ""

    @rt("/s/{key}/step")
    def step(key: str, session):
        if st := pick(key, session):
            st.demo.director.step()
        return ""

    @rt("/s/{key}/restart")
    def restart(key: str, session):
        if st := pick(key, session):
            st.restart()
        return ""

    return app


stages = Stages()
app = make_app(stages)

if __name__ == "__main__":
    serve()
