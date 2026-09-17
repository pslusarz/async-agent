import asyncio
from dataclasses import dataclass, field
from typing import Callable

from ..bedrock import MODEL, async_client
from .board import Post, Thread
from .tools import Tool

STOP = object()


@dataclass
class Task:
    id: int
    cancel: asyncio.Event = field(default_factory=asyncio.Event)
    tail: Callable | None = None
    runner: asyncio.Task | None = None
    done: bool = False


class Agent:
    def __init__(self, sp: str = "", model: str = MODEL, tools: list[Tool] = ()):
        self.cli = async_client(model)
        self.sp = sp
        self.thread = Thread()
        self.tools = {t.name: t for t in tools}
        self.schemas = [t.schema for t in tools]
        self.plain_schemas = [t.schema for t in tools if not t.meta]
        self.tasks: dict[int, Task] = {}
        self.inbox: asyncio.Queue = asyncio.Queue()
        self._subs: list[asyncio.Queue] = []
        self._waiters: dict[int, asyncio.Future] = {}
        self._answers: dict[int, Post] = {}
        self._running: set[asyncio.Task] = set()
        self._task: asyncio.Task | None = None

    async def __aenter__(self):
        self.start()
        return self

    async def __aexit__(self, *exc):
        await self.stop()

    def start(self):
        self._task = asyncio.create_task(self._run())

    async def stop(self):
        self.inbox.put_nowait(STOP)
        if self._task:
            await self._task

    def send(self, text: str) -> Post:
        p = self.thread.post("user", text)
        self.inbox.put_nowait(p.id)
        return p

    async def ask(self, text: str, timeout: float = 60) -> Post:
        return await self.reply(self.send(text), timeout)

    async def reply(self, p: Post, timeout: float = 60) -> Post:
        if p.id in self._answers:
            return self._answers.pop(p.id)
        fut = asyncio.get_running_loop().create_future()
        self._waiters[p.id] = fut
        return await asyncio.wait_for(fut, timeout)

    def spawn(self, coro):
        t = asyncio.create_task(coro)
        self._running.add(t)
        t.add_done_callback(self._running.discard)
        return t

    def watch(self, task: int, tailer):
        self.tasks[task].tail = tailer

    def _finish(self, t: Task, result: str):
        t.done = True
        p = self.thread[t.id]
        p.text = result
        p.meta["done"] = True
        self.emit(p)

    async def complete(self, task: int, result: str):
        t = self.tasks[task]
        if t.done:
            return
        self._finish(t, result)
        self.inbox.put_nowait(task)

    async def kill(self, task: int):
        t = self.tasks[task]
        if t.done:
            return
        t.cancel.set()
        if t.runner:
            t.runner.cancel()
        self._finish(t, "killed")

    async def stream(self):
        q: asyncio.Queue = asyncio.Queue()
        self._subs.append(q)
        try:
            while (ev := await q.get()) is not STOP:
                yield ev
        finally:
            self._subs.remove(q)

    def emit(self, p: Post):
        for q in self._subs:
            q.put_nowait(p)
        if p.kind not in ("assistant", "error") or p.meta.get("interim"):
            return
        root = self.thread.root_of(p.parent)
        fut = self._waiters.pop(root, None)
        if fut and not fut.done():
            fut.set_result(p)
        else:
            self._answers[root] = p

    def _dispatch(self, call, parent: int) -> Post:
        res = self.thread.post("tool_result", parent=parent, use_id=call.id, done=False)
        res.text = f"started task {res.id}"
        t = Task(res.id)
        self.tasks[res.id] = t
        t.runner = self.spawn(self.tools[call.name].fn(self, res.id, **call.input))
        self.emit(res)
        return res

    async def _turn(self, pid: int):
        # a turn woken by a finished task needs a user-role message to answer
        if self.thread.last_role() == "assistant":
            self.emit(self.thread.post("note", f"task {pid} finished"))
        probed = False
        for _ in range(8):
            schemas = self.plain_schemas if probed else self.schemas
            r = await self.cli(self.thread.render(), sp=self.sp, tools=schemas)
            text = "\n".join(b.text for b in r.content if b.type == "text")
            calls = [b for b in r.content if b.type == "tool_use"]
            if not calls:
                self.emit(self.thread.post("assistant", text, parent=pid))
                return
            metas = [c for c in calls if self.tools[c.name].meta]
            if metas:
                # meta calls stay out of history; only the posts they make survive
                for c in metas:
                    await self.tools[c.name].fn(self, **c.input)
                probed = True
                continue
            if text:
                self.emit(self.thread.post("assistant", text, parent=pid, interim=True))
            for c in calls:
                call = self.thread.post("tool_call", parent=pid, use_id=c.id, name=c.name, input=c.input)
                self.emit(call)
                self._dispatch(c, call.id)
            return

    async def _run(self):
        while (pid := await self.inbox.get()) is not STOP:
            try:
                await self._turn(pid)
            except Exception as e:
                self.emit(Post("error", f"{type(e).__name__}: {e}", parent=pid))
        for q in self._subs:
            q.put_nowait(STOP)
