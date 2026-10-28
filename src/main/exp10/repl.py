"""Talk to the exp10 agent in a terminal and watch it answer on its own.

    LLM_CACHE=off uv run python -m main.exp10.repl

Each line you type is a message. The agent's words appear as it says them, including
the ones it says unprompted when work finishes. Type /log to see everything the
model was shown, /quit to leave.
"""

import threading

from .agent import Agent
from .tools import kill, tail, weather


def main():
    a = Agent(tools=[weather, tail, kill])
    shown = 0

    def follow():
        nonlocal shown
        while True:
            a.wait_until(lambda: len(a.transcript()) > shown, timeout=3600)
            said = a.transcript()
            for who, text in said[shown:]:
                if who == "agent":
                    print(f"\nagent: {text}\n> ", end="", flush=True)
            shown = len(said)

    threading.Thread(target=follow, daemon=True).start()
    while (line := input("> ").strip()) != "/quit":
        if line == "/log":
            for m in a.render():
                print(f"--- {m['role']}\n{m['content']}")
        elif line:
            a.post(line)
    a.stop()


if __name__ == "__main__":
    main()
