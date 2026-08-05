import shlex
from dataclasses import dataclass, field
from typing import Literal

Kind = Literal["empty", "meta", "command"]


@dataclass(frozen=True)
class ParsedLine:
    kind: Kind
    name: str = ""
    args: list[str] = field(default_factory=list)
    exec_cmd: list[str] | None = None


def parse_line(line: str) -> ParsedLine:
    stripped = line.strip()
    if not stripped:
        return ParsedLine(kind="empty")
    tokens = shlex.split(stripped)
    if stripped.startswith("/"):
        return ParsedLine(kind="meta", name=tokens[0][1:], args=tokens[1:])
    exec_cmd: list[str] | None = None
    if "--" in tokens:
        separator = tokens.index("--")
        exec_cmd = tokens[separator + 1 :]
        tokens = tokens[:separator]
    return ParsedLine(kind="command", name=tokens[0], args=tokens, exec_cmd=exec_cmd)
