import queue
import threading
from dataclasses import dataclass

from ..bedrock import MODEL, raw_client
from .board import Board, Call, Msg
from .run import Runner
from .tools import Tool

BOARD_SP = (
    "You are reading a threaded message board. Every message is prefixed with its place "
    "in the tree, its id and who wrote it, like '|   +-- [#5] [assistant]'. Those "
    "prefixes are structure, not part of what was said. Reply in plain prose: no prefix, "
    "no id, no writer tag, no tree characters. Task ids are "
    "bookkeeping between you and the board: never quote one to the person you are talking "
    "to. Do tell them what a task reported, including progress and percentages, and say "
    "so in your own words as work you are doing rather than by naming the task."
)
STOP = object()


@dataclass
class Event:
    kind: str
    mid: int
    payload: str = ""


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
        self.tasks: dict[int, Runner] = {}
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

    def wait_for(
        self, target: str | Msg, parent: int | None = None, timeout: float = 60
    ) -> Msg:
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

    def wait_for_task(self, q: Msg, timeout: float = 30) -> Call:
        """Block until the agent answers `q` by starting a task, and return that node."""
        with self._cv:
            ok = self._cv.wait_for(lambda: self._task_of(q) is not None, timeout)
        if not ok:
            raise TimeoutError(f"no task started for #{q.id}")
        return self._task_of(q)

    def _task_of(self, q: Msg) -> Call | None:
        return next(
            (
                c
                for m in self.board.walk(q.id)
                for c in m.calls
                if not self.tools[c.tool].meta
            ),
            None,
        )

    def _changed(self):
        with self._cv:
            self._cv.notify_all()

    def _on_done(self, r: Runner):
        self.events.put(Event("result", r.id, payload=r.future.result()))

    def kill(self, call: int):
        r = self.tasks.get(call)
        if r is None or r.killed:
            return
        r.kill()
        with self._cv:
            self.board.kill(call)
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

    def _take_turn(
        self, mid: int, focus: int | None = None, note: str | None = None
    ) -> Msg | None:
        probed = False
        for _ in range(4):
            schemas = self.plain_schemas if probed else self.schemas
            r = self._call(focus if focus is not None else mid, schemas, note)
            calls = [b for b in r.content if b.type == "tool_use"]
            text = "".join(b.text for b in r.content if b.type == "text")
            if not calls:
                return self.board.post("assistant", text, parent=mid)
            metas = [c for c in calls if self.tools[c.name].meta]
            if metas:
                # a meta call is a tool that returned at once, so it is recorded as one
                node = self.board.post("assistant", text, parent=mid)
                for c in metas:
                    call = self.board.add_call(node.id, c.name, c.input)
                    self.board.set_result(
                        call.id, self.tools[c.name].fn(self, **c.input)
                    )
                mid = node.id
                probed = True
                continue
            # one node per assistant turn, holding every call it made at once
            node = self.board.post("assistant", text, parent=mid)
            started = [
                self.board.add_call(node.id, c.name, c.input, actions=self.meta_names)
                for c in calls
            ]
            for call in started:
                self.tasks[call.id] = Runner(
                    call.id, self.tools[call.tool].fn(**call.args), self._on_done
                )
            self._changed()
            for call in started:
                self.tasks[call.id].start()
            return node
        return None

    def _result(self, ev: Event):
        r = self.tasks.get(ev.mid)
        # a killed task stays killed, so anything it settles with afterwards is dropped
        if r and r.killed:
            return
        with self._cv:
            self.board.set_result(ev.mid, ev.payload)
            self._cv.notify_all()
        node = self.board[self.board.calls[ev.mid].msg]
        # the agent only gets its turn once every placeholder in the node is filled
        if node.terminal:
            self._maybe_continue(node.id)
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
