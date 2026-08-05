from contextlib import redirect_stderr
from io import StringIO
from unittest.mock import Mock, patch

from devctl.errors import DevctlError
from devctl.runtime import compose_file, ensure_runtime, is_proxy_running, reload_proxy

from .helpers import TempDirTestCase, make_settings


class RuntimeTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.settings = make_settings(self.tmp_path)
        compose_dir = self.settings.repo_root / ".docker"
        compose_dir.mkdir(parents=True)
        (compose_dir / "docker-compose.yml").write_text("name: devctl\nservices: {}\n", encoding="utf-8")

    @patch("devctl.runtime.subprocess.run")
    def test_is_proxy_running_true_when_compose_reports_service(self, run_mock) -> None:
        run_mock.return_value.returncode = 0
        run_mock.return_value.stdout = "container-id\n"

        self.assertTrue(is_proxy_running(self.settings))

    @patch("devctl.runtime.subprocess.run")
    def test_is_proxy_running_false_when_compose_reports_nothing(self, run_mock) -> None:
        run_mock.return_value.returncode = 0
        run_mock.return_value.stdout = ""

        self.assertFalse(is_proxy_running(self.settings))

    @patch("devctl.runtime.is_proxy_running", return_value=True)
    @patch("devctl.runtime.subprocess.run")
    def test_ensure_runtime_skips_boot_when_proxy_is_running(self, run_mock, _proxy_mock) -> None:
        ensure_runtime(self.settings)

        run_mock.assert_not_called()

    @patch("devctl.commands.bootstrap")
    @patch("devctl.runtime.is_proxy_running", side_effect=[False, True])
    @patch("devctl.runtime.subprocess.run")
    def test_ensure_runtime_builds_bootstraps_and_starts_caddy(self, run_mock, _proxy_mock, bootstrap_mock) -> None:
        run_mock.return_value.returncode = 0

        ensure_runtime(self.settings)

        bootstrap_mock.assert_called_once_with(self.settings)
        commands = [call.args[0] for call in run_mock.call_args_list]
        compose = compose_file(self.settings)
        self.assertEqual(["docker", "compose", "-f", compose, "build", "devctl"], commands[0])
        self.assertEqual(["docker", "compose", "-f", compose, "up", "-d", "caddy"], commands[1])

    @patch.dict("os.environ", {"DEVCTL_SKIP_BOOT": "1"})
    @patch("devctl.runtime.is_proxy_running", return_value=False)
    @patch("devctl.runtime.subprocess.run")
    def test_ensure_runtime_honors_skip_env(self, run_mock, _proxy_mock) -> None:
        ensure_runtime(self.settings)

        run_mock.assert_not_called()

    def test_ensure_runtime_fails_when_compose_file_is_missing(self) -> None:
        (self.settings.repo_root / ".docker" / "docker-compose.yml").unlink()

        with self.assertRaises(DevctlError):
            ensure_runtime(self.settings)

    @patch("devctl.runtime.is_proxy_running", return_value=False)
    @patch("devctl.runtime.subprocess.run")
    def test_reload_proxy_does_nothing_without_a_running_proxy(self, run_mock, _proxy_mock) -> None:
        reload_proxy(self.settings)

        run_mock.assert_not_called()

    @patch("devctl.runtime.is_proxy_running", return_value=True)
    @patch("devctl.runtime.subprocess.run")
    def test_reload_proxy_pushes_the_caddyfile_into_the_proxy(self, run_mock, _proxy_mock) -> None:
        run_mock.return_value.returncode = 0

        reload_proxy(self.settings)

        compose = compose_file(self.settings)
        self.assertEqual(
            ["docker", "compose", "-f", compose, "exec", "-T", "caddy", "caddy", "reload", "--config", "/state/Caddyfile"],
            run_mock.call_args.args[0],
        )

    @patch("devctl.runtime.time.sleep")
    @patch("devctl.runtime.is_proxy_running", return_value=True)
    @patch("devctl.runtime.subprocess.run")
    def test_reload_proxy_retries_while_the_admin_endpoint_boots(self, run_mock, _proxy_mock, _sleep_mock) -> None:
        run_mock.side_effect = [
            Mock(returncode=1, stdout="", stderr="dial tcp: connection refused"),
            Mock(returncode=0, stdout="", stderr=""),
        ]

        reload_proxy(self.settings)

        self.assertEqual(2, run_mock.call_count)

    @patch("devctl.runtime.time.sleep")
    @patch("devctl.runtime.is_proxy_running", return_value=True)
    @patch("devctl.runtime.subprocess.run")
    def test_reload_proxy_warns_instead_of_aborting_the_command(self, run_mock, _proxy_mock, _sleep_mock) -> None:
        run_mock.return_value = Mock(returncode=1, stdout="", stderr="adapt: unexpected token")

        stderr = StringIO()
        with redirect_stderr(stderr):
            reload_proxy(self.settings)

        self.assertIn("unexpected token", stderr.getvalue())
