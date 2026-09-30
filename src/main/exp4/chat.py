import asyncio
import threading
from dataclasses import dataclass

from .loop import Event, Session, options


@dataclass
class Entry:
    role: str
    text: str
    at: float


class Chat:
    """A plain linear transcript over a Session, driven from ordinary sync code.

    The SDK tags a turn that a finished task drove, but not which question that
    task was answering, so the link is kept here: a task id leads back to the
    Agent call that started it, and from there to the question that was on the
    table at the time.
    """

    def __init__(self, opts=None, timeout: float = 60):
        self._opts = opts or options()
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._session: Session | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            raise TimeoutError("session never came up")

    def _run(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._serve())

    async def _serve(self):
        async with Session(self._opts) as s:
            self._session = s
            self._ready.set()
            while not self._stop.is_set():
                await asyncio.sleep(0.05)

    def say(self, text: str):
        asyncio.run_coroutine_threadsafe(self._session.say(text), self._loop).result(10)

    def close(self):
        self._stop.set()
        self._thread.join(15)

    @property
    def events(self) -> list[Event]:
        return list(self._session.events)

    def entries(self) -> list[Entry]:
        events = self.events
        out: list[Entry] = []
        pending: list[Event] = []

        for e in events:
            if e.kind == "user":
                out.append(Entry("user", e.text, e.at))
            elif e.kind == "said" and e.parent is None:
                pending.append(e)
            elif e.kind == "turn":
                out.extend(self._flush(events, pending, e))
                pending = []

        out.extend(Entry("agent", s.text, s.at) for s in pending)
        return out

    def _flush(self, events, said, turn):
        q = self._question_of(events, turn)
        current = self._latest_question(events, turn.at)
        late = q is not None and q is not current
        for s in said:
            text = (
                f"Regarding your earlier question, {q.text!r}: {s.text}"
                if late
                else s.text
            )
            yield Entry("agent", text, s.at)

    @staticmethod
    def _latest_question(events, at: float) -> Event | None:
        asked = [e for e in events if e.kind == "user" and e.at <= at]
        return asked[-1] if asked else None

    def _question_of(self, events, turn) -> Event | None:
        if (turn.origin or {}).get("kind") != "task-notification":
            return None
        landed = [e for e in events if e.kind == "TaskNotification" and e.at <= turn.at]
        if not landed:
            return None
        started = [
            e for e in events if e.kind == "TaskStarted" and e.task == landed[-1].task
        ]
        if not started:
            return None
        return self._latest_question(events, started[0].at)
