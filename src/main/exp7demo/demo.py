import threading
import time

from ..exp5.tools import kill, new_thread, tail
from ..exp7.chat import Chat
from .director import ASK, Director
from .script import Agent, Script

TYPE_DELAY = 0.035


class Demo:
    """One run of one scenario: a real exp7 agent, a scripted model, and a director."""

    def __init__(self, scenario, speed: float = 1.0, on_change=None):
        self.scenario = scenario
        self.director = Director(speed=speed)
        tools, replies = scenario.build(self.director)
        self.script = Script(replies, self.director)
        self.agent = Agent(
            self.script,
            self.director,
            sp=scenario.sp,
            tools=[*tools, tail, kill, new_thread],
        )
        self.chat = Chat(self.agent)
        self._on_change = on_change
        self.director.on_change = self.bump
        self.agent.on_change = self.bump
        self.typing = ""
        self.over = False
        self._thread = threading.Thread(target=self._drive, daemon=True)

    def start(self):
        self._thread.start()
        return self

    def bump(self):
        """Say that something moved. Called from the agent's, the tools' and the script's threads."""
        self.chat._bump()
        if self._on_change is not None:
            self._on_change()

    def stop(self):
        self.director.abort()
        for cid in list(self.agent.tasks):
            self.agent.kill(cid)
        self.agent.stop()

    def _drive(self):
        for line in self.scenario.says:
            if line.after:
                self.director.wait_played(line.after)
            self.director.gate(f"user types {line.text!r}", line.delay, ASK)
            if self.director.aborted:
                return
            self._type(line.text)
            self.chat.say(line.text)
            self.bump()
        self.over = True
        self.bump()

    def _type(self, text: str):
        pace = TYPE_DELAY / self.director.speed
        for i in range(1, len(text) + 1):
            self.typing = text[:i]
            self.bump()
            time.sleep(pace)
        self.typing = ""
