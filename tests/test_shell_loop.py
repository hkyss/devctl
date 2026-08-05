import io
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from rich.console import Console

from devctl.cli import build_parser
from devctl.errors import DevctlError
from devctl.shell.loop import run_shell

from .helpers import TempDirTestCase, make_settings


def scripted_prompt(lines):
    iterator = iter(lines)

    def prompt() -> str:
        try:
            item = next(iterator)
        except StopIteration:
            raise EOFError from None
        if isinstance(item, BaseException):
            raise item
        return item

    return prompt


class RunShellTests(TempDirTestCase):
    def run_lines(self, lines) -> tuple[int, str]:
        console = Console(record=True, width=100, force_terminal=False, no_color=True)
        settings = make_settings(self.tmp_path)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = run_shell(settings, console=console, prompt=scripted_prompt(lines), parser=build_parser())
        return code, console.export_text()

    def test_exit_meta_leaves_shell_with_banner_and_goodbye(self) -> None:
        code, output = self.run_lines(["/exit"])
        self.assertEqual(0, code)
        self.assertIn("devctl v", output)
        self.assertIn("bye", output)

    def test_quit_alias_leaves_shell(self) -> None:
        code, _ = self.run_lines(["/quit"])
        self.assertEqual(0, code)

    def test_eof_leaves_shell(self) -> None:
        code, output = self.run_lines([])
        self.assertEqual(0, code)
        self.assertIn("bye", output)

    def test_command_prints_success_footer(self) -> None:
        code, output = self.run_lines(["version", "/exit"])
        self.assertEqual(0, code)
        self.assertIn("✔ version", output)

    def test_unknown_slash_command_hints_and_continues(self) -> None:
        code, output = self.run_lines(["/nope", "/exit"])
        self.assertEqual(0, code)
        self.assertIn("unknown command /nope", output)

    def test_bad_flags_report_exit_2_and_keep_loop_alive(self) -> None:
        code, output = self.run_lines(["up --bogus", "/exit"])
        self.assertEqual(0, code)
        self.assertIn("exit 2", output)

    def test_unbalanced_quotes_report_error_and_keep_loop_alive(self) -> None:
        code, output = self.run_lines(['up "broken', "/exit"])
        self.assertEqual(0, code)
        self.assertIn("error:", output)

    def test_devctl_error_is_reported_with_exit_code(self) -> None:
        with patch("devctl.shell.loop.dispatch", side_effect=DevctlError("boom", 3)):
            code, output = self.run_lines(["status app", "/exit"])
        self.assertEqual(0, code)
        self.assertIn("boom", output)
        self.assertIn("exit 3", output)

    def test_keyboard_interrupt_during_command_reports_130(self) -> None:
        with patch("devctl.shell.loop.dispatch", side_effect=KeyboardInterrupt):
            code, output = self.run_lines(["status app", "/exit"])
        self.assertEqual(0, code)
        self.assertIn("exit 130", output)

    def test_keyboard_interrupt_at_prompt_continues(self) -> None:
        code, _ = self.run_lines([KeyboardInterrupt(), "/exit"])
        self.assertEqual(0, code)

    def test_nested_shell_command_prints_hint(self) -> None:
        code, output = self.run_lines(["shell", "/exit"])
        self.assertEqual(0, code)
        self.assertIn("already in the shell", output)

    def test_empty_lines_are_ignored(self) -> None:
        code, output = self.run_lines(["", "   ", "/exit"])
        self.assertEqual(0, code)
        self.assertNotIn("✘", output)
