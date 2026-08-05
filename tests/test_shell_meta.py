import unittest

from rich.console import Console

from devctl.cli import build_parser
from devctl.shell.meta import META_COMMANDS, ShellContext, find_meta, meta_names


def make_ctx() -> ShellContext:
    console = Console(record=True, width=100, force_terminal=False, no_color=True)
    return ShellContext(console=console, settings=None, parser=build_parser())


class MetaTests(unittest.TestCase):
    def test_registry_has_core_commands(self) -> None:
        self.assertIn("help", META_COMMANDS)
        self.assertIn("clear", META_COMMANDS)
        self.assertIn("exit", META_COMMANDS)

    def test_find_meta_resolves_aliases(self) -> None:
        self.assertIs(META_COMMANDS["exit"], find_meta("quit"))
        self.assertIsNone(find_meta("nope"))

    def test_meta_names_include_aliases(self) -> None:
        names = meta_names()
        for expected in ("help", "clear", "exit", "quit"):
            self.assertIn(expected, names)

    def test_exit_sets_should_exit(self) -> None:
        ctx = make_ctx()
        META_COMMANDS["exit"].handler(ctx)
        self.assertTrue(ctx.should_exit)

    def test_help_lists_cli_and_meta_commands(self) -> None:
        ctx = make_ctx()
        META_COMMANDS["help"].handler(ctx)
        text = ctx.console.export_text()
        self.assertIn("up", text)
        self.assertIn("/exit", text)

    def test_clear_does_not_exit(self) -> None:
        ctx = make_ctx()
        META_COMMANDS["clear"].handler(ctx)
        self.assertFalse(ctx.should_exit)
