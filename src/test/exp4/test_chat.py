import time

import pytest

from main.exp4.chat import Chat

pytestmark = pytest.mark.live


def until(chat, pred, timeout=150):
    end = time.time() + timeout
    while time.time() < end:
        if pred(chat):
            return True
        time.sleep(0.2)
    return False


def agent_said(chat, needle):
    return any(needle in e.text for e in chat.entries() if e.role == "agent")


def test_the_transcript_is_plain_roles_and_text():
    chat = Chat()
    try:
        chat.say("What is 2+2? Answer with the number only.")

        assert until(chat, lambda c: agent_said(c, "4"), timeout=60)
        roles = [e.role for e in chat.entries()]
        assert roles[0] == "user" and "agent" in roles
        assert {f for f in vars(chat.entries()[0])} == {"role", "text", "at"}
    finally:
        chat.close()


def test_a_late_answer_stands_on_its_own():
    """Nothing here attributes a late answer to the question it serves.

    The transcript is linear and complete, so when the task lands the agent can
    see that the conversation moved on, and reintroduces the subject unasked.
    """
    chat = Chat()
    try:
        chat.say("Use the calendar agent to look up Joe's schedule.")
        assert until(chat, lambda c: any(e.kind == "TaskStarted" for e in c.events), timeout=60)

        chat.say("Meanwhile, what is the capital of France?")
        assert until(chat, lambda c: agent_said(c, "Paris"), timeout=60)

        assert until(chat, lambda c: agent_said(c, "11am"))
        texts = [e.text for e in chat.entries()]
        assert any("Paris" in t for t in texts)
        # the agent names the subject itself; the host does nothing
        assert "Joe" in texts[-1]
    finally:
        chat.close()
