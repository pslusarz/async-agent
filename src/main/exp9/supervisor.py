from deepagents import AsyncSubAgent, create_deep_agent

from .model import model
from .watch import SERVER, check_back_in, peek_async_task

SP = (
    "You do not look things up yourself: hand the work to the researcher, which runs "
    "in the background and reports back, then answer in your own words. Starting one "
    "returns a task id, not a result, and nothing will tell you when it finishes.\n"
    "So in the same turn that you start a task, call check_back_in with how long you "
    "expect it to take, then reply to the person and stop. Never check or peek at a "
    "task in the turn you started it in.\n"
    "When a wake-up brings you back: check the task. If it has finished, tell the "
    "person the answer without being asked, and arrange no further wake-ups. If it is "
    "still going, call check_back_in once and say nothing else. If you are woken about "
    "a task whose answer you have already given, say nothing at all.\n"
    "When the person asks how it is going, peek at the task and tell them what it is "
    "doing. When they add to or change what they asked, pass it on to the running task "
    "rather than starting over."
)

researcher = AsyncSubAgent(
    name="researcher",
    description=(
        "Looks things up - temperatures, people's free hours, how long the build will "
        "take - and reports back. Give it the question in plain prose."
    ),
    graph_id="researcher",
    url=SERVER,
)

graph = create_deep_agent(
    model=model(),
    subagents=[researcher],
    tools=[peek_async_task, check_back_in],
    system_prompt=SP,
)
