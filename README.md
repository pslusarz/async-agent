# async-agent

> **Write-up:** [An agent you can interrupt](https://pslusarz.github.io/articles/2026/10/01/an-agent-you-can-interrupt.html)
> — why an event loop is enough to produce ReAct, what breaks once a tool outlives the
> turn that called it, and how this compares with Anthropic's Claude Agent SDK.
>
> **Demo:** [async-agent-demo-production.up.railway.app](https://async-agent-demo-production.up.railway.app)
> — the harness running three scenarios you can play, pause or step through a beat at
> a time, with the agent's board beside the chat. Nothing calls a model.

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

## Timeouts

A tool call carries an extra argument the harness injects into every schema: how long
the agent expects it to take. When that runs out the harness does not act on it. It
puts an **overdue event** on the same queue as user messages and finished tasks, which
means the agent simply gets a turn, with a note naming the task and asking it to look
and decide. Nothing in the system prompt or any tool description mentions killing;
that only ever appears on the event, because only the harness knows the clock ran out.

Deciding to leave a task alone re-arms the timer, so the question comes back. Deciding
to kill it spends from a **retry budget** counted along the branch that led to the
call — ancestors only, so five lookups issued side by side never spend each other's
retries. When the budget is gone, the kill result says so, and tells the agent to open
a new thread and ask the person what to do rather than try again.

Here is a task that was given more time and then stopped, with the elapsed clock on
the left. The expected interval was clamped to a second and the retry budget to zero,
to keep the example short:

```
 0.0s  .. #1  user   'what is the temperature in Warsaw, MO?'
11.0s    .. #2  agent  'Let me check that for you right now!'
                  call #3 temperature(Warsaw, MO) -> KILLED
13.4s      ok #4  agent  'Let me check on how that lookup is coming along.'  <- overdue
                    call #5 tail(3) -> 'almost done...'
16.4s        ok #6  agent  "It's almost done — just about there!"
                      call #7 tail(3) -> 'almost done...  (nothing has moved since
                                          you last looked; you will be told when
                                          it does)'
18.1s          ok #8  agent  "I'll keep waiting — no need to keep checking since
                              I'll be notified as soon as the result comes in."
23.4s      ok #9  agent  'Let me see how it is doing!'                      <- overdue
                    call #10 tail(3) -> "I'm stuck and cannot make progress."
25.2s        ok #11 agent  'It looks like the lookup has gotten stuck.'
                      call #12 kill(3) -> 'killed. temperature has now been killed
                                           1 time over this request and is not going
                                           to work. Use new_thread to ...'
27.2s          ok #13 agent
                      call #14 new_thread(...) -> 'said in a new thread, #15'
27.2s  ok #15 agent  "I've been trying to look up the temperature in Warsaw, MO,
                      but the tool keeps stalling. How would you like to proceed?"
```

This is the part that is hard without the board. **#4 and #9 are siblings**: two
separate visits to the same task, ten seconds apart, each its own branch hanging off
the call they are about — not two more lines at the end of a transcript. And **#15 is
a new root**, because a thread that has run out of things to try is a bad place to ask
a question.

Two smaller things the board made easy. The turn is a loop, so the agent keeps every
tool for its whole turn and can tail, think, and kill in one breath; it is never
offered a cut-down toolset. And at #6 it chose to look twice — so `tail` tells it when
nothing has moved since its last look, and promises it will be told when something
does. That is a fact rather than a rule, and the re-armed timer is what makes the
promise true. It stopped polling on its own.

## The same thing on the Claude Agent SDK

`exp4` and `exp6` rebuild these scenarios on Anthropic's own Claude Agent SDK, to find
out which of the parts above it already has. It has the ones the event loop bought and
none of the ones the board did.

Free: starting work in the background, stopping it (`TaskStop`), and waking the
conversation when it lands. The unprompted turn is native — a finished task produces a
turn nobody asked for, which is most of what the event loop was for.

Timeouts port over cleanly, because the clock was never part of the API in the first
place. `TaskStarted` carries a task id and the session can be spoken to at any moment,
which is all `exp6` needs to arm a timer and nudge when it expires. Given that nudge,
the agent behaves the same way it does on the board: told once that a task had been
running 20s with an empty transcript it said *"within normal startup range"* and left
it alone, and told again 20s later it said *"still empty after two check-ins, I'll stop
it now"* and called `TaskStop`. Nobody typed anything after the opening question.

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
  repeat that it is going. The prohibition binds the agent, though, not the harness:
  that file is live-updating JSONL, so `exp6` reads it and folds a line of it into the
  overdue nudge. `tail` does not disappear, it changes hands — and a progress report
  the harness offers cannot be polled the way a tool the agent calls can.
- **There is nowhere to put an expected interval.** The backgrounding schema is
  `Agent`/`Task` and belongs to the framework, so the agent cannot say how long it
  thinks a call will take. The timeout becomes harness policy instead of the agent's
  own judgement.
- **A nudge from the harness is indistinguishable from the user.** Saying something to
  the session is the only way in, so an overdue notice arrives as a user turn. It has
  to be labelled `[automatic notice from the harness, not from the person you are
  talking to]`, or the agent thanks the user for checking in. The board has the same
  shape — every line is rendered as user content — but there a placeholder is already
  marked as machinery, so it costs nothing.
- **A pending task can fall out of context.** Nothing re-renders the list of
  outstanding work. The only record that a task is running is the placeholder at the
  point it was launched, an ordinary message in an append-only transcript, so as the
  conversation grows or gets compacted that placeholder ages out and takes the agent's
  only handle on the task with it. The board rewrites its tail every turn precisely so
  that cannot happen.

## Caching, which is not optional

Sixteen live tests, minutes rather than seconds, every run billed and every run
needing credentials. At that price you stop re-running them, and then you stop
trusting them. The board experiments solved this long ago by patching `httpx`
in-process, which is all [pycachy](https://github.com/AnswerDotAI/cachy) does. Doing
the same for the SDK ones took a day, and it is worth being specific about why:

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
- **Some tests cannot be cached at all.** Several assert on interleaving or on a
  wall-clock timer, and latency is exactly what the cache removes, so the request
  sequence diverges and there is nothing to match. They are marked `realtime` and run
  live. A response cache can replay what was said; never when.

The cacheable ones replay in under a minute with `AWS_ACCESS_KEY_ID` set to nonsense.

## Project status

This is a proof-of-concept experiment, not a framework you can drop into something.
It exists to find out which problems a harness like this has to solve, and there have
been more of them than I expected. If there is interest it could grow into a library.

What that means in practice:

- There are two lines of experiment in the repo, not one design. The harness is
  `exp1`-`exp3` and `exp5`: an asyncio event loop kept frozen for comparison, the same
  ideas rebuilt as the message board, a chat UI over it, and timeouts on top. The
  control is `exp4` and `exp6`, which is the whole thing again on the Claude Agent SDK.
  Nothing is factored for reuse.
- The tools are toys: a thermometer, a calendar, a build timer, picked because they
  finish at inconvenient moments.
- Some real gaps are still open. A reply can land somewhere the board does not
  recognise as answering the question, so a question can stay open while its answer
  sits elsewhere in the thread. That one is written up in the
  [known gaps](.github/copilot-instructions.md).

For what does work, the tests are the best guide: 97 of them against the board,
covering the tool contract itself, progress probes, cancellation, tools that raise,
retries after a bad call, several tools running at once, timeouts and the decisions
they force, and a browser driving the real app — plus 16 more driving the SDK, which
are where the comparison above comes from.

## The demo app

[async-agent-demo-production.up.railway.app](https://async-agent-demo-production.up.railway.app)
is a public walkthrough of the harness. **No model is called.** The replies are canned
and the tools are scripted, so it behaves the same way every time, costs nothing to
leave running, and needs no credentials.

Everything else is the real thing: the same board, the same background tasks on the
same threads, the same widgets. The panel on the right shows the board exactly as the
model would have been handed it, plus live `tail` output from each running task.

Three scenarios, all driveable with **Play**, **Pause** and **Step**:

- **One tool call, then one that wedges** — the simple shape first, then a tool that
  reports progress and stops dead. The harness notices it is overdue; the agent tails
  it, kills it and starts a fresh call that completes.
- **Three at once, with a conversation over the top** — three lookups in flight while
  the user asks for a joke and then a progress report.
- **A second question, about something else entirely** — two different tools
  overlapping, where the later question is answered first and the earlier answer has
  to say which question it belongs to.

The code is [src/main/exp7demo](src/main/exp7demo), about 1,100 lines on top of `exp7`:

- `director.py` — the gate every thread passes through, so Pause stops the agent, the
  tools and the scripted user together rather than only what is on screen.
- `script.py` — the canned client, the scripted tool, and an `Agent` whose overdue
  timer is a director beat rather than a wall clock (a real timer would fire while the
  viewer had it paused).
- `scenarios.py` — the scenarios themselves. Ordering is pinned with cues rather than
  sleeps: a scripted question waits on a beat from a tool's progress, and a task can
  carry `settle_after` so it cannot land before some other beat has played.

Running it locally, deploying it, and the operational traps — session affinity, SSE
buffering, graceful shutdown — are in
[.github/skills/exp7-demo-deploy/SKILL.md](.github/skills/exp7-demo-deploy/SKILL.md).
