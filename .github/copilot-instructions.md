# async-agent

We need to build from scratch, a harness that allows the agent to respond to user inputs while it is also busy with other tasks. 

Our goal is to understand this space and what issues a framework like that needs to solve.

We will build in stages, taking very small steps and solving one problem at a time.

Brainstorming scenarios:
- agent calls a tool which completes right away (control case)
- agent calls a tool, which takes a long time, and agent can chat with the user and answer questions about the tool's progress
- agent calls a tool, inspects its progress periodically, and decides the tool needs to be killed (it is looping infinitely, missing permissions or some such)
- agent calls a long running tool, which gives periodic updates, and after the tool completes, the context is consolidated to remove the progress details.
- agent kills long running tool in response to user request

The way I see it is the harness running an event loop, where certain parts of the context are rewritten to reflect currently running tasks. User messages should come through that event loop. Agent should have meta-tools to manage the running tasks. Each task should have a streaming output buffer that the agent can inspect, as well as the standard Pydantic return object once it completes.
## Layout

- `src/main/bedrock.py` — Claude via AWS Bedrock, plus the response cache wrapper.
- `src/main/exp1` — an asyncio event loop over a threaded post history, with async
  tools, progress probes (`tail`), cancellation (`kill`) and a ReAct retry loop.
  Built on claudette. Frozen; kept for comparison.
- `src/main/exp2` — the same ideas re-approached as a **message board**: nested
  replies, threads ordered by recent activity, and a tool call that leaves a
  placeholder which is later rewritten with its outcome. Talks to the Anthropic SDK
  directly (claudette's `mk_msgs` reassigns roles by position, which breaks a board
  whose roles do not alternate) and exposes a synchronous API over a background
  event loop. `chat.py` projects the tree into a plain linear transcript.
- `src/main/exp3` — a minimal fasthtml chat UI over exp2, with tools that pick a
  random completion time (capped at two minutes) and report progress while running.

## Setup

```sh
uv sync
```

The agents talk to Claude through AWS Bedrock, so AWS credentials with Bedrock
access need to be in the environment or profile:

```sh
export AWS_PROFILE=your-profile
export AWS_REGION=us-east-1
```

## Tests

```sh
uv run pytest
```

Runs in parallel (`-n auto`, set in `pyproject.toml`); use `-n0` to debug. LLM
responses are cached in `llm_cache.jsonl` so the suite replays in seconds without
calling Bedrock; `LLM_CACHE=off` forces live calls. A cold run still needs AWS
credentials, because the client is built before any cache lookup.

Things worth remembering when working on the tests:

- Assert on data, not on the model's phrasing. Several tests have broken because
  they checked for particular wording in a reply.
- A cached bad response replays forever. After changing a prompt, delete
  `llm_cache.jsonl`, re-record, and dedupe it (keep last per key, sort by key).
- Replaying from cache removes latency, which changes thread scheduling. Async
  code that relied on an LLM call to yield needs a real suspension point.
- Playwright is opened and closed inside each test. The pytest plugins hold a
  session-scoped event loop that stops pytest-asyncio from running exp1's tests
  in the same worker.

## The chat app

```sh
LLM_CACHE=off uv run uvicorn main.exp3.app:app --port 8000
```

Ask for something that needs a tool ("how long will the build take?", "when can
Jane, Jack and Joe meet?") and keep talking while it works. The answer arrives on
its own when the tool finishes, and names the question it belongs to.

## Known gaps

**Reply placement vs. task completion (exp2).** `Board.answered` treats a finished
task node as answered only once something is written *directly beneath it*, but the
agent's reply lands wherever the conversation put it. If a client follows up on its
own question (`parent=q.id`) rather than on the agent's task node, the task node is
left childless and `wait_for(q)` blocks forever even though the answer is sitting
elsewhere in the thread. The capstone test only passes because it attaches
follow-ups to the task node. Fixing it means either handing clients thread ids and
letting the harness choose placement, or changing the rule so an answer need not sit
directly under the task it resolves.

**Tool exceptions (exp2).** A tool that raises never calls `agent.result`, so its
call stays pending forever and its node never becomes terminal. The intent is to
treat a raised exception as an ordinary result the agent reads and reacts to
(retry, ask the user, give up), exactly as `strict_temperature` does with an error
string.
