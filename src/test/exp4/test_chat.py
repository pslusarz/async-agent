import time

import pytest

from main.exp4.chat import Chat

pytestmark = pytest.mark.live

REGARDING = "Regarding your earlier question"


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


def test_an_answer_that_follows_its_question_reads_plainly():
    chat = Chat()
    try:
        chat.say("Use the calendar agent to look up Joe's schedule.")

        assert until(chat, lambda c: agent_said(c, "Joe"))
        first = next(e for e in chat.entries() if e.role == "agent")
        assert not first.text.startswith(REGARDING)
    finally:
        chat.close()


def test_an_answer_arriving_out_of_order_says_what_it_is_about():
    chat = Chat()
    try:
        chat.say("Use the calendar agent to look up Joe's schedule.")
        assert until(chat, lambda c: any(e.kind == "TaskStarted" for e in c.events), timeout=60)

        chat.say("Meanwhile: what is 2+2? Answer with the number only.")
        assert until(chat, lambda c: agent_said(c, "4"), timeout=60)

        assert until(chat, lambda c: agent_said(c, REGARDING))
        entries = chat.entries()
        late = next(e for e in entries if REGARDING in e.text)
        assert "Joe's schedule" in late.text
        assert entries[-1].text == late.text
    finally:
        chat.close()
