import queue
import threading
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Callable

from ..bedrock import MODEL, raw_client
from .board import Board, Msg
from .tools import Tool

TOOL_PENDING = "Tool called, please follow up for an answer"
BOARD_SP = (
    "You are reading a threaded message board. Every message is prefixed with its place "
    "in the tree, like '|   +-- [#5]'. Those prefixes are structure, not part of what was "
    "said. Reply in plain prose: no prefix, no id, no tree characters."
)
STOP = object()


@dataclass
class Event:
    kind: str
    mid: int
    fut: Future | None = None
    payload: str = ""


@dataclass
class Task:
    id: int
    # threads cannot be force-killed, so cancellation is cooperative
    cancel: threading.Event = field(default_factory=threading.Event)
    tail: Callable | None = None
    done: bool = False


class Agent:
    def __init__(
        self,
        sp: str = "",
        model: str = MODEL,
        tools: list[Tool] = (),
        maxtok: int = 1024,
        auto: bool = False,
        max_auto: int = 4,
    ):
        self.cli = raw_client()
        self.model = model
        self.maxtok = maxtok
        self.auto = auto
        self.max_auto = max_auto
        self.sp = f"{BOARD_SP}\n\n{sp}" if sp else BOARD_SP
        self.board = Board()
        self.tools = {t.name: t for t in tools}
        self.schemas = [t.schema for t in tools]
        self.plain_schemas = [t.schema for t in tools if not t.meta]
        self.meta_names = tuple(t.name for t in tools if t.meta)
        self.tasks: dict[int, Task] = {}
        self.events: queue.Queue = queue.Queue()
        self.errors: list[Exception] = []
        self._auto: dict[int, int] = {}
        self._replies: dict[int, Msg] = {}
        self._cv = threading.Condition()
        self._loop = threading.Thread(target=self._run, daemon=True)
        self._loop.start()

    def post(self, text: str, parent: int | None = None, timeout: float = 60) -> Msg:
        m = self.board.post("user", text, parent=parent)
        fut: Future = Future()
        self.events.put(Event("user", m.id, fut))
        return fut.result(timeout)

    def result(self, node: int, value: str):
        self.events.put(Event("result", node, payload=value))

    def watch(self, node: int, tailer: Callable):
        self.tasks[node].tail = tailer

    def kill(self, node: int):
        t = self.tasks.get(node)
        if t is None or t.done:
            return
        t.done = True
        t.cancel.set()
        with self._cv:
            self.board.kill(node)
            self._cv.notify_all()

    def wait_for(self, node: Msg, timeout: float = 30) -> Msg:
        with self._cv:
            ok = self._cv.wait_for(lambda: self.board[node.id].terminal, timeout)
        if not ok:
            raise TimeoutError(f"no outcome for #{node.id}")
        return self.board[node.id]

    def wait_for_reply(self, node: Msg, timeout: float = 60) -> Msg:
        root = self.board.root_of(node.id)
        with self._cv:
            ok = self._cv.wait_for(lambda: root in self._replies, timeout)
        if not ok:
            raise TimeoutError(f"no unprompted reply in thread #{root}")
        return self._replies.pop(root)

    def stop(self):
        self.events.put(STOP)
        self._loop.join()

    def _run(self):
        while (ev := self.events.get()) is not STOP:
            try:
                if ev.kind == "user":
                    self._turn(ev)
                else:
                    self._result(ev)
            except Exception as e:
                # result events have no future, so errors would vanish otherwise
                self.errors.append(e)
                if ev.fut and not ev.fut.done():
                    ev.fut.set_exception(e)

    def _call(self, focus: int, schemas: list[dict]):
        kw = dict(tools=schemas) if schemas else {}
        return self.cli.messages.create(
            model=self.model,
            max_tokens=self.maxtok,
            system=self.sp,
            messages=self.board.render(focus),
            **kw,
        )

    def _turn(self, ev: Event):
        # a human posting in a thread refills its autonomous budget
        self._auto[self.board.root_of(ev.mid)] = 0
        m = self._take_turn(ev.mid)
        if ev.fut and not ev.fut.done():
            ev.fut.set_result(m)

    def _take_turn(self, mid: int) -> Msg | None:
        probed = False
        for _ in range(4):
            schemas = self.plain_schemas if probed else self.schemas
            r = self._call(mid, schemas)
            calls = [b for b in r.content if b.type == "tool_use"]
            if not calls:
                text = "".join(b.text for b in r.content if b.type == "text")
                return self.board.post("assistant", text, parent=mid)
            metas = [c for c in calls if self.tools[c.name].meta]
            if metas:
                # blocking, and only one round per turn so the agent cannot busy-poll
                for c in metas:
                    self.tools[c.name].fn(self, mid, **c.input)
                probed = True
                continue
            node = self.board.post(
                "assistant",
                TOOL_PENDING,
                parent=mid,
                tool=calls[0].name,
                args=calls[0].input,
                actions=self.meta_names,
            )
            self.tasks[node.id] = Task(node.id)
            for c in calls:
                threading.Thread(
                    target=self.tools[c.name].fn,
                    args=(self, node.id),
                    kwargs=c.input,
                    daemon=True,
                ).start()
            return node
        return None

    def _result(self, ev: Event):
        t = self.tasks.get(ev.mid)
        if t and t.done:
            return
        if t:
            t.done = True
        with self._cv:
            self.board.set_result(ev.mid, ev.payload)
            self._cv.notify_all()
        self._maybe_continue(ev.mid)

    def _maybe_continue(self, mid: int):
        root = self.board.root_of(mid)
        spent = self._auto.get(root, 0)
        if not self.auto or spent >= self.max_auto:
            return
        self._auto[root] = spent + 1
        m = self._take_turn(mid)
        if m is not None and m.tool is None:
            with self._cv:
                self._replies[root] = m
                self._cv.notify_all()
