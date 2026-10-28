from ..exp2.tools import TEMPERATURE, Countdown, Tool
from ..exp5.tools import kill, stuck_temperature, tail

__all__ = ["kill", "tail", "stuck_temperature", "weather"]

# picked so the two cities in one question finish a few seconds apart
TEMPS = {"columbia": ("81", 3.0), "washington": ("64", 6.0)}


def _weather(city: str, state: str):
    value, seconds = TEMPS.get(city.strip().lower(), ("72", 3.0))
    return Countdown(value, seconds)


weather = Tool(TEMPERATURE, _weather)
