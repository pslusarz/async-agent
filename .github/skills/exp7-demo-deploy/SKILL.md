---
name: exp7-demo-deploy
description: Deploy and operate the public exp7 demo app (src/main/exp7demo) - a canned, LLM-free walkthrough of the async agent harness. Use when deploying, containerising, configuring a reverse proxy, sizing, or debugging the demo in a hosted environment.
---

# Deploying the exp7 demo

A public, read-only walkthrough of the async-agent harness. Visitors pick a scenario
and watch a scripted conversation play out, with Play / Pause / Step controls and a
live view of the agent's board.

**It never calls an LLM.** The model is replaced by a list of canned replies, so the
app makes no outbound network calls of any kind and needs no credentials.

## Entrypoint

```
main.exp7demo.app:app
```

An ASGI app (fasthtml over Starlette). Run it with uvicorn:

```sh
uv sync
uv run uvicorn main.exp7demo.app:app \
  --host 0.0.0.0 --port 8000 \
  --timeout-graceful-shutdown 3
```

`--timeout-graceful-shutdown` is **required**, not optional. See "Shutdown" below.

`src/main/exp7demo/app.py` also has an `if __name__ == "__main__": serve()` block.
That is a local convenience (it turns on reload); do not use it in a deployment.

The import path is `main.*`, not `src.main.*` - `pyproject.toml` maps `src/main` to
the `main` package via hatchling. Any install that puts the project on the path
(`uv sync`, `pip install .`, `pip install -e .`) gives you `main.exp7demo.app`.

## Routes

| Route | Method | Purpose |
|---|---|---|
| `/` | GET | Landing page: explanation, screenshot, scenario list, outbound links |
| `/s/{key}` | GET | A scenario's stage. Unknown `key` redirects to `/` |
| `/s/{key}/events` | GET | **SSE stream** that pushes the whole stage on every change |
| `/s/{key}/play` `/pause` `/step` `/restart` | POST | Controls; return an empty body |
| `/{file}.{ext}` | GET | Static files from `src/main/exp7demo/static/` |

Scenario keys come from `BY_KEY` in `src/main/exp7demo/scenarios.py`: currently
`one-call` and `weather`.

## Configuration

| Env var | Required | Notes |
|---|---|---|
| `DEMO_SECRET_KEY` | **yes, in production** | Signing key for the session cookie |

If `DEMO_SECRET_KEY` is unset, fasthtml generates a key and writes it to `.sesskey`
in the **current working directory**. That is fine locally and wrong in a deployment:
an ephemeral filesystem means every restart invalidates every session, and multiple
replicas each generate a different key. Always set it. `.sesskey` is gitignored and
must never be committed.

There is no database, no cache, no writable state on disk. The container can be
read-only apart from `/tmp`.

Tunables are module constants, not env vars - edit them if you need to:

- `STREAM_TTL = 300.0` in `app.py` - how long one SSE connection lives
- `Stages.TTL = 15 * 60` - idle seconds before an unwatched session is reaped
- `Stages.MAX = 200` - soft cap on concurrent sessions

## State, and why this needs one replica or sticky sessions

**All state is in process memory.** `Stages` is a plain dict keyed by
`(session id, scenario key)`. The session id is minted into a signed cookie on first
visit by `sid_of()`.

A visitor's `/s/{key}/events` stream and their `/play` POSTs must land on the **same
process**, or the controls will drive a different run from the one on screen.

So either:

- run a **single replica** (simplest, and plenty for a demo), or
- enable **sticky sessions** on the load balancer, keyed on the `session_` cookie.

Horizontal scaling without stickiness is broken, not merely suboptimal. There is no
shared store to add; this is by design, since the point of the app is a live in-memory
agent harness.

## Reverse proxy: SSE needs care

The UI is driven entirely by one long-lived `text/event-stream` per open tab. Two
things to get right:

1. **Disable response buffering.** nginx buffers by default and the UI will appear
   frozen. Set `proxy_buffering off;` and `proxy_cache off;` on the `/s/` location,
   or have the app sit behind something that does not buffer.
2. **Idle timeouts.** A *paused* demo sends no bytes at all - there is no heartbeat.
   Any proxy with an idle-read timeout shorter than the silence will drop the
   connection. The browser's `EventSource` reconnects by itself and the first frame
   is a full re-render, so nothing is lost, but it looks like a flicker.

   Mitigation: set `STREAM_TTL` **below** the proxy's idle timeout, so the stream
   closes itself cleanly rather than being killed. Defaults worth knowing: AWS ALB
   60s, Heroku 55s, Cloudflare ~100s. With any of those, drop `STREAM_TTL` to ~45.

   A proper fix would be a periodic SSE comment as a heartbeat; it is not implemented.

## Shutdown

Uvicorn's graceful shutdown waits for in-flight responses to finish. An SSE stream by
definition does not finish, so **without `--timeout-graceful-shutdown` the process
hangs until every viewer disconnects** (observed: 28s, bounded only by the client).
With `--timeout-graceful-shutdown 3` it exits in 3s.

A Starlette lifespan `shutdown` handler does **not** help: uvicorn runs it *after*
waiting for connections, so it fires too late to end the streams.

Make sure the orchestrator's termination grace period is longer than the uvicorn
timeout (e.g. uvicorn 3s, Kubernetes `terminationGracePeriodSeconds: 15`).

## Sizing

Each active session runs a real agent harness on real threads:

- 1 agent event-loop thread
- 1 scripted-user thread
- 1 thread per running background task

Measured peak extra threads per session: **5** for `weather` (all three tool calls in
flight), **2** for `one-call`. Both drop back to 0 once the run is stopped, so a
reaped session reclaims everything.

Sessions are reaped when unwatched (no live SSE stream) and idle past `Stages.TTL`.
A session with a live stream is **never** reaped, so `Stages.MAX` is a soft cap: the
real ceiling is concurrent viewers, not that constant. Size the container's thread and
memory budget on peak concurrent viewers x ~5 threads, and lower `TTL` if abandoned
tabs pile up.

CPU is near idle - the scenarios are mostly `Event.wait()` on a director gate.

## Dependencies

`pyproject.toml` is shared with the research experiments, so installing it pulls in
`claudette`, `anthropic[bedrock]`, `claude-agent-sdk` and `boto3`. The demo imports
that chain (`exp7demo.script` -> `exp7.agent` -> `exp5.agent` -> `main.bedrock`) but
**never calls it**, because `exp7demo.script.Agent` overrides `_client()` to return
the canned script.

Verified: the app imports and serves with every AWS variable unset and no
`~/.aws`. If you want a smaller image you could trim the dependency set, but do not
remove the import chain itself.

Requires Python **>= 3.13** (`requires-python` in `pyproject.toml`).

## Railway: the live deployment

Live: **https://async-agent-demo-production.up.railway.app**

| | |
|---|---|
| Project | `async-agent-demo`, id `e49075bc-3af7-4573-8868-e10ff4762a8e` |
| Workspace | Pawel Slusarz's Projects |
| Environment | `production` (the only one - there is deliberately no staging) |
| Service | `async-agent-demo`, 1 replica |
| Builder | Railpack (auto-detected: uv + Python 3.13 from `pyproject.toml`) |

Two checked-in files drive it: `Procfile` (the start command) and `railway.json`
(replica count and restart policy). Both live at the repo root.

### Deploys are CLI uploads, not GitHub

```sh
railway up --ci --service async-agent-demo --environment production
```

`railway up` tars the working directory and hands it to the builder. The Railway
GitHub App has **no access to this repo and does not need any** - pushing to
`origin/main` deploys nothing. `--ci` streams build logs and exits when the build
finishes, instead of tailing deploy logs forever.

This means **the deployed code is whatever was in the working tree at upload time**,
including uncommitted edits. Check `git status` before deploying if that matters.

To switch to push-to-deploy later: grant the Railway GitHub App access to the repo at
<https://github.com/settings/installations>, then
`railway service source connect --repo pslusarz/async-agent --branch main`. Verify it
actually took with `gh api repos/pslusarz/async-agent/deployments` - an empty array
means the hook is silently dead, which has happened on a sibling project.

### Railpack, not Nixpacks

Railway now defaults new services to Railpack. A `nixpacks.toml` is **silently
ignored**, and so is `"build": {"builder": "NIXPACKS"}` in `railway.json` - the build
log says `[railpack] merge ghcr.io/railwayapp/railpack-runtime:...` either way. Don't
bother writing one; the `nixpacks.toml` that was here initially was deleted as dead
config.

Railpack does read the **`Procfile`**, which is what actually supplies the start
command and therefore the mandatory `--timeout-graceful-shutdown`.

### `uv run` re-syncs dev dependencies at container boot

The first deploy downloaded **playwright (46 MB)** on every container start, because
`pyproject.toml` is shared with the research experiments and a bare `uv run` syncs the
full dev group before executing. The fix is in the `Procfile`:

```
web: uv run --no-dev --frozen --no-sync uvicorn main.exp7demo.app:app --host 0.0.0.0 --port $PORT --timeout-graceful-shutdown 3
```

Railpack has already installed the project into `/app/.venv` at build time, so the
runtime sync is pure waste. A healthy boot is four lines and nothing else:

```
Starting Container
INFO:     Started server process [13]
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8080
```

If you see package downloads there again, the `uv run` flags got dropped.

### Secrets

`DEMO_SECRET_KEY` is set on the service. Set it without the value ever reaching the
terminal, your shell history, or an agent's transcript:

```sh
openssl rand -hex 32 | railway variables --set-from-stdin DEMO_SECRET_KEY \
  --service async-agent-demo --environment production --skip-deploys
```

List names only (`--kv` prints values, which you rarely want):

```sh
railway variables --service async-agent-demo --environment production --kv | cut -d= -f1
```

### Railway's proxy and SSE

Verified: Railway's edge does **not** buffer `text/event-stream`, and first byte
arrives in ~0.12s. `STREAM_TTL = 300` is left at its default because Railway did not
drop an idle paused stream - unlike the ALB/Heroku/Cloudflare cases in the proxy
section above. If a flicker-every-N-seconds is ever reported, that assumption is the
first thing to recheck.

### Operating it

```sh
railway logs --service async-agent-demo --environment production --lines 50
railway status                      # project / environment / service of the linked dir
railway service restart --service async-agent-demo --environment production --yes
railway domain --service async-agent-demo          # note: rejects --environment
```

`railway domain` is the one command here that does **not** accept `--environment`;
passing it just prints usage.

## Smoke test after deploying

```sh
BASE=https://async-agent-demo-production.up.railway.app

curl -sS -o /dev/null -w '%{http_code}\n' $BASE/                 # 200
curl -sS -o /dev/null -w '%{http_code}\n' $BASE/demo.png         # 200, static files served
curl -sS -o /dev/null -w '%{http_code}\n' $BASE/s/nope           # 303, unknown key redirects

# session cookie is issued, and the SSE stream delivers a first frame unbuffered
curl -sS -c /tmp/ck -o /dev/null $BASE/s/weather
grep -q session_ /tmp/ck && echo 'cookie ok'
curl -sS -b /tmp/ck -N --max-time 5 $BASE/s/weather/events | head -c 200
```

The last command must print HTML within a second or two. If it hangs and then dumps
everything at the end, a proxy is buffering.

In a browser: load `/s/weather`, press **Play**, and confirm messages and spinners
appear progressively. Press **Step** from a fresh **Restart** and confirm exactly one
beat advances per click.

## Layout

```
src/main/exp7demo/
  app.py          routes, SSE, HTML/CSS, Stage + Stages (session store)
  demo.py         Demo: one run of one scenario; owns agent, chat, director
  director.py     Director: the play/pause/step gate every thread passes through
  script.py       canned model client, scripted tool, Agent subclass with no LLM
  scenarios.py    the scenarios themselves; BY_KEY is the route-key registry
  static/demo.png landing-page screenshot (a checked-in build artifact)
```

`exp7demo` builds on `exp7` / `exp5` / `exp2`, which are the live harness. Do not
change those to fix a demo problem.

## Things that will bite you

- Deploying without `DEMO_SECRET_KEY`: sessions reset on every restart.
- Deploying two replicas without sticky sessions: controls hit the wrong run.
- Deploying behind buffering nginx: the page never updates.
- Forgetting `--timeout-graceful-shutdown`: rollouts stall.
- Expecting `git push` to deploy: it doesn't, deploys are `railway up` uploads.
- Writing a `nixpacks.toml` and expecting Railway to read it: Railpack ignores it.
- A bare `uv run` in the `Procfile`: re-installs the dev group on every boot.
- `static/demo.png` is a committed artifact. If the UI changes it goes stale; it is
  regenerated by stepping the `weather` scenario ~15 beats in headless chromium at a
  1500px viewport and screenshotting `#stage`. There is no script for it.
