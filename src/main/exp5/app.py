from fasthtml.common import serve

from ..exp3.app import make_app
from .agent import Agent
from .chat import Chat
from .tools import kill, new_thread, stuck_temperature, tail

SP = (
    "Tools run in the background and take a while. Calling one returns a task id, not "
    "a result. When the user asks how something is going, check on it and tell them."
)

chat = Chat(
    Agent(
        sp=SP,
        tools=[stuck_temperature, tail, kill, new_thread],
        timeout_cap=8.0,
        max_retries=1,
    )
)
app = make_app(chat)

if __name__ == "__main__":
    serve()
