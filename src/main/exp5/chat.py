from ..exp2.chat import Chat as Linear


class Chat(Linear):
    """A transcript spanning every thread, since the agent can open one of its own."""

    def _said(self):
        b = self.agent.board
        return [m for root in b.threads() for m in b.walk(root.id) if self._shown(m)]

    def _tail(self) -> int | None:
        b = self.agent.board
        if self._root is None:
            return None
        return b.walk(b.threads()[-1].id)[-1].id
