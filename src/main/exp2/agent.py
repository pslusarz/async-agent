import queue
import threading
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
        max_auto: int = 4,
    ):
        self.cli = raw_client()
        self.model = model
        self.maxtok = maxtok
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
        self._cv = threading.Condition()
        self._loop = threading.Thread(target=self._run, daemon=True)
        self._loop.start()

    def post(self, text: str, parent: int | None = None) -> Msg:
        m = self.board.post("user", text, parent=parent)
        self.events.put(Event("user", m.id))
        return m

    def wait_for(self, target: str | Msg, parent: int | None = None, timeout: float = 60) -> Msg:
        """Block until the agent has answered `target` in words, and return that answer.

        A string is posted first, so wait_for("...") is post() followed by wait_for(msg).
        """
        if isinstance(target, str):
            target = self.post(target, parent)
        with self._cv:
            ok = self._cv.wait_for(lambda: self.board.answered(target.id), timeout)
        if not ok:
            raise TimeoutError(f"no reply to #{target.id}")
        return self.board.answer_of(target.id)

    def wait_for_task(self, q: Msg, timeout: float = 30) -> Msg:
        """Block until the agent answers `q` by starting a task, and return that node."""
        with self._cv:
            ok = self._cv.wait_for(lambda: self._task_of(q) is not None, timeout)
        if not ok:
            raise TimeoutError(f"no task started for #{q.id}")
        return self._task_of(q)

    def _task_of(self, q: Msg) -> Msg | None:
        return next(
            (m for m in self.board.walk(q.id) if m.tool and not self.tools[m.tool].meta),
            None,
        )

    def _changed(self):
        with self._cv:
            self._cv.notify_all()

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
                # nobody is waiting on this call stack, so errors would vanish otherwise
                self.errors.append(e)

    def _call(self, focus: int, schemas: list[dict], note: str | None = None):
        kw = dict(tools=schemas) if schemas else {}
        return self.cli.messages.create(
            model=self.model,
            max_tokens=self.maxtok,
            system=self.sp,
            messages=self.board.render(focus, note),
            **kw,
        )

    def _turn(self, ev: Event):
        # a human posting in a thread refills its autonomous budget
        self._auto[self.board.root_of(ev.mid)] = 0
        self._take_turn(ev.mid)
        self._changed()

    def _take_turn(self, mid: int, focus: int | None = None, note: str | None = None) -> Msg | None:
        probed = False
        for _ in range(4):
            schemas = self.plain_schemas if probed else self.schemas
            r = self._call(focus if focus is not None else mid, schemas, note)
            calls = [b for b in r.content if b.type == "tool_use"]
            if not calls:
                text = "".join(b.text for b in r.content if b.type == "text")
                return self.board.post("assistant", text, parent=mid)
            metas = [c for c in calls if self.tools[c.name].meta]
            if metas:
                # a meta call is a tool that returned at once, so it is recorded as one
                for c in metas:
                    out = self.tools[c.name].fn(self, **c.input)
                    node = self.board.post(
                        "assistant", out, parent=mid, tool=c.name, args=c.input
                    )
                    self.board.set_result(node.id, out)
                    mid = node.id
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
            with self._cv:
                self._cv.notify_all()
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
        self._changed()

    def _maybe_continue(self, mid: int):
        root = self.board.root_of(mid)
        spent = self._auto.get(root, 0)
        if spent >= self.max_auto:
            return
        self._auto[root] = spent + 1
        q = self.board[mid].parent
        self._take_turn(
            mid,
            focus=q,
            note=(
                f"Task #{mid} has finished and its outcome is shown above. "
                f"Answer [#{q}] in words now. Start another task only if you cannot "
                "answer without it, for example when the outcome is an error telling "
                "you how to correct the call, or when it tells you something you must "
                "look up before you can answer."
            ),
        )
