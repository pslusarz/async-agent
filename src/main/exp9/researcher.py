from deepagents import create_deep_agent

from .model import model
from .tools import TOOLS

SP = (
    "You look things up for another agent. Your tools take a while to answer; call "
    "every one you need at once rather than one after another. When you have what "
    "was asked for, say it in plain prose and stop."
)

graph = create_deep_agent(model=model(), tools=TOOLS, system_prompt=SP)
