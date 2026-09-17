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
    n = b.post("assistant", "Let me look that up.", parent=q.id)
    c = b.add_call(n.id, "temperature", dict(city="Warsaw", state="MO"), actions=actions)
    return b, n, c


def test_placeholder_tells_the_agent_what_ran_and_how_to_inspect_it():
    b, n, c = pending()

    assert n.text == "Let me look that up."
    assert c.display == (
        f"[temperature(city='Warsaw', state='MO') is running as task #{c.id}. "
        f"You may inspect progress with tail(task={c.id}); terminate it with kill(task={c.id}). "
        "This placeholder will be replaced by the outcome when the task finishes or is killed.]"
    )
    assert n.display == f"Let me look that up.\n{c.display}"


def test_only_registered_meta_tools_are_offered():
    _, _, c = pending(actions=("tail",))
    assert f"tail(task={c.id})" in c.display
    assert "kill(task=" not in c.display

    _, _, c = pending(actions=())
    assert "You may" not in c.display
    assert "placeholder will be replaced" in c.display


def test_placeholder_is_replaced_by_the_result():
    b, n, c = pending()
    b.set_result(c.id, "72")

    assert c.display == "[temperature(city='Warsaw', state='MO') returned: 72]"
    assert "task #" not in c.display
    assert n.text == "Let me look that up."


def test_one_node_can_hold_several_placeholders():
    b = Board()
    q = b.post("user", "Warsaw and Springfield?")
    n = b.post("assistant", "Checking both.", parent=q.id)
    c1 = b.add_call(n.id, "temperature", dict(city="Warsaw"))
    c2 = b.add_call(n.id, "temperature", dict(city="Springfield"))

    assert not b.answered(q.id)
    b.set_result(c1.id, "72")
    assert not n.terminal and not b.answered(q.id)

    b.set_result(c2.id, "68")
    assert n.terminal
    assert not b.answered(q.id)          # filled, but nobody has said anything

    b.post("assistant", "72 and 68.", parent=n.id)
    assert b.answered(q.id)


def test_a_reply_to_a_pending_task_says_which_task_it_refers_to():
    b, n, c = pending()
    f = b.post("user", "Do you know the answer yet?", parent=n.id)

    def line():
        return next(m["content"] for m in b.render() if f"[#{f.id}]" in m["content"])

    assert f"[this message is in reference to task #{c.id} started earlier]" in line()

    b.set_result(c.id, "72")
    assert f"[this message is in reference to task #{c.id}, which already returned: 72]" in line()
