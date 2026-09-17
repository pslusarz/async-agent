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