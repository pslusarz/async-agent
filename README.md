# async-agent

If you have ever typed a steering message to GitHub Copilot while it was waiting on
a long-running tool, and watched your message sit there until the tool finished, you
already know this is not a solved problem, not even for the people building the
leading agents.

This is a harness for the other way round: an agent you can keep talking to while
its tools are still working. Ask it something slow, ask it something else while it
waits, ask how the first one is going, change your mind and cancel it. Answers
arrive when they are ready and say which question they belong to.

![the chat app](docs/async-chat-demo.png)

Layout, setup, how to run the tests and the chat app, and the known gaps are in
[.github/copilot-instructions.md](.github/copilot-instructions.md).

## How it works

The question here is how to get a turn-based LLM to cope with answers landing at odd
intervals while the conversation carries on around them.

Two pieces do most of the work: a small **event loop** and a conversation kept as a
**message board**.

The event loop gives you a ReAct agent almost for free. Anything a tool reports is an
event, and when one arrives the agent gets another turn, so it can chain a second
tool, retry a failed call with corrected arguments, or just answer. None of those
need special handling.

The loop leaves the harder parts open: tying a result to the request that wanted it,
possibly many exchanges back, deciding what to do when only some of the answers are
in, and letting the agent look in on a slow tool and give up on it.

The board covers those. The person chatting never sees it, but the agent reads it
every turn:

- **Threads reorder as they are touched.** The thread with the newest activity is
  rendered last, right where the agent is about to reply.
- **A running tool call is a placeholder saying what can be done with it:**
  `[schedule(person='Jane') is running as task #5. You may inspect progress with
  tail(task=5); terminate it with kill(task=5). This placeholder will be replaced by
  the outcome when the task finishes or is killed.]`
- **When it finishes, the placeholder becomes the outcome:**
  `[schedule(person='Jane') returned: free 9-12]`
- **One turn is one node**, holding everything the agent said and every call it made
  at once. A node is finished only when all of its calls are, so the agent answers a
  two-person calendar question once instead of twice with half the answer.
- **Only the recent part of the board changes.** Once a node's tools have landed it
  stops being rewritten, so the earlier part of the transcript stays stable and
  cacheable while the tail of it is still moving.

Tools run on their own threads behind a small interface, described in [The tool
contract](#the-tool-contract) below: `tail` to ask how it is going, `kill` to stop
it. A finished tool settles a `Future`, which wakes the loop and gives the agent a
turn to say something about it.

None of this reaches the user. `Chat` flattens the board into an ordinary linear
conversation with role, text and timestamp. When an answer arrives long after the
question it belongs to, it says so: *"Regarding your earlier question, 'how long will
the build take?': ..."*

## The tool contract

A tool that blocks the conversation while it works defeats the point, so every tool
here is something the harness can start, look in on, and give up on. Three methods,
and no reference to the agent, the board or the node it was called from:

```python
class Task(Protocol):
    def run(self) -> str: ...  # do the work, return the value
    def tail(self, lines: int) -> str: ...  # what is going on right now
    def stop(self) -> None: ...  # wind-down requested, called from another thread
```

A tool's entry point is a factory: it takes the arguments the model supplied and
returns a `Task`. The harness does the rest.

**The harness owns the thread.** `Runner` starts the task, and whatever `run`
returns settles a `concurrent.futures.Future` whose done-callback wakes the event
loop. The tool never calls back into the agent.

**Raising is a result.** A tool that throws settles with `failed: ...` rather than
leaving its call pending forever. The agent reads the failure like any other
outcome and decides whether to retry, ask, or give up. This is why the contract
returns a value instead of taking a callback: a callback that is never reached is
invisible, an exception is not.

**`tail` says how much you want.** The meta tool is `tail(task, lines)`, so the
agent can glance at one line or read the last twenty. Output goes onto the board
permanently, so the default is small.

**`kill` is cooperative, because it has to be.** A Python thread cannot be
interrupted. `kill` calls `stop()`, waits a short grace period for the task to wind
down, and then stops caring. A task that ignores `stop` can only be abandoned, and
the harness is honest about that rather than pretending otherwise.

**A killed task stays killed.** Whatever a task settles with after it was killed is
dropped rather than posted. A decision to stop is not undone a moment later by a
result arriving from the work that was stopped.

Most tools do not want to implement `tail` and `stop` themselves, so `Work` provides
them: a `status` line, a bounded log, and a stop flag. Subclasses implement `run` and
call `beat()` wherever they can afford to pause — which is both where progress is
reported and where a stop request is delivered, the way a Temporal activity heartbeat
doubles as its cancellation point.

```python
class Countdown(Work):
    def __init__(self, value: str, seconds: float):
        super().__init__()
        self.value, self.seconds = value, seconds

    def run(self) -> str:
        due = time.monotonic() + self.seconds
        while (left := due - time.monotonic()) > 0:
            self.status = f"still running, about {max(0, round(left))}s to go"
            self.beat(min(0.05, left))
        return self.value
```

A tool that never calls `beat` is a tool that can only be abandoned. `stuck_temperature`
is exactly that, on purpose.

## What the board looks like

Three calendars were requested at once. Two came back quickly, Joe's did not, and the
user asked for an update while it was still running. Here is the board at that
moment. `..` marks something still owed an answer, `ok` something settled.

```
.. #1 user   'when can Jane, Jack and Joe meet?'
  .. #2 agent  'Let me check all three schedules at the same time!'
          call #3 schedule(Jane) -> 'free 9-12'
          call #4 schedule(Jack) -> 'free 10-14'
          call #5 schedule(Joe)  -> PENDING
    ok #6 user   'how is that going?'
      ok #7 agent  'Let me check on that for you!'
              call #8 tail(5) -> '5% done, about 85s to go'
        ok #9 agent  "Still working on Joe's schedule, only about 5% of the way"
```

A few things to notice:

- **#2 is one turn holding three calls.** Two have results, one is still out, so the
  node is unfinished and #1 stays unanswered. The agent will not try to schedule a
  meeting from two thirds of the answer.
- **The progress question stands on its own.** #6 was asked and answered, so it is
  settled even though the thing it asked about is not.
- **Checking on a task is just another tool call.** `tail` is recorded at #8 the same
  way as the calendar lookups, with an immediate result.

The same moment, as the person chatting sees it:

```
YOU   | when can Jane, Jack and Joe meet?
AGENT | Let me check all three schedules at the same time!
YOU   | how is that going?
AGENT | Let me check on that for you!
AGENT | Still working on Joe's schedule, only about 5% of the way through with
        roughly 85 seconds to go.
```

No ids, no tasks and no tree. When Joe's calendar lands, the agent will come back on
its own with the meeting time.

## The same thing on the Claude Agent SDK

`exp4` rebuilds these scenarios on Anthropic's own Claude Agent SDK, to find out which
of the parts above it already has. It has the ones the event loop bought and none of
the ones the board did.

Free: starting work in the background, stopping it (`TaskStop`), and waking the
conversation when it lands. The unprompted turn is native — a finished task produces a
turn nobody asked for, which is most of what `exp1` needed a loop for.

The rest is not, and the gaps are the interesting part:

- **Every async tool has to be dressed up as an agent.** A plain MCP tool runs inline
  and blocks the turn. To get one off the main thread it must be wrapped in an
  `AgentDefinition` with `background=True` and delegated to, so a one-line calendar
  lookup becomes a subagent with its own context and system prompt. `background=True`
  is not optional either: the model always asks for `run_in_background: False`, so the
  definition has to override it. A side effect is that a failed call is now retried
  *inside* the subagent, and the parent never sees the correction — cleaner, but
  strictly less visible than a retry on the main transcript.
- **The agent will not look in on a running task, and you cannot make it.** The launch
  placeholder hands over an `output_file` and in the same breath says `Do NOT Read or
  tail this file — it is the full subagent JSONL transcript and reading it will
  overflow your context. If the user asks for progress, say the agent is still
  running.` That instruction is baked into the framework, not into our prompt, so
  `tail` has no counterpart here. Asked how something is going, the agent can only
  repeat that it is going.
- **A pending task can fall out of context.** Nothing re-renders the list of
  outstanding work. The only record that a task is running is the placeholder at the
  point it was launched, an ordinary message in an append-only transcript, so as the
  conversation grows or gets compacted that placeholder ages out and takes the agent's
  only handle on the task with it. The board rewrites its tail every turn precisely so
  that cannot happen.

## Caching, which is not optional

Thirteen live tests, three and a half minutes, every run billed and every run needing
credentials. At that price you stop re-running them, and then you stop trusting them.
`exp1`-`exp3` solved this long ago by patching `httpx` in-process, which is all
[pycachy](https://github.com/AnswerDotAI/cachy) does. Doing the same for `exp4` took a
day, and it is worth being specific about why:

- **There is no support for this.** The Agent SDK documentation has no page on testing,
  mocking or replay, and the issue tracker has no accepted pattern for it.
- **In-process patching cannot work.** The model calls happen inside the SDK's bundled
  **Node** CLI. No amount of patching Python reaches a subprocess, which also rules out
  `vcrpy` and `pytest-recording`. The only seam left is the wire, so the cache is a
  proxy on localhost that the CLI is pointed at with `ANTHROPIC_BEDROCK_BASE_URL`.
- **The request has to be re-signed.** SigV4 covers the `Host` header, so the CLI's
  signature is void the moment the endpoint changes to localhost. The proxy signs
  again on the way out. Replays need no credentials at all, because the cache key
  ignores headers.
- **Bedrock is not JSON.** Responses stream binary `application/vnd.amazon.eventstream`,
  which has to survive the round trip byte-for-byte.
- **Three kinds of id are minted per run** — the session id, the agent ids, and the
  task output paths under `/private/tmp` — and all of them are echoed back into the
  next request. They are renumbered by order of first appearance rather than flattened
  to one value, because flattening makes two requests that differ only in *which* of
  three concurrent agents finished hash identically.
- **One of those patterns matched `9007199254740991`.** It is `MAX_SAFE_INTEGER`, it
  appears as a `maximum` in the tool schemas, and it is sixteen characters of valid
  hex. Matching it shifted every id numbered after it.
- **The CLI reports `duration_ms`.** A replay does not spend that time, so the
  recording and the replay disagree about a number neither of them chose.
- **Some tests cannot be cached at all.** Two assert on interleaving, and latency is
  exactly what the cache removes, so the request sequence diverges and there is nothing
  to match. They are marked `realtime` and run live. A response cache can replay what
  was said; never when.

Eleven of the thirteen now replay in 53s with `AWS_ACCESS_KEY_ID` set to nonsense.

## Project status

This is a proof-of-concept experiment, not a framework you can drop into something.
It exists to find out which problems a harness like this has to solve, and there have
been more of them than I expected. If there is interest it could grow into a library.

What that means in practice:

- There are four experiments in the repo, not one design. `exp1` is an asyncio event
  loop, kept frozen for comparison. `exp2` is the same ideas rebuilt as the message
  board. `exp3` is the chat UI over it. `exp4` is the whole thing again on the Claude
  Agent SDK, as a control. Nothing is factored for reuse.
- The tools are toys: a thermometer, a calendar, a build timer, picked because they
  finish at inconvenient moments.
- Some real gaps are still open. A reply can land somewhere the board does not
  recognise as answering the question, and the agent gets only one look at a running
  task per turn, so it cannot tail twice or tail and then kill in one breath. Both are
  written up in the [known gaps](.github/copilot-instructions.md).

For what does work, the tests are the best guide: 90 of them against the board,
covering the tool contract itself, progress probes, cancellation, tools that raise,
retries after a bad call, several tools running at once, and a browser driving the
real app — plus 13 more driving the SDK, which are where the comparison above comes
from.
