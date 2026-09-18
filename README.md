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
