import threading
import time
from dataclasses import dataclass, field
from itertools import count

_ids = count(1)


# the agent's reply outranks the next scripted question, which outranks tool progress
REPLY = 0
ASK = 1
WORK = 2


@dataclass
class Beat:
    """One scripted move, waiting its turn to happen."""

    label: str
    delay: float
    lane: int = WORK
    id: int = field(default_factory=lambda: next(_ids))


class Director:
    """Lets scripted moves through one at a time, on a timer when playing and on demand when paused.

    Every thread that is about to do something the viewer should see calls gate()
    first, so pausing the demo stops the agent, the tools and the scripted user
    together rather than only the part that happens to be on screen.
    """

    def __init__(self, on_change=None, speed: float = 1.0):
        self.mode = "pause"
        self.speed = speed
        self.on_change = on_change
        self.queue: list[Beat] = []
        self.history: list[str] = []
        self.aborted = False
        self._credits = 0
        self._cv = threading.Condition()

    def play(self):
        self._set(mode="play")

    def pause(self):
        self._set(mode="pause")

    def step(self):
        with self._cv:
            self.mode = "pause"
            # a step with nothing pending is not banked, or it would be spent
            # all at once on whichever beat happens to arrive first
            if self.queue:
                self._credits = 1
            self._cv.notify_all()
        self._changed()

    def abort(self):
        self._set(abort=True)

    @property
    def next_up(self) -> str:
        with self._cv:
            return self.queue[0].label if self.queue else ""

    def wait_played(self, cue: str):
        """Hold until a beat whose label contains `cue` has been let through."""
        with self._cv:
            self._cv.wait_for(
                lambda: self.aborted or any(cue in h for h in self.history)
            )

    def gate(self, label: str, delay: float = 0.0, lane: int = WORK):
        b = Beat(label, delay, lane)
        with self._cv:
            self._place(b)
            self._cv.notify_all()
        self._changed()
        with self._cv:
            until = None
            while not self.aborted:
                if self.queue[0] is not b:
                    until = None
                    self._cv.wait()
                elif self._credits:
                    self._credits -= 1
                    break
                elif self.mode == "play":
                    until = until or time.monotonic() + b.delay / self.speed
                    if (left := until - time.monotonic()) <= 0:
                        break
                    self._cv.wait(left)
                else:
                    until = None
                    self._cv.wait()
            self.queue.remove(b)
            self.history.append(label)
            self._cv.notify_all()
        self._changed()

    def _place(self, b: Beat):
        # what is being said jumps ahead of what is merely grinding away
        i = len(self.queue)
        while i and self.queue[i - 1].lane > b.lane:
            i -= 1
        self.queue.insert(i, b)

    def _set(self, mode: str = "", abort: bool = False):
        with self._cv:
            if mode:
                self.mode = mode
            self.aborted = self.aborted or abort
            self._cv.notify_all()
        self._changed()

    def _changed(self):
        if self.on_change is not None:
            self.on_change()
