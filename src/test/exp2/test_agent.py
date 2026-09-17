from main.exp2.agent import Agent

SP = "Answer in one short sentence."


def test_answer_comes_back_with_a_message_id():
    a = Agent(sp=SP)
    r = a.post("What is the capital of France?")

    assert "Paris" in r.text
    assert r.id in a.board.msgs
    assert a.board[r.id].role == "assistant"
    assert r.parent == a.board.root_of(r.id)


def test_followup_by_id_nests_under_the_reply():
    a = Agent(sp=SP)
    r1 = a.post("What is the capital of France?")
    r2 = a.post("What is its population?", parent=r1.id)

    assert a.board[r2.parent].parent == r1.id
    assert a.board.root_of(r2.id) == a.board.root_of(r1.id)
    assert "million" in r2.text.lower() or "2" in r2.text


def test_question_without_an_id_starts_a_new_thread():
    a = Agent(sp=SP)
    r1 = a.post("What is the capital of France?")
    r2 = a.post("What is the capital of Japan?")

    assert a.board.root_of(r1.id) != a.board.root_of(r2.id)
    assert len(a.board.threads()) == 2
    assert "Tokyo" in r2.text


def test_agent_answers_from_another_thread_that_was_not_snipped():
    a = Agent(sp=SP)
    a.post("Remember: my favorite color is chartreuse.")
    a.post("What is the capital of France?")
    r = a.post("What is my favorite color?")

    assert "chartreuse" in r.text.lower()
    assert len(a.board.threads()) == 3


def test_the_thread_being_replied_to_moves_to_the_bottom():
    a = Agent(sp=SP)
    r1 = a.post("What is the capital of France?")
    a.post("What is the capital of Japan?")
    a.post("What is its population?", parent=r1.id)

    assert a.board.threads()[-1].id == a.board.root_of(r1.id)
    last_user = [m for m in a.board.render() if m["role"] == "user"][-1]
    assert last_user["content"].endswith("What is its population?")
