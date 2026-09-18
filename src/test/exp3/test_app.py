import threading
import time

from main.exp2.board import Board
from main.exp2.chat import Chat
from main.exp3.app import make_app


class FakeAgent:
    """Answers instantly, and can be told to speak later with nobody typing."""

    def __init__(self):
        self.board = Board()

    def post(self, text, parent=None):
        m = self.board.post("user", text, parent=parent)
        self.board.post("assistant", f"you said {text!r}", parent=m.id)
        return m

    def speak_later(self, text, after=0.3):
        def run():
            time.sleep(after)
            tail = self.board.walk(self.board.threads()[0].id)[-1]
            self.board.post("assistant", text, parent=tail.id)

        threading.Thread(target=run, daemon=True).start()


def open_chat(browse, serve_app, agent=None):
    agent = agent or FakeAgent()
    return browse(serve_app(make_app(Chat(agent))))


def test_the_page_starts_empty_with_a_composer(browse, serve_app):
    with open_chat(browse, serve_app) as page:
        assert page.locator("#transcript .bubble").count() == 0
        assert page.locator("input[name=msg]").is_visible()


def test_sending_a_message_shows_it_and_the_reply(browse, serve_app):
    with open_chat(browse, serve_app) as page:
        page.fill("input[name=msg]", "hello there")
        page.click("button")

        page.wait_for_selector(".row.user .bubble")
        assert page.locator(".row.user .bubble").inner_text() == "hello there"
        assert "hello there" in page.locator(".row.agent .bubble").inner_text()
        assert page.input_value("input[name=msg]") == ""


def test_an_unprompted_message_appears_without_the_user_doing_anything(browse, serve_app):
    agent = FakeAgent()
    with open_chat(browse, serve_app, agent) as page:
        page.fill("input[name=msg]", "how long will the build take?")
        page.click("button")
        page.wait_for_selector(".row.agent .bubble")
        before = page.locator(".bubble").count()

        agent.speak_later("The build will take 12 minutes.")

        # no clicking, no typing: the poll brings it in
        page.wait_for_selector("text=The build will take 12 minutes.", timeout=10_000)
        assert page.locator(".bubble").count() == before + 1


def test_the_transcript_never_shows_task_ids(browse, serve_app):
    with open_chat(browse, serve_app) as page:
        page.fill("input[name=msg]", "check the build")
        page.click("button")
        page.wait_for_selector(".row.agent .bubble")

        assert "task #" not in page.locator("#transcript").inner_text().lower()
