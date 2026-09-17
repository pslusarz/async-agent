import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from itertools import count

_ids = count(1)


class RWLock:
    """Many concurrent readers, one exclusive writer.

    Writers take priority so a steady stream of readers cannot starve them, and
    nested read() calls on the same thread bypass the gate, which keeps a thread
    already inside a read from deadlocking behind a waiting writer.
    """

    def __init__(self):
        self._cond = threading.Condition()
        self._readers = 0
        self._writing = False
        self._waiting_writers = 0
        self._local = threading.local()

    @contextmanager
    def read(self):
        depth = getattr(self._local, "depth", 0)
        if depth == 0:
            with self._cond:
                while self._writing or self._waiting_writers:
                    self._cond.wait()
                self._readers += 1
        self._local.depth = depth + 1
        try:
            yield
        finally:
            self._local.depth = depth
            if depth == 0:
                with self._cond:
                    self._readers -= 1
                    if self._readers == 0:
                        self._cond.notify_all()

    @contextmanager
    def write(self):
        with self._cond:
            self._waiting_writers += 1
            try:
                while self._writing or self._readers:
                    self._cond.wait()
            finally:
                self._waiting_writers -= 1
            self._writing = True
        try:
            yield
        finally:
            with self._cond:
                self._writing = False
                self._cond.notify_all()


ACTIONS = {
    "tail": "inspect progress with tail(task={id})",
    "kill": "terminate it with kill(task={id})",
}


@dataclass
class Msg:
    role: str
    text: str
    parent: int | None = None
    id: int = field(default_factory=lambda: next(_ids))
    at: float = field(default_factory=time.time)
    children: list[int] = field(default_factory=list)
    result: str | None = None
    tool: str | None = None
    args: dict | None = None
    actions: tuple[str, ...] = ()
    killed: bool = False
    @property
    def call(self) -> str:
        return f"{self.tool}({', '.join(f'{k}={v!r}' for k, v in (self.args or {}).items())})"

    @property
    def terminal(self) -> bool:
        return self.result is not None or self.killed

    @property
    def display(self) -> str:
        # a pending task advertises its id and the meta tools actually registered
        if self.tool is None:
            return self.text
        if self.killed:
            return f"[{self.call} was killed before it returned]"
        if self.result is not None:
            return f"[{self.call} returned: {self.result}]"
        hints = [ACTIONS[a].format(id=self.id) for a in self.actions if a in ACTIONS]
        offer = f" You may {'; '.join(hints)}." if hints else ""
        return (
            f"[{self.call} is running as task #{self.id}.{offer}"
            " This placeholder will be replaced by the outcome when the task finishes"
            " or is killed.]"
        )


class Board:
    def __init__(self):
        self.msgs: dict[int, Msg] = {}
        # per board, so a scenario renders the same ids on every run
        self._ids = count(1)
        self.lock = RWLock()

    def __getitem__(self, mid: int) -> Msg:
        return self.msgs[mid]

    def post(
        self,
        role: str,
        text: str,
        parent: int | None = None,
        tool: str | None = None,
        args: dict | None = None,
        actions: tuple[str, ...] = (),
    ) -> Msg:
        with self.lock.write():
            m = Msg(role, text, parent=parent, tool=tool, args=args, actions=actions)
            m.id = next(self._ids)
            self.msgs[m.id] = m
            if parent is not None:
                self.msgs[parent].children.append(m.id)
            return m

    def set_result(self, mid: int, result: str) -> Msg:
        with self.lock.write():
            m = self.msgs[mid]
            m.result = result
            return m

    def kill(self, mid: int) -> Msg:
        with self.lock.write():
            m = self.msgs[mid]
            m.killed = True
            return m

    def walk(self, mid: int) -> list[Msg]:
        with self.lock.read():
            out: list[Msg] = []

            def rec(m):
                out.append(m)
                for cid in m.children:
                    rec(self.msgs[cid])

            rec(self.msgs[mid])
            return out

    def root_of(self, mid: int) -> int:
        with self.lock.read():
            m = self.msgs[mid]
            while m.parent is not None:
                m = self.msgs[m.parent]
            return m.id

    def threads(self) -> list[Msg]:
        with self.lock.read():
            roots = [m for m in self.msgs.values() if m.parent is None]
            return sorted(roots, key=lambda r: max(m.id for m in self.walk(r.id)))

    def depth(self, mid: int) -> int:
        with self.lock.read():
            d, m = 0, self.msgs[mid]
            while m.parent is not None:
                m, d = self.msgs[m.parent], d + 1
            return d

    def line(self, m: Msg) -> str:
        text = m.display
        if m.role == "user" and m.parent is not None:
            p = self.msgs[m.parent]
            if p.tool is None:
                pass
            elif p.killed:
                text = f"[this message is in reference to task #{p.id}, which was killed] {text}"
            elif p.result is None:
                text = f"[this message is in reference to task #{p.id} started earlier] {text}"
            else:
                text = f"[this message is in reference to task #{p.id}, which already returned: {p.result}] {text}"
        return "|   " * self.depth(m.id) + f"+-- [#{m.id}] {text}"

    def render(self, focus: int | None = None) -> list[dict]:
        with self.lock.read():
            msgs: list[dict] = []
            last = None
            for root in self.threads():
                for m in self.walk(root.id):
                    msgs.append(dict(role=m.role, content=self.line(m)))
                    last = m.id
            # a reply to a branch can leave other branches rendered after it, and a turn
            # driven by a finished task would otherwise end on an assistant message
            if focus is not None and (last != focus or msgs[-1]["role"] != "user"):
                msgs.append(dict(role="user", content=f"Respond to [#{focus}]."))
            return msgs
