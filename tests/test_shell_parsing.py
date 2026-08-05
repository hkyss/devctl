import unittest

from devctl.shell.parsing import parse_line


class ParseLineTests(unittest.TestCase):
    def test_blank_line_is_empty(self) -> None:
        self.assertEqual("empty", parse_line("   ").kind)

    def test_meta_command_without_args(self) -> None:
        parsed = parse_line("/help")
        self.assertEqual("meta", parsed.kind)
        self.assertEqual("help", parsed.name)
        self.assertEqual([], parsed.args)

    def test_meta_command_with_args(self) -> None:
        parsed = parse_line("/help up")
        self.assertEqual("help", parsed.name)
        self.assertEqual(["up"], parsed.args)

    def test_plain_command_keeps_full_argv(self) -> None:
        parsed = parse_line("up example-web --no-build")
        self.assertEqual("command", parsed.kind)
        self.assertEqual("up", parsed.name)
        self.assertEqual(["up", "example-web", "--no-build"], parsed.args)
        self.assertIsNone(parsed.exec_cmd)

    def test_double_dash_splits_exec_tail(self) -> None:
        parsed = parse_line("exec app --service cms -- ls -la")
        self.assertEqual(["exec", "app", "--service", "cms"], parsed.args)
        self.assertEqual(["ls", "-la"], parsed.exec_cmd)

    def test_quoted_arguments(self) -> None:
        parsed = parse_line('logs "my app"')
        self.assertEqual(["logs", "my app"], parsed.args)

    def test_unbalanced_quote_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            parse_line('up "broken')
