from main.exp2.board import Board


def build():
    b = Board()
    q1 = b.post("user", "capital of France?")
    a1 = b.post("assistant", "Paris.", parent=q1.id)
    q2 = b.post("user", "favorite color is blue")
    a2 = b.post("assistant", "Noted.", parent=q2.id)
    return b, q1, a1, q2, a2


def test_reply_nests_under_its_parent():
    b, q1, a1, _, _ = build()
    f = b.post("user", "population?", parent=a1.id)

    assert b[a1.id].children == [f.id]
    assert b.root_of(f.id) == q1.id
    assert [m.id for m in b.walk(q1.id)] == [q1.id, a1.id, f.id]


def test_threads_order_by_most_recent_activity_last():
    b, q1, a1, q2, a2 = build()
    assert [t.id for t in b.threads()] == [q1.id, q2.id]

    b.post("user", "population?", parent=a1.id)
    assert [t.id for t in b.threads()] == [q2.id, q1.id]


def test_every_message_is_its_own_chat_message_with_a_tree_prefix():
    b, q1, a1, q2, a2 = build()
    f = b.post("user", "population?", parent=a1.id)
    msgs = b.render()

    assert [m["role"] for m in msgs] == [
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
    ]
    assert msgs[0]["content"] == f"+-- [#{q2.id}] favorite color is blue"
    assert msgs[1]["content"] == f"|   +-- [#{a2.id}] Noted."
    assert msgs[2]["content"] == f"+-- [#{q1.id}] capital of France?"
    assert msgs[3]["content"] == f"|   +-- [#{a1.id}] Paris."
    assert msgs[4]["content"] == f"|   |   +-- [#{f.id}] population?"


def test_a_focus_pointer_is_added_only_when_the_target_is_not_last():
    b = Board()
    q = b.post("user", "q")
    a = b.post("assistant", "a", parent=q.id)
    one = b.post("user", "branch one", parent=a.id)
    b.post("assistant", "answer one", parent=one.id)
    two = b.post("user", "branch two", parent=a.id)

    assert not b.render(focus=two.id)[-1]["content"].startswith("Respond to")
    assert b.render(focus=one.id)[-1] == dict(
        role="user", content=f"Respond to [#{one.id}]."
    )


def test_nothing_is_snipped():
    b, q1, a1, q2, a2 = build()
    b.post("user", "population?", parent=a1.id)
    dump = "".join(m["content"] for m in b.render())

    for m in b.msgs.values():
        assert m.text in dump


def pending(actions=("tail", "kill")):
    b = Board()
    q = b.post("user", "temperature in Warsaw, MO?")
    n = b.post(
        "assistant",
        "Tool called, please follow up for an answer",
        parent=q.id,
        tool="temperature",
        args=dict(city="Warsaw", state="MO"),
        actions=actions,
    )
    return b, n


def test_placeholder_tells_the_agent_what_ran_and_how_to_inspect_it():
    b, n = pending()

    assert n.text == "Tool called, please follow up for an answer"
    assert n.display == (
        f"[temperature(city='Warsaw', state='MO') is running as task #{n.id}. "
        f"You may inspect progress with tail(task={n.id}); terminate it with kill(task={n.id}). "
        "This placeholder will be replaced by the outcome when the task finishes or is killed.]"
    )


def test_only_registered_meta_tools_are_offered():
    _, n = pending(actions=("tail",))
    assert f"tail(task={n.id})" in n.display
    assert "kill(task=" not in n.display

    _, n = pending(actions=())
    assert "You may" not in n.display
    assert "placeholder will be replaced" in n.display


def test_placeholder_is_replaced_by_the_result():
    b, n = pending()
    b.set_result(n.id, "72")

    assert n.display == "[temperature(city='Warsaw', state='MO') returned: 72]"
    assert "task #" not in n.display
    assert n.text == "Tool called, please follow up for an answer"


def test_a_reply_to_a_pending_task_says_which_task_it_refers_to():
    b, n = pending()
    f = b.post("user", "Do you know the answer yet?", parent=n.id)

    def line():
        return next(m["content"] for m in b.render() if f"[#{f.id}]" in m["content"])

    assert f"[this message is in reference to task #{n.id} started earlier]" in line()

    b.set_result(n.id, "72")
    assert f"[this message is in reference to task #{n.id}, which already returned: 72]" in line()
