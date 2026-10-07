import os
import subprocess
import time

import httpx
import pytest

URL = os.getenv("EXP9_SERVER", "http://127.0.0.1:2024")
BOOT = 120.0


def up() -> bool:
    try:
        return httpx.get(f"{URL}/ok", timeout=2).status_code == 200
    except Exception:
        return False


@pytest.fixture(scope="session")
def server() -> str:
    """The Agent Protocol server both graphs are registered on, started if not already."""
    if up():
        yield URL
        return
    p = subprocess.Popen(
        [
            "uv",
            "run",
            "langgraph",
            "dev",
            "--no-browser",
            "--no-reload",
            # every subagent and every wake-up holds a worker; too few and launches queue
            "--n-jobs-per-worker",
            "10",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        due = time.monotonic() + BOOT
        while time.monotonic() < due and not up():
            time.sleep(1)
        if not up():
            pytest.fail(f"no Agent Protocol server at {URL}")
        yield URL
    finally:
        p.terminate()
