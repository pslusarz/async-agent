import time
from dataclasses import dataclass, field
from itertools import count

_ids = count(1)


@dataclass
class Post:
    kind: str
    text: str = ""
    parent: int | None = None
    id: int = field(default_factory=lambda: next(_ids))
    at: float = field(default_factory=time.time)
    children: list[int] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    @property
    def role(self) -> str:
        return "assistant" if self.kind in ("assistant", "tool_call") else "user"

    def blocks(self) -> list[dict]:
        if self.kind == "tool_call":
            return [dict(type="tool_use", id=self.meta["use_id"], name=self.meta["name"], input=self.meta["input"])]
        if self.kind == "tool_result":
            return [dict(type="tool_result", tool_use_id=self.meta["use_id"], content=self.text)]
        return [dict(type="text", text=self.text)]


class Thread:
    def __init__(self):
        self.posts: dict[int, Post] = {}
        # per thread, so a scenario renders the same ids on every run
        self._ids = count(1)

    def __getitem__(self, pid: int) -> Post:
        return self.posts[pid]

    def post(self, kind: str, text: str = "", parent: int | None = None, **meta) -> Post:
        p = Post(kind, text, parent=parent, meta=meta)
        p.id = next(self._ids)
        self.posts[p.id] = p
        if parent is not None:
            self.posts[parent].children.append(p.id)
        return p

    def root_of(self, pid: int) -> int:
        p = self.posts[pid]
        while p.parent is not None:
            p = self.posts[p.parent]
        return p.id

    def walk(self):
        def below(p):
            yield p
            for cid in p.children:
                yield from below(self.posts[cid])

        for p in self.posts.values():
            if p.parent is None:
                yield from below(p)

    def last_role(self) -> str | None:
        role = None
        for p in self.walk():
            role = p.role
        return role

    def render(self) -> list[dict]:
        msgs: list[dict] = []
        for p in self.walk():
            if msgs and msgs[-1]["role"] == p.role:
                msgs[-1]["content"] += p.blocks()
            else:
                msgs.append(dict(role=p.role, content=p.blocks()))
        return msgs
