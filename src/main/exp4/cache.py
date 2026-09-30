"""Record and replay exp4's Bedrock traffic, so the live tests run without the network.

exp1-3 cache by patching httpx in-process, which works because the anthropic SDK
calls it directly. exp4 cannot: its model calls happen inside the bundled Node CLI,
and patching Python never reaches a subprocess. The only seam left is the wire, so
this serves a proxy on localhost, hands the CLI its address through
ClaudeAgentOptions.env as ANTHROPIC_BEDROCK_BASE_URL, and forwards each request to
the real Bedrock. Forwarding uses httpx, which is what pycachy patches, so the
store is an ordinary cachy.jsonl and none of the caching logic lives here.

The CLI signs for whatever endpoint it is given, so its signature is worthless once
the host changes; _forward re-signs from scratch. A replay never leaves the process
and cachy keys on url, accept and body rather than headers, so a bogus signature is
fine and no AWS credentials are needed to replay.

A replay only matches a recording if the request bytes match. Four things do not:
the session id, the agent ids and the /private/tmp task paths are minted per run,
and duration_ms is how long a subagent took, which a replay does not spend. The
first three are renumbered by order of first appearance rather than flattened to
one value, so requests that differ only in which of several concurrent agents
finished still hash differently.

Tests whose assertions are about interleaving cannot be replayed at all, because
the latency they measure is the thing the cache removes; those are marked realtime
and run live. See the Tests section of .github/copilot-instructions.md for the
record and replay commands.
"""

import base64
import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import boto3
import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials

REGION = os.getenv("AWS_REGION", "us-east-1")
HOST = f"bedrock-runtime.{REGION}.amazonaws.com"
ROOT = Path(__file__).resolve().parents[3]
JSONL = ROOT / "cachy.jsonl"
ENABLED = os.getenv("LLM_CACHE", "on") != "off"
KEEP = ("content-type",)
# the session id, the agent ids and the task output paths are minted fresh every run
UUID = r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b"
# the digit guard keeps large plain integers in the tool schemas from reading as hex ids
AGENT = r"\b(?![0-9]+\b)[0-9a-f]{16,17}\b"
VOLATILE = re.compile(f"{UUID}|{AGENT}")


def _stable(m: re.Match) -> str:
    seen: dict[str, str] = {}
    return VOLATILE.sub(lambda x: seen.setdefault(x[0], f"cachy{len(seen)}"), m[0])


# numbering them by first appearance keeps concurrent agents distinct from each other
BODY = (re.compile(r"(?s)\A.*\Z"), _stable)
# a replay has no real latency, so the time the CLI reports back is not the recorded one
ELAPSED = (
    re.compile(r"<duration_ms>\d+</duration_ms>"),
    "<duration_ms>0</duration_ms>",
)

_url: str | None = None
_lock = threading.Lock()


def _credentials():
    try:
        if (c := boto3.Session().get_credentials()) is not None:
            return c
    except Exception:
        pass
    # a replay never leaves the process, and the key ignores the signature
    return Credentials("replay", "replay")


def _probe(body: bytes) -> bool:
    """A model-availability check, which Claude Code sends as a one-token '.' prompt."""
    try:
        return json.loads(body).get("max_tokens") == 1
    except ValueError:
        return False


def _remember(req: httpx.Request, res: httpx.Response) -> None:
    from cachy.core import _cache, _key, _write_cache

    if _cache(k := _key(req), JSONL):
        return
    hdrs = {"content-type": res.headers.get("content-type", "application/json")}
    _write_cache(
        k,
        base64.b64encode(res.content).decode(),
        JSONL,
        hdrs,
        res.status_code,
        binary=True,
    )


def _forward(method: str, path: str, body: bytes, accept: str) -> httpx.Response:
    url = f"https://{HOST}{path}"
    signed = AWSRequest(
        method=method,
        url=url,
        data=body,
        headers={"content-type": "application/json", "accept": accept},
    )
    SigV4Auth(_credentials(), "bedrock", REGION).add_auth(signed)
    req = httpx.Request(method, url, headers=dict(signed.headers), content=body)
    with httpx.Client(timeout=600) as cli:
        res = cli.send(req)
    # cachy records 2xx only, and the probes for models this account cannot reach answer 403
    # limiting this to probes stops a failed call elsewhere from caching its own error
    if not 200 <= res.status_code < 300 and _probe(body):
        _remember(req, res)
    return res


class _Proxy(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("content-length") or 0))
        try:
            res = _forward("POST", self.path, body, self.headers.get("accept", ""))
            data, code = res.content, res.status_code
            keep = [(k, v) for k, v in res.headers.items() if k.lower() in KEEP]
        except Exception as e:
            data, code, keep = str(e).encode(), 502, [("content-type", "text/plain")]
        self.send_response(code)
        for k, v in keep:
            self.send_header(k, v)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def base_url() -> str:
    global _url
    with _lock:
        if _url is None:
            from cachy import enable_cachy, norm_pats

            norm_pats.append(BODY)
            norm_pats.append(ELAPSED)
            enable_cachy(
                cache_dir=str(ROOT), doms=(HOST,), debug=bool(os.getenv("CACHE_DEBUG"))
            )
            srv = ThreadingHTTPServer(("127.0.0.1", 0), _Proxy)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            _url = f"http://127.0.0.1:{srv.server_port}"
    return _url


def env() -> dict[str, str]:
    """Point the CLI subprocess at the recording proxy, so its model calls are cached."""
    return {"ANTHROPIC_BEDROCK_BASE_URL": base_url()} if ENABLED else {}
