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
