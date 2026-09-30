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
  `run.py` holds the tool contract: a `Task` protocol of `run`/`tail`/`stop`, a
  `Runner` that owns the thread and the `Future`, and a `Work` base implementing
  `tail`/`stop` over a status line, a bounded log and a `beat()` that doubles as the
  cancellation point.
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

exp4's model calls happen inside the bundled Node CLI, where patching Python's
httpx cannot reach them, so `src/main/exp4/cache.py` puts a recording proxy in
front of Bedrock instead and points the subprocess at it with
`ANTHROPIC_BEDROCK_BASE_URL`. The proxy re-signs each request and forwards it
with httpx, which is what `pycachy` patches, so the store is an ordinary
`cachy.jsonl`. Record against Bedrock, then replay with no credentials at all:

```sh
AWS_PROFILE=staging AWS_REGION=us-east-1 CLAUDE_CODE_USE_BEDROCK=1 \
  uv run pytest src/test/exp4 -m live -n0            # record
CLAUDE_CODE_USE_BEDROCK=1 \
  uv run pytest src/test/exp4 -m 'live and not realtime' -n0   # replay, ~4x faster
```

Record with `-n0`: cachy rewrites the whole file per entry, so parallel workers
lose each other's writes.

Things worth remembering when working on the tests:

- Assert on data, not on the model's phrasing. Several tests have broken because
  they checked for particular wording in a reply.
- A cached bad response replays forever. After changing a prompt, delete
  `llm_cache.jsonl`, re-record, and dedupe it (keep last per key, sort by key).
- Replaying from cache removes latency, which changes thread scheduling. Async
  code that relied on an LLM call to yield needs a real suspension point.
- The two `realtime` tests cannot be replayed at all, for the same reason: they
  assert on the interleaving that the cache removes. Run them live.
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

**Tool exceptions (exp2).** Closed. A tool's `run` returning settles its `Future`, and
raising settles it with `failed: ...`, so an exception is an ordinary result the agent
reads and reacts to rather than a call that stays pending forever.

**One look per turn (exp2).** `_take_turn` drops the meta tools from the schema list
after the first meta call (`probed = True`), so within a single turn the agent can
`tail` once and must then answer or start a plain tool. It cannot tail two tasks, tail
the same task twice to see whether it moved, or tail and then decide to kill. Each of
those needs a further user message today. The guard exists to stop tail loops; a budget
would serve better than a hard ban, and would let the agent run a real ReAct loop before
answering a question about progress.
