from ..exp5.agent import Agent as Timed


class Agent(Timed):
    """An Agent that hands every call it starts to a listener, and says when anything moves."""

    listener = None
    on_change = None

    def _emit(self, kind: str, cid: int):
        if self.listener is not None:
            self.listener(kind, self.board.calls[cid])
        self._moved()

    def _changed(self):
        super()._changed()
        self._moved()

    def _moved(self):
        if self.on_change is not None:
            self.on_change()
