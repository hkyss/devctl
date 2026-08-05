import os
import sys

COLORS = {
    "blue": "34",
    "cyan": "36",
    "green": "32",
    "red": "31",
    "yellow": "33",
}


def supports_color(stream=sys.stdout) -> bool:
    return "NO_COLOR" not in os.environ and stream.isatty()


def color(text: str, name: str, stream=sys.stdout) -> str:
    if not supports_color(stream):
        return text
    code = COLORS.get(name)
    if not code:
        return text
    return f"\033[{code}m{text}\033[0m"


def info(text: str) -> str:
    return color(text, "cyan")


def step(text: str) -> str:
    return color(text, "blue")


def success(text: str) -> str:
    return color(text, "green")


def warning(text: str) -> str:
    return color(text, "yellow")


def error(text: str) -> str:
    return color(text, "red", stream=sys.stderr)
