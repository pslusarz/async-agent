import copy
import queue
import threading

from ..bedrock import MODEL, raw_client
from ..exp2.agent import BOARD_SP, STOP, Event
from ..exp2.board import Board, Call, Msg
from ..exp2.run import Runner
from ..exp2.tools import Tool

TIMEOUT_ARG = dict(
    type="number",
    description=(
        "How long you expect this call to take, in seconds: the interval after which "
        "you would consider the result overdue."
    ),
)
DEFAULT_TIMEOUT = 30.0
KILLED = "killed"
# a turn is a ReAct loop; this only stops a runaway, it does not ration anything
MAX_STEPS = 6
# a tool that has already had the last word, so the turn is over once it returns
ENDS_TURN = ("new_thread",)


def overdue(cid: int, seconds: float) -> str:
    """The harness nudging the agent about a task that outlived its expected interval."""
    return (
        f"Task #{cid} has not finished within the {seconds:g}s you expected of it. "
        f"Look at how it is doing with tail(task={cid}), then decide: if it is still "
        f"making progress, leave it running and say so; if it cannot make progress, "
        f"stop it with kill(task={cid}) and carry on from there."
    )


def gave_up(tool: str, n: int) -> str:
    return (
        f"{KILLED}. {tool} has now been killed {n} time{'s' if n > 1 else ''} over this "
        "request and is not going to work. There is nothing further to try in this "
        "thread. Use new_thread to say what you were trying to find out, that the tool "
        "keeps failing, and ask how they would like to proceed."
    )


def ask_instead(tool: str) -> str:
    """Said last, where the fallback 'Respond to [#n]' would otherwise contradict it."""
    return (
        f"This thread is finished: {tool} has been killed too many times to try again, "
        "so do not reply here. Call new_thread now, and in its text say what you were "
        "trying to find out, that the tool keeps failing, and ask how they would like "
        "to proceed."
    )


def how_to_call(names: tuple[str, ...]) -> str:
    """Told to the agent because only the harness knows which tools outlive a turn."""
    listed = ", ".join(names)
    return (
        f"Two kinds of tool are available to you. {listed} are synchronous: they answer "
        "at once, and calling one does not end your turn - you are given another turn "
        "immediately, with the result in front of you. Every other tool runs in the "
        "background: calling one starts work that outlives this turn and hands you a "
        "task id rather than a result.\n"
        "Do not mix the two in one turn. A turn that calls a synchronous tool starts no "
        "background work, so anything you ask to run alongside it will not be started. "
        "Call the synchronous tool on its own, read what it says on the turn you are "
        "given straight after, and start the background work then. Calling more than "
        "one synchronous tool at a time is allowed, but one at a time reads better."
    )


def not_started(names: list[str]) -> str:
    listed = ", ".join(names)
    was = "was" if len(names) == 1 else "were"
    return (
        f"The result above is from the synchronous tool you just called. {listed} "
        f"{was} not started, because a turn that calls a synchronous tool starts no "
        "background work. Start it now if you still want it."
    )


# A turn is triggered by the user, by a result landing, or by a timer, and each node it
# posts either calls a synchronous tool, starts background work, or is the turn's last
# word. Only some of those nine combinations are worth showing the reader; the rest stay
# on the board as the agent's own context. A node that exists to carry a synchronous
# call is never shown, because the turn's last word already reports what it found; a
# node that starts work after a result is not shown either, because the agent is not
# ready to answer yet.
SPEAKS = {("user", "work"), ("user", "word"), ("result", "word")}


def speaks(trigger: str, did: str) -> bool:
    return (trigger, did) in SPEAKS


def with_timeout(schema: dict) -> dict:
    s = copy.deepcopy(schema)
    s["input_schema"]["properties"]["timeout"] = TIMEOUT_ARG
    s["input_schema"]["required"] = [*s["input_schema"].get("required", ()), "timeout"]
    return s


class Agent:
    def __init__(
        self,
        sp: str = "",
        model: str = MODEL,
        tools: list[Tool] = (),
        maxtok: int = 1024,
        max_auto: int = 4,
        max_retries: int = 2,
        timeout_cap: float = 60.0,
    ):
        self.cli = self._client()
        self.model = model
        self.maxtok = maxtok
        self.max_auto = max_auto
        self.max_retries = max_retries
        self.timeout_cap = timeout_cap
        self.sp = f"{BOARD_SP}\n\n{sp}" if sp else BOARD_SP
        self.board = Board()
        self.tools = {t.name: t for t in tools}
        self.schemas = [
            t.schema if t.synchronous else with_timeout(t.schema) for t in tools
        ]
        if names := tuple(t.name for t in tools if t.synchronous):
            self.sp = f"{self.sp}\n\n{how_to_call(names)}"
        self.tasks: dict[int, Runner] = {}
        self.timers: dict[int, threading.Timer] = {}
        self.nudged: dict[int, int] = {}
        self.seen: dict[int, str] = {}
        self.events: queue.Queue = queue.Queue()
        self.errors: list[Exception] = []
        self._ask: str | None = None
        self._auto: dict[int, int] = {}
        self._cv = threading.Condition()
        self._loop = threading.Thread(target=self._run, daemon=True)
        self._loop.start()

    def _client(self):
        return raw_client()

    def post(self, text: str, parent: int | None = None) -> Msg:
        m = self.board.post("user", text, parent=parent)
        self.events.put(Event("user", m.id))
        return m

    def wait_for(
        self, target: str | Msg, parent: int | None = None, timeout: float = 60
    ) -> Msg:
        if isinstance(target, str):
            target = self.post(target, parent)
        with self._cv:
            ok = self._cv.wait_for(lambda: self.board.answered(target.id), timeout)
        if not ok:
            raise TimeoutError(f"no reply to #{target.id}")
        return self.board.answer_of(target.id)

    def wait_for_task(self, q: Msg, timeout: float = 30) -> Call:
        with self._cv:
            ok = self._cv.wait_for(lambda: self._task_of(q) is not None, timeout)
        if not ok:
            raise TimeoutError(f"no task started for #{q.id}")
        return self._task_of(q)

    def wait_until(self, pred, timeout: float = 60) -> bool:
        with self._cv:
            return self._cv.wait_for(pred, timeout)

    def _task_of(self, q: Msg) -> Call | None:
        return next(
            (
                c
                for m in self.board.walk(q.id)
                for c in m.calls
                if not self.tools[c.tool].synchronous
            ),
            None,
        )

    def _changed(self):
        with self._cv:
            self._cv.notify_all()

    def _emit(self, kind: str, cid: int):
        # a seam for a watcher to follow one call at a time; nobody listens by default
        pass

    def _on_done(self, r: Runner):
        self.events.put(Event("result", r.id, payload=r.future.result()))

    def kill(self, call: int):
        r = self.tasks.get(call)
        if r is None or r.killed:
            return
        self._disarm(call)
        r.kill()
        with self._cv:
            self.board.kill(call)
            self._cv.notify_all()
        self._emit("settled", call)

    def note_kill(self, cid: int) -> str:
        """Say whether this line of attempts has used up its retries."""
        call = self.board.calls[cid]
        n = self._attempts(cid)
        if n <= self.max_retries:
            return KILLED
        self._ask = ask_instead(call.tool)
        return gave_up(call.tool, n)

    def _attempts(self, cid: int) -> int:
        """How many times this tool has been killed along the branch leading to `cid`.

        Only ancestors count, so calls made side by side - three cities at once -
        are separate lines of attempt and do not spend each other's retries.
        """
        call = self.board.calls[cid]
        n, m = 1, self.board[call.msg]
        while m.parent is not None:
            m = self.board[m.parent]
            n += any(c.tool == call.tool and c.killed for c in m.calls)
        return n

    def stop(self):
        for cid in list(self.timers):
            self._disarm(cid)
        self.events.put(STOP)
        self._loop.join()

    def _arm(self, cid: int, due: float | None):
        seconds = min(float(due or DEFAULT_TIMEOUT), self.timeout_cap)
        t = threading.Timer(seconds, self._fire, args=(cid, seconds))
        t.daemon = True
        self.timers[cid] = t
        t.start()

    def _fire(self, cid: int, seconds: float):
        self.events.put(Event("overdue", cid, payload=repr(seconds)))

    def _disarm(self, cid: int):
        t = self.timers.pop(cid, None)
        if t is not None:
            t.cancel()

    def _run(self):
        while (ev := self.events.get()) is not STOP:
            try:
                if ev.kind == "user":
                    self._turn(ev)
                elif ev.kind == "overdue":
                    self._overdue(ev)
                else:
                    self._result(ev)
            except Exception as e:
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
        self._auto[self.board.root_of(ev.mid)] = 0
        self._take_turn(ev.mid)
        self._changed()

    def _take_turn(
        self,
        mid: int,
        focus: int | None = None,
        note: str | None = None,
        trigger: str = "user",
    ) -> Msg | None:
        for _ in range(MAX_STEPS):
            r = self._call(
                focus if focus is not None else mid, self.schemas, note
            )  # a nudge is spent once read, or it would be repeated after it was acted on
            note = None
            calls = [b for b in r.content if b.type == "tool_use"]
            text = "".join(b.text for b in r.content if b.type == "text")
            if not calls:
                return self.board.post(
                    "assistant", text, parent=mid, aside=not speaks(trigger, "word")
                )
            immediate = [c for c in calls if self.tools[c.name].synchronous]
            if immediate:
                node = self.board.post(
                    "assistant", text, parent=mid, aside=not speaks(trigger, "sync")
                )
                for c in immediate:
                    call = self.board.add_call(node.id, c.name, c.input)
                    self.board.set_result(
                        call.id, self.tools[c.name].fn(self, **c.input)
                    )
                mid = node.id
                self._changed()
                if any(c.name in ENDS_TURN for c in immediate):
                    return node
                deferred = [c.name for c in calls if c not in immediate]
                note = self._ask or (not_started(deferred) if deferred else None)
                self._ask = None
                # present_synchronous_tool_result_to_agent_immediately: the turn does not
                # end, because a result nobody has read is the same as no result at all
                continue
            node = self.board.post(
                "assistant", text, parent=mid, aside=not speaks(trigger, "work")
            )
            started = []
            for c in calls:
                args = dict(c.input)
                due = args.pop("timeout", None)
                # kill is offered by the overdue nudge alone, never by the placeholder
                started.append(
                    (self.board.add_call(node.id, c.name, args, actions=("tail",)), due)
                )
            for call, _ in started:
                self.tasks[call.id] = Runner(
                    call.id, self.tools[call.tool].fn(**call.args), self._on_done
                )
            self._changed()
            for call, due in started:
                self.tasks[call.id].start()
                self._arm(call.id, due)
                self._emit("started", call.id)
            return node
        return None

    def _overdue(self, ev: Event):
        self._disarm(ev.mid)
        r = self.tasks.get(ev.mid)
        if r is None or r.done:
            return
        seconds = float(ev.payload)
        self.nudged[ev.mid] = self.nudged.get(ev.mid, 0) + 1
        self._take_turn(
            self.board.calls[ev.mid].msg,
            note=overdue(ev.mid, seconds),
            trigger="overdue",
        )
        # left running rather than killed, so ask again after the same interval
        if not r.done:
            self._arm(ev.mid, seconds)
        self._changed()

    def _result(self, ev: Event):
        self._disarm(ev.mid)
        r = self.tasks.get(ev.mid)
        if r and r.killed:
            return
        with self._cv:
            self.board.set_result(ev.mid, ev.payload)
            self._cv.notify_all()
        self._emit("settled", ev.mid)
        node = self.board[self.board.calls[ev.mid].msg]
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
            trigger="result",
            note=(
                f"Task #{mid} has finished and its outcome is shown above. "
                f"Answer [#{q}] in words now. Start another task only if you cannot "
                "answer without it, for example when the outcome is an error telling "
                "you how to correct the call, or when it tells you something you must "
                "look up before you can answer."
            ),
        )
