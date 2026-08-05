import unittest
from unittest.mock import MagicMock, patch

from devctl.cli import build_parser, dispatch, main, subcommand_help


class CliTests(unittest.TestCase):
    def test_version_subcommand_registered(self) -> None:
        args = build_parser().parse_args(["version"])
        self.assertEqual("version", args.command)

    def test_version_flag(self) -> None:
        args = build_parser().parse_args(["--version"])
        self.assertTrue(args.version)

    def test_up_accepts_multiple_projects(self) -> None:
        args = build_parser().parse_args(["up", "a", "b"])
        self.assertEqual(["a", "b"], args.projects)

    def test_up_no_build_flag(self) -> None:
        args = build_parser().parse_args(["up", "--no-build", "a"])
        self.assertTrue(args.no_build)

    def test_up_build_flag(self) -> None:
        args = build_parser().parse_args(["up", "--build", "a"])
        self.assertTrue(args.build)

    def test_up_build_and_no_build_are_mutually_exclusive(self) -> None:
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["up", "--build", "--no-build", "a"])

    def test_up_json_flag(self) -> None:
        args = build_parser().parse_args(["up", "--json", "a"])
        self.assertTrue(args.json)

    def test_restart_subcommand_registered(self) -> None:
        args = build_parser().parse_args(["restart", "a"])
        self.assertEqual("restart", args.command)

    def test_profile_json_flag(self) -> None:
        args = build_parser().parse_args(["profile", "a", "--json"])
        self.assertEqual("profile", args.command)
        self.assertTrue(args.json)

    def test_open_subcommand_registered(self) -> None:
        args = build_parser().parse_args(["open", "a"])
        self.assertEqual("open", args.command)
        self.assertEqual("a", args.project)

    def test_prune_dry_run_flag(self) -> None:
        args = build_parser().parse_args(["prune", "--dry-run"])
        self.assertEqual("prune", args.command)
        self.assertTrue(args.dry_run)

    def test_doctor_json_flag(self) -> None:
        args = build_parser().parse_args(["doctor", "--json"])
        self.assertTrue(args.json)

    def test_doctor_fix_flags(self) -> None:
        args = build_parser().parse_args(["doctor", "--fix", "--dry-run"])
        self.assertTrue(args.fix)
        self.assertTrue(args.dry_run)

    def test_doctor_fix_defaults(self) -> None:
        args = build_parser().parse_args(["doctor"])
        self.assertFalse(args.fix)
        self.assertFalse(args.dry_run)

    def test_doctor_workspace_flag(self) -> None:
        args = build_parser().parse_args(["doctor", "--workspace"])
        self.assertTrue(args.workspace)

    def test_doctor_workspace_defaults_false(self) -> None:
        args = build_parser().parse_args(["doctor"])
        self.assertFalse(args.workspace)

    def test_no_color_flag(self) -> None:
        args = build_parser().parse_args(["--no-color", "list"])
        self.assertTrue(args.no_color)

    def test_gc_subcommand_registered(self) -> None:
        args = build_parser().parse_args(["gc"])
        self.assertEqual("gc", args.command)
        self.assertFalse(args.dry_run)
        self.assertFalse(args.yes)
        self.assertFalse(args.volumes)
        self.assertFalse(args.images)

    def test_gc_flags(self) -> None:
        args = build_parser().parse_args(["gc", "--dry-run", "--yes", "--volumes", "--images"])
        self.assertTrue(args.dry_run)
        self.assertTrue(args.yes)
        self.assertTrue(args.volumes)
        self.assertTrue(args.images)

    def test_exec_subcommand_registered(self) -> None:
        args = build_parser().parse_args(["exec", "app", "--service", "cms", "-T"])
        self.assertEqual("exec", args.command)
        self.assertEqual("app", args.project)
        self.assertEqual("cms", args.service)
        self.assertTrue(args.no_tty)

    def test_exec_defaults(self) -> None:
        args = build_parser().parse_args(["exec"])
        self.assertIsNone(args.project)
        self.assertIsNone(args.service)
        self.assertFalse(args.no_tty)

    @patch("devctl.cli.load_settings")
    @patch("devctl.commands.exec_command")
    def test_main_splits_argv_on_double_dash_for_exec(self, exec_mock, load_settings_mock) -> None:
        exec_mock.return_value = 3
        argv = ["exec", "app", "--service", "cms", "--", "ls", "-la"]
        with patch("sys.argv", ["devctl", *argv]):
            exit_code = main()

        self.assertEqual(3, exit_code)
        exec_mock.assert_called_once_with(
            load_settings_mock.return_value,
            "app",
            service="cms",
            tty=True,
            cmd=["ls", "-la"],
        )

    @patch("devctl.cli.load_settings")
    def test_main_exec_without_double_dash_raises(self, load_settings_mock) -> None:
        with patch("sys.argv", ["devctl", "exec", "app", "--service", "cms"]):
            exit_code = main()
        self.assertNotEqual(0, exit_code)

    @patch("devctl.cli.load_settings")
    @patch("devctl.commands.stats")
    def test_main_returns_130_when_command_interrupted(self, stats_mock, load_settings_mock) -> None:
        stats_mock.side_effect = KeyboardInterrupt
        with patch("sys.argv", ["devctl", "stats", "app"]):
            exit_code = main()
        self.assertEqual(130, exit_code)

    def test_stats_subcommand_registered(self) -> None:
        args = build_parser().parse_args(["stats", "app", "--json", "--no-stream"])
        self.assertEqual("stats", args.command)
        self.assertEqual("app", args.project)
        self.assertTrue(args.json)
        self.assertTrue(args.no_stream)

    def test_stats_defaults(self) -> None:
        args = build_parser().parse_args(["stats"])
        self.assertIsNone(args.project)
        self.assertFalse(args.json)
        self.assertFalse(args.no_stream)

    def test_logs_service_repeatable_and_since_tail(self) -> None:
        args = build_parser().parse_args(["logs", "app", "--service", "cms", "--service", "queue", "--since", "10m", "--tail", "50"])
        self.assertEqual(["cms", "queue"], args.services)
        self.assertEqual("10m", args.since)
        self.assertEqual(50, args.tail)

    def test_logs_defaults(self) -> None:
        args = build_parser().parse_args(["logs"])
        self.assertIsNone(args.services)
        self.assertIsNone(args.since)
        self.assertIsNone(args.tail)

    def test_release_stub_registered(self) -> None:
        args = build_parser().parse_args(["release", "1.2.3"])
        self.assertEqual("release", args.command)
        self.assertEqual("1.2.3", args.version)

    def test_make_stub_registered_with_passthrough_args(self) -> None:
        args = build_parser().parse_args(["make", "test", "V=1"])
        self.assertEqual("make", args.command)
        self.assertEqual(["test", "V=1"], args.args)

    def test_release_and_make_listed_in_help(self) -> None:
        helps = subcommand_help(build_parser())
        self.assertIn("release", helps)
        self.assertIn("make", helps)

    def test_release_and_make_dispatch_refuse_in_container(self) -> None:
        from devctl.errors import DevctlError

        for argv in (["release", "1.2.3"], ["make", "test"]):
            args = build_parser().parse_args(argv)
            with self.assertRaises(DevctlError) as ctx:
                dispatch(args, MagicMock(), None)
            self.assertEqual(2, ctx.exception.code)
            self.assertIn("wrapper", str(ctx.exception))


class DispatchTests(unittest.TestCase):
    @patch("devctl.commands.down")
    def test_dispatch_routes_down(self, down_mock) -> None:
        args = build_parser().parse_args(["down", "--all"])
        settings = MagicMock()
        code = dispatch(args, settings, None)
        self.assertEqual(0, code)
        down_mock.assert_called_once_with(settings, None, True)

    @patch("devctl.commands.exec_command")
    def test_dispatch_passes_exec_tail_and_exit_code(self, exec_mock) -> None:
        exec_mock.return_value = 5
        args = build_parser().parse_args(["exec", "app", "--service", "cms"])
        settings = MagicMock()
        code = dispatch(args, settings, ["ls", "-la"])
        self.assertEqual(5, code)
        exec_mock.assert_called_once_with(settings, "app", service="cms", tty=True, cmd=["ls", "-la"])


class SubcommandHelpTests(unittest.TestCase):
    def test_lists_every_subcommand_with_help(self) -> None:
        help_map = subcommand_help(build_parser())
        self.assertIn("up", help_map)
        self.assertIn("gc", help_map)
        self.assertEqual("start a project", help_map["up"])
        self.assertTrue(all(isinstance(text, str) for text in help_map.values()))


class ShellWiringTests(unittest.TestCase):
    def test_shell_subcommand_registered(self) -> None:
        args = build_parser().parse_args(["shell"])
        self.assertEqual("shell", args.command)

    @patch("devctl.cli.load_settings")
    @patch("devctl.shell.run_shell")
    def test_shell_subcommand_launches_shell(self, run_shell_mock, load_settings_mock) -> None:
        run_shell_mock.return_value = 7
        with patch("sys.argv", ["devctl", "shell"]):
            exit_code = main()
        self.assertEqual(7, exit_code)
        run_shell_mock.assert_called_once_with(load_settings_mock.return_value)

    @patch("devctl.cli.load_settings")
    @patch("devctl.shell.run_shell")
    def test_no_args_with_tty_launches_shell(self, run_shell_mock, load_settings_mock) -> None:
        run_shell_mock.return_value = 0
        with (
            patch("sys.argv", ["devctl"]),
            patch("sys.stdin") as stdin_mock,
            patch("sys.stdout") as stdout_mock,
        ):
            stdin_mock.isatty.return_value = True
            stdout_mock.isatty.return_value = True
            exit_code = main()
        self.assertEqual(0, exit_code)
        run_shell_mock.assert_called_once()

    @patch("devctl.cli.load_settings")
    def test_no_args_without_tty_prints_help_and_exits_2(self, load_settings_mock) -> None:
        with (
            patch("sys.argv", ["devctl"]),
            patch("sys.stdin") as stdin_mock,
        ):
            stdin_mock.isatty.return_value = False
            exit_code = main()
        self.assertEqual(2, exit_code)


class VersionHelperTests(unittest.TestCase):
    def test_get_version_returns_string(self) -> None:
        from devctl.commands import get_version

        self.assertIsInstance(get_version(), str)
        self.assertTrue(get_version())
