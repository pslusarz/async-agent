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

    Nothing here ties a late answer back to the question it serves. The SDK's
    transcript is linear and complete, so when a task lands the agent can see
    that the conversation moved on and reintroduces the subject itself.
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
        return [
            Entry("user" if e.kind == "user" else "agent", e.text, e.at)
            for e in self.events
            if e.kind == "user" or (e.kind == "said" and e.parent is None)
        ]
