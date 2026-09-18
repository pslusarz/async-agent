from dataclasses import dataclass


@dataclass
class Entry:
    role: str
    text: str
    at: float


class Chat:
    """A plain linear transcript over the board.

    The board is a tree and answers can arrive long after the conversation moved on.
    Here it is just a conversation: one line after another, where the agent sometimes
    speaks unprompted. A late answer says which question it belongs to in its own
    words; nothing about tasks, threads or progress is exposed. Ask the agent if you
    want to know how a tool is doing.
    """

    def __init__(self, agent):
        self.agent = agent
        self._root: int | None = None

    def say(self, text: str):
        m = self.agent.post(text, parent=self._tail())
        if self._root is None:
            self._root = m.id

    def entries(self) -> list[Entry]:
        b = self.agent.board
        if self._root is None:
            return []
        said = [m for m in b.walk(self._root) if m.role == "user" or m.text]
        said.sort(key=lambda m: m.at)

        out, asked = [], None
        for m in said:
            if m.role == "user":
                asked = m
                out.append(Entry("user", m.text, m.at))
                continue
            q = self._question_of(m.id)
            late = q is not None and (asked is None or q.id != asked.id)
            text = f"Regarding your earlier question, {q.text!r}: {m.text}" if late else m.text
            out.append(Entry("agent", text, m.at))
        return out

    def _tail(self) -> int | None:
        # follow-ups hang off the newest node, which is the task node while one runs
        return None if self._root is None else self.agent.board.walk(self._root)[-1].id

    def _question_of(self, mid: int):
        b = self.agent.board
        m = b[mid]
        while m.parent is not None:
            m = b[m.parent]
            if m.role == "user":
                return m
        return None
