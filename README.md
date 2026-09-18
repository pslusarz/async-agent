# async-agent

If you have ever typed a steering message to GitHub Copilot while it was waiting on
a long-running tool, and watched your message just sit there until the tool
finished, you already know this is not a solved problem — not even for the people
building the leading agents.

This is a harness for the other way round: an agent you can keep talking to while
its tools are still working. Ask it something slow, ask it something else while it
waits, ask how the first one is going, change your mind and cancel it. Answers
arrive when they are ready and say which question they belong to.

![the chat app](docs/async-chat-demo.png)

Layout, setup, how to run the tests and the chat app, and the known gaps are in
[.github/copilot-instructions.md](.github/copilot-instructions.md).

## How it works

The question this is poking at: how do you get a turn-based LLM to behave more like
a human partner — one that copes with answers landing at odd intervals while the
conversation carries on around them?

Two pieces do most of the work: a small **event loop**, and a conversation kept as a
**message board**.

The event loop hands you a ReAct agent for nothing. Anything a tool reports is an
event; when one arrives the agent simply gets another turn, so it can chain a second
tool, retry a failed call with corrected arguments, or answer — without any of that
being a special case.

What the loop does *not* solve is the interesting part: tying a result to the request
that wanted it, possibly many exchanges back; deciding what to do when only some of
the answers are in; and letting the agent look in on a slow tool and give up on it.

That is what the board is for. It is internal — the person chatting never sees it —
but the agent reads it every turn:

- **Threads reorder as they are touched.** The thread with the newest activity is
  rendered last, right where the agent is about to reply, so attention lands on what
  just changed.
- **A tool call is a placeholder that explains itself.** While it runs, the agent
  sees the handle and what it may do with it:
  `[schedule(person='Jane') is running as task #5. You may inspect progress with
  tail(task=5); terminate it with kill(task=5). This placeholder will be replaced by
  the outcome when the task finishes or is killed.]`
- **When it finishes, the placeholder becomes the outcome:**
  `[schedule(person='Jane') returned: free 9-12]`
- **One turn is one node**, holding everything the agent said and every call it made
  at once. A node is finished only when all of its calls are, so the agent answers a
  two-person calendar question once, not twice with half the answer.
- **The rewriting settles.** Nodes stop changing as their tools land, so the earlier
  part of the transcript becomes stable and cacheable even though the tail of it is
  still in motion.

Tools run on their own threads behind a small interface: `tail` to ask how it is
going, `kill` to stop it. A finished tool posts its result back to the loop, which
gives the agent its turn to say something about it.

None of this reaches the user. `Chat` flattens the board into an ordinary linear
conversation — role, text, timestamp, nothing else — and when an answer arrives long
after the question, it introduces itself: *"Regarding your earlier question, 'how
long will the build take?': …"*

## What the board looks like

Three calendars were requested at once. Two came back quickly, Joe's did not, and
the user asked for an update while it was still running. This is the board at that
moment — `..` marks something still owed an answer, `ok` something settled:

```
.. #1 user   'when can Jane, Jack and Joe meet?'
  .. #2 agent  'Let me check all three schedules at the same time!'
          call #3 schedule(Jane) -> 'free 9-12'
          call #4 schedule(Jack) -> 'free 10-14'
          call #5 schedule(Joe)  -> PENDING
    ok #6 user   'how is that going?'
      ok #7 agent  'Let me check on that for you!'
              call #8 tail(5) -> '5% done, about 85s to go'
        ok #9 agent  "Still working on Joe's schedule — only about 5% of the way"
```

Worth noticing:

- **#2 is one turn holding three calls.** Two have results, one is still out, so the
  node is unfinished and #1 stays unanswered. The agent will not try to schedule a
  meeting from two thirds of the answer.
- **The progress question is complete in itself.** #6 was asked and answered, so it
  is settled even though the thing it asked about is not.
- **Checking on a task is just another tool call.** `tail` is recorded at #8 exactly
  like the calendar lookups — same shape, immediate result.

The same moment, as the person chatting sees it:

```
YOU   | when can Jane, Jack and Joe meet?
AGENT | Let me check all three schedules at the same time!
YOU   | how is that going?
AGENT | Let me check on that for you!
AGENT | Still working on Joe's schedule — only about 5% of the way through with
        roughly 85 seconds to go.
```

No ids, no tasks, no tree — and when Joe's calendar finally lands, the agent will
come back on its own with the meeting time.

## Project status

This is a proof-of-concept experiment, not a framework you can drop into something.
It is a place to find out which problems a harness like this actually has to solve,
and the answer so far is "more than you would guess". If there is interest, it could
grow into a library; right now the value is in the questions it has surfaced.

What that means in practice:

- There are three experiments in the repo, not one design. `exp1` is an asyncio event
  loop, kept frozen for comparison; `exp2` is the same ideas rebuilt as the message
  board; `exp3` is the chat UI over it. Nothing is factored for reuse.
- The tools are toys — a thermometer, a calendar, a build timer — chosen because they
  finish at inconvenient moments.
- Real gaps remain, and they are written down rather than papered over. A tool that
  raises an exception currently leaves its call pending forever, and a reply can land
  somewhere the board does not recognise as answering the question. Both are in the
  [known gaps](.github/copilot-instructions.md).

The tests are the honest description of what works: 76 of them, covering progress
probes, cancellation, retries after a bad call, several tools running at once, and a
browser driving the real app.
