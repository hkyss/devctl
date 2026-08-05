import argparse
from collections.abc import Callable
from dataclasses import dataclass

from rich.console import Console

from ..settings import Settings
from . import ui


@dataclass
class ShellContext:
    console: Console
    settings: Settings
    parser: argparse.ArgumentParser
    should_exit: bool = False


@dataclass(frozen=True)
class MetaCommand:
    handler: Callable[[ShellContext], None]
    description: str
    aliases: tuple[str, ...] = ()


def _help(ctx: ShellContext) -> None:
    from ..cli import subcommand_help

    command_rows = sorted((name, text) for name, text in subcommand_help(ctx.parser).items() if name != "shell")
    meta_rows = [(f"/{name}", command.description) for name, command in sorted(META_COMMANDS.items())]
    ui.help_table(ctx.console, command_rows, meta_rows)


def _clear(ctx: ShellContext) -> None:
    ctx.console.clear()


def _exit(ctx: ShellContext) -> None:
    ctx.should_exit = True


META_COMMANDS: dict[str, MetaCommand] = {
    "help": MetaCommand(_help, "show available commands"),
    "clear": MetaCommand(_clear, "clear the screen"),
    "exit": MetaCommand(_exit, "leave the shell", aliases=("quit",)),
}


def find_meta(name: str) -> MetaCommand | None:
    command = META_COMMANDS.get(name)
    if command is not None:
        return command
    for candidate in META_COMMANDS.values():
        if name in candidate.aliases:
            return candidate
    return None


def meta_names() -> list[str]:
    names = list(META_COMMANDS)
    for command in META_COMMANDS.values():
        names.extend(command.aliases)
    return sorted(names)
