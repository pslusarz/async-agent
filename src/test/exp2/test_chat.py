from main.exp2.board import Board
from main.exp2.chat import Chat


class Stub:
    def __init__(self):
        self.board = Board()

    def post(self, text, parent=None):
        return self.board.post("user", text, parent=parent)


def lines(c):
    return [(e.role, e.text) for e in c.entries()]


def test_a_reply_that_follows_its_question_reads_plainly():
    a = Stub()
    c = Chat(a)
    c.say("what is the capital of France?")
    q = a.board.msgs[1]
    a.board.post("assistant", "Paris.", parent=q.id)

    assert lines(c) == [
        ("user", "what is the capital of France?"),
        ("agent", "Paris."),
    ]


def test_an_answer_arriving_out_of_order_says_what_it_is_about():
    a = Stub()
    c = Chat(a)
    c.say("how long will the build take?")
    slow = a.board.msgs[1]
    node = a.board.post("assistant", "", parent=slow.id)
    call = a.board.add_call(node.id, "build_time", {})

    c.say("meanwhile, what is 2+2?")
    quick = a.board.walk(slow.id)[-1]
    a.board.post("assistant", "4.", parent=quick.id)

    a.board.set_result(call.id, "12 minutes")
    a.board.post("assistant", "It will take 12 minutes.", parent=node.id)

    assert lines(c) == [
        ("user", "how long will the build take?"),
        ("user", "meanwhile, what is 2+2?"),
        ("agent", "4."),
        (
            "agent",
            "Regarding your earlier question, 'how long will the build take?': "
            "It will take 12 minutes.",
        ),
    ]


def test_the_transcript_exposes_nothing_but_role_text_and_time():
    a = Stub()
    c = Chat(a)
    c.say("hello")
    a.board.post("assistant", "hi", parent=a.board.msgs[1].id)

    assert {f for f in vars(c.entries()[0])} == {"role", "text", "at"}


def test_empty_before_anything_is_said():
    assert Chat(Stub()).entries() == []
