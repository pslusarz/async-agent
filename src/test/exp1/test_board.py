from main.exp1.board import Thread


def test_children_render_next_to_their_question():
    t = Thread()
    q = t.post("user", "start the job")
    t.post("assistant", "starting", parent=q.id)
    a = t.post("user", "status?")
    t.post("assistant", "still going", parent=a.id)

    assert [p.text for p in t.walk()] == [
        "start the job",
        "starting",
        "status?",
        "still going",
    ]


def test_consecutive_same_role_posts_merge_into_one_message():
    t = Thread()
    q = t.post("user", "run the tool")
    call = t.post("assistant", "calling tool", parent=q.id)
    t.post("probe", "50% done", parent=call.id)
    t.post("probe", "100% done", parent=call.id)
    t.post("user", "thanks")

    assert t.render() == [
        dict(role="user", content=[dict(type="text", text="run the tool")]),
        dict(role="assistant", content=[dict(type="text", text="calling tool")]),
        dict(
            role="user",
            content=[
                dict(type="text", text="50% done"),
                dict(type="text", text="100% done"),
                dict(type="text", text="thanks"),
            ],
        ),
    ]


def test_tool_call_and_result_render_as_anthropic_blocks():
    t = Thread()
    q = t.post("user", "temp in Warsaw, MO?")
    call = t.post(
        "tool_call",
        parent=q.id,
        use_id="tu_1",
        name="temperature",
        input=dict(city="Warsaw", state="MO"),
    )
    t.post("tool_result", "72", parent=call.id, use_id="tu_1", done=True)

    assert t.render() == [
        dict(role="user", content=[dict(type="text", text="temp in Warsaw, MO?")]),
        dict(
            role="assistant",
            content=[
                dict(
                    type="tool_use",
                    id="tu_1",
                    name="temperature",
                    input=dict(city="Warsaw", state="MO"),
                )
            ],
        ),
        dict(
            role="user",
            content=[dict(type="tool_result", tool_use_id="tu_1", content="72")],
        ),
    ]
