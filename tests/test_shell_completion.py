import unittest

from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document

from devctl.cli import build_parser
from devctl.shell.completion import DevctlCompleter, build_completer

from .helpers import TempDirTestCase, make_settings


def completions(completer: DevctlCompleter, text: str) -> list[str]:
    document = Document(text, cursor_position=len(text))
    return [completion.text for completion in completer.get_completions(document, CompleteEvent())]


def make_completer(projects=("example-web", "example-api")) -> DevctlCompleter:
    return DevctlCompleter(["up", "gc", "status"], ["help", "exit"], lambda: list(projects))


class DevctlCompleterTests(unittest.TestCase):
    def test_first_word_completes_commands(self) -> None:
        self.assertEqual(["up"], completions(make_completer(), "u"))

    def test_first_word_completes_slash_metas(self) -> None:
        self.assertEqual(["/exit"], completions(make_completer(), "/e"))

    def test_second_word_completes_project_names(self) -> None:
        self.assertEqual(["example-api", "example-web"], sorted(completions(make_completer(), "up ex")))

    def test_flags_are_not_completed(self) -> None:
        self.assertEqual([], completions(make_completer(), "up --n"))

    def test_project_provider_errors_yield_no_completions(self) -> None:
        def broken() -> list[str]:
            raise RuntimeError("no registry yet")

        completer = DevctlCompleter(["up"], ["help"], broken)
        self.assertEqual([], completions(completer, "up ex"))


class BuildCompleterTests(TempDirTestCase):
    def test_includes_cli_commands_but_not_shell(self) -> None:
        completer = build_completer(build_parser(), make_settings(self.tmp_path))
        self.assertIn("up", completions(completer, "u"))
        self.assertEqual([], completions(completer, "shel"))

    def test_uninitialized_registry_does_not_break_completion(self) -> None:
        completer = build_completer(build_parser(), make_settings(self.tmp_path))
        self.assertEqual([], completions(completer, "up ex"))
