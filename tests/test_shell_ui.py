import unittest
from pathlib import Path

from rich.console import Console

from devctl.shell import ui


def make_console() -> Console:
    return Console(record=True, width=100, force_terminal=False, no_color=True)


class UiTests(unittest.TestCase):
    def test_banner_shows_version_workspace_and_count(self) -> None:
        console = make_console()
        ui.banner(console, version="9.9.9", workspace_root=Path("/ws/github"), project_count=3)
        text = console.export_text()
        self.assertIn("devctl v9.9.9", text)
        self.assertIn("/ws/github", text)
        self.assertIn("3 project(s)", text)
        self.assertIn("/help", text)

    def test_footer_success(self) -> None:
        console = make_console()
        ui.footer(console, label="up example-web", exit_code=0, seconds=1.23)
        self.assertIn("✔ up example-web · 1.2s", console.export_text())

    def test_footer_failure_includes_exit_code(self) -> None:
        console = make_console()
        ui.footer(console, label="up", exit_code=1, seconds=0.51)
        self.assertIn("✘ up · exit 1 · 0.5s", console.export_text())

    def test_error_line(self) -> None:
        console = make_console()
        ui.error_line(console, "boom")
        self.assertIn("error: boom", console.export_text())

    def test_help_table_lists_commands_and_metas(self) -> None:
        console = make_console()
        ui.help_table(console, [("up", "start a project")], [("/exit", "leave the shell")])
        text = console.export_text()
        self.assertIn("up", text)
        self.assertIn("start a project", text)
        self.assertIn("/exit", text)
