from main.exp2.agent import Agent

SP = "Answer in one short sentence."


def test_post_returns_immediately_and_wait_for_returns_the_answer():
    a = Agent(sp=SP)
    q = a.post("What is the capital of France?")

    assert q.role == "user"
    assert q.parent is None

    r = a.wait_for(q)
    assert "Paris" in r.text
    assert a.board[r.parent].id == q.id


def test_wait_for_accepts_a_string_and_posts_it():
    a = Agent(sp=SP)
    r = a.wait_for("What is the capital of France?")

    assert "Paris" in r.text
    assert a.board[r.parent].text == "What is the capital of France?"


def test_two_questions_can_be_posted_before_either_is_answered():
    a = Agent(sp=SP)
    q1 = a.post("What is the capital of France?")
    q2 = a.post("What is the capital of Japan?")

    assert a.board.root_of(q1.id) != a.board.root_of(q2.id)
    assert "Paris" in a.wait_for(q1).text
    assert "Tokyo" in a.wait_for(q2).text


def test_followup_by_id_nests_under_the_reply():
    a = Agent(sp=SP)
    r1 = a.wait_for("What is the capital of France?")
    r2 = a.wait_for("What is its population?", parent=r1.id)

    assert a.board[r2.parent].parent == r1.id
    assert a.board.root_of(r2.id) == a.board.root_of(r1.id)
    assert "million" in r2.text.lower() or "2" in r2.text


def test_agent_answers_from_another_thread_that_was_not_snipped():
    a = Agent(sp=SP)
    a.wait_for("Remember: my favorite color is chartreuse.")
    a.wait_for("What is the capital of France?")
    r = a.wait_for("What is my favorite color?")

    assert "chartreuse" in r.text.lower()
    assert len(a.board.threads()) == 3


def test_the_thread_being_replied_to_moves_to_the_bottom():
    a = Agent(sp=SP)
    r1 = a.wait_for("What is the capital of France?")
    a.wait_for("What is the capital of Japan?")
    a.wait_for("What is its population?", parent=r1.id)

    assert a.board.threads()[-1].id == a.board.root_of(r1.id)
