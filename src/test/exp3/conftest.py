import socket
import threading
import time
from contextlib import contextmanager

import pytest
import uvicorn
from playwright.sync_api import sync_playwright


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def serve_app():
    servers = []

    def start(app):
        port = free_port()
        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
        )
        threading.Thread(target=server.run, daemon=True).start()
        servers.append(server)
        end = time.time() + 10
        while time.time() < end and not server.started:
            time.sleep(0.02)
        assert server.started, "server did not start"
        return f"http://127.0.0.1:{port}"

    yield start
    for s in servers:
        s.should_exit = True


@pytest.fixture
def browse():
    """Drive a page, opening and closing playwright inside the test.

    The pytest-playwright plugins keep a session-scoped event loop alive, which
    stops pytest-asyncio from running exp1's async tests in the same worker.
    """

    @contextmanager
    def go(url):
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page()
                page.goto(url)
                yield page
            finally:
                browser.close()

    return go
