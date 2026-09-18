from main.exp2.agent import Agent
from main.exp2.chat import Chat
from main.exp3.app import SP, make_app
from main.exp3.tools import timed

# the two minute ceiling is for demos; tests settle in well under a second
FAST = timed(
    "build_time",
    "Find out how long the current build will take.",
    {},
    "12 minutes",
    due=(0.3, 0.6),
)


def test_a_real_tool_answer_arrives_in_the_browser_on_its_own(browse, serve_app):
    agent = Agent(sp=SP, tools=[FAST])
    url = serve_app(make_app(Chat(agent)))

    with browse(url) as page:
        page.fill("input[name=msg]", "how long will the build take?")
        page.click("button")

        page.wait_for_selector(".row.agent .bubble", timeout=30_000)

        # nobody touches the page; the timer fires and the answer shows up
        page.wait_for_selector("text=12 minutes", timeout=60_000)
        assert "task #" not in page.locator("#transcript").inner_text().lower()

    assert not agent.errors
