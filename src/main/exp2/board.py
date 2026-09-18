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
class Call:
    """One tool_use block from an assistant turn."""

    id: int
    tool: str
    args: dict = field(default_factory=dict)
    result: str | None = None
    killed: bool = False
    actions: tuple[str, ...] = ()
    msg: int = 0

    @property
    def terminal(self) -> bool:
        return self.result is not None or self.killed

    @property
    def sig(self) -> str:
        return f"{self.tool}({', '.join(f'{k}={v!r}' for k, v in self.args.items())})"

    @property
    def display(self) -> str:
        if self.killed:
            return f"[{self.sig} was killed before it returned]"
        if self.result is not None:
            return f"[{self.sig} returned: {self.result}]"
        hints = [ACTIONS[a].format(id=self.id) for a in self.actions if a in ACTIONS]
        offer = f" You may {'; '.join(hints)}." if hints else ""
        return (
            f"[{self.sig} is running as task #{self.id}.{offer}"
            " This placeholder will be replaced by the outcome when the task finishes"
            " or is killed.]"
        )


@dataclass
class Msg:
    """One turn: what was said, plus any tool calls made in the same breath."""

    role: str
    text: str = ""
    parent: int | None = None
    id: int = 0
    at: float = field(default_factory=time.time)
    children: list[int] = field(default_factory=list)
    calls: list[Call] = field(default_factory=list)

    @property
    def terminal(self) -> bool:
        return all(c.terminal for c in self.calls)

    @property
    def display(self) -> str:
        parts = ([self.text] if self.text else []) + [c.display for c in self.calls]
        return "\n".join(parts)


class Board:
    def __init__(self):
        self.msgs: dict[int, Msg] = {}
        self.calls: dict[int, Call] = {}
        # per board, so a scenario renders the same ids on every run
        self._ids = count(1)
        self.lock = RWLock()

    def __getitem__(self, mid: int) -> Msg:
        return self.msgs[mid]

    def post(self, role: str, text: str = "", parent: int | None = None) -> Msg:
        with self.lock.write():
            m = Msg(role, text, parent=parent, id=next(self._ids))
            self.msgs[m.id] = m
            if parent is not None:
                self.msgs[parent].children.append(m.id)
            return m

    def add_call(self, mid: int, tool: str, args: dict, actions=()) -> Call:
        with self.lock.write():
            c = Call(next(self._ids), tool, dict(args), actions=tuple(actions), msg=mid)
            self.msgs[mid].calls.append(c)
            self.calls[c.id] = c
            return c

    def set_result(self, cid: int, result: str) -> Call:
        with self.lock.write():
            c = self.calls[cid]
            c.result = result
            return c

    def kill(self, cid: int) -> Call:
        with self.lock.write():
            c = self.calls[cid]
            c.killed = True
            return c

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

    def answered(self, mid: int) -> bool:
        # TODO: this demands a reply directly beneath a finished task, but replies land
        # where the conversation put them - see "Known gaps" in .github/copilot-instructions.md
        with self.lock.read():
            m = self.msgs[mid]
            if m.role == "assistant" and not m.calls:
                return True
            if not m.terminal:
                return False
            # a finished task still owes the reader words about its outcome
            return bool(m.children) and all(self.answered(c) for c in m.children)

    def answer_of(self, mid: int) -> Msg | None:
        with self.lock.read():
            said = [m for m in self.walk(mid) if m.role == "assistant" and not m.calls]
            return said[-1] if said else None

    def depth(self, mid: int) -> int:
        with self.lock.read():
            d, m = 0, self.msgs[mid]
            while m.parent is not None:
                m, d = self.msgs[m.parent], d + 1
            return d

    def line(self, m: Msg) -> str:
        text = m.display
        if m.role == "user" and m.parent is not None:
            ref = [self._ref(c) for c in self.msgs[m.parent].calls]
            if ref:
                text = f"[{'; '.join(ref)}] {text}"
        prefix = "|   " * self.depth(m.id) + "+-- "
        head, *rest = text.split("\n")
        pad = " " * len(prefix)
        return "\n".join([f"{prefix}[#{m.id}] {head}"] + [f"{pad}{r}" for r in rest])

    def _ref(self, c: Call) -> str:
        if c.killed:
            return f"this message is in reference to task #{c.id}, which was killed"
        if c.result is None:
            return f"this message is in reference to task #{c.id} started earlier"
        return f"this message is in reference to task #{c.id}, which already returned: {c.result}"

    def render(self, focus: int | None = None, note: str | None = None) -> list[dict]:
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
                msgs.append(dict(role="user", content=note or f"Respond to [#{focus}]."))
            return msgs
