# async-agent

An experiment in building a harness that lets an agent keep talking to you while
long-running tools are still working.

Two experiments live side by side:

- `src/main/exp1` — an asyncio event loop over a threaded post history, with async
  tools, progress probes (`tail`), cancellation (`kill`) and a ReAct retry loop.
  Built on [claudette](https://github.com/AnswerDotAI/claudette).
- `src/main/exp2` — the same ideas re-approached as a **message board**: nested
  replies, threads ordered by recent activity, tool calls that return a placeholder
  node which is later rewritten with the outcome. Talks to the Anthropic SDK
  directly and exposes a synchronous API over a background event loop.

## Setup

```sh
uv sync
```

## Running

The agents talk to Claude through AWS Bedrock, so you need AWS credentials with
Bedrock access in your environment or profile:

```sh
export AWS_PROFILE=your-profile
export AWS_REGION=us-east-1
```

```sh
uv run pytest
```

LLM responses are cached in `llm_cache.jsonl` so the suite replays without calling
Bedrock. Set `LLM_CACHE=off` to force live calls.
