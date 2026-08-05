import fcntl
import io
from contextlib import redirect_stdout
from unittest.mock import patch

from devctl.commands import up
from devctl.errors import DevctlError
from devctl.profiles import ExtraRoute
from devctl.registry import Registry

from .helpers import TempDirTestCase, make_profile, make_settings


class UpLockScopeTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.settings = make_settings(self.tmp_path)
        Registry(self.settings).ensure()
        self.project_dir = self.tmp_path / "app"
        self.project_dir.mkdir(parents=True)

    def test_lock_released_before_health_check(self) -> None:
        held = {"during_health_check": None}

        def fake_wait_for_port(host, port, timeout):
            with self.settings.lock_path.open("w") as probe:
                try:
                    fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    held["during_health_check"] = False
                    fcntl.flock(probe.fileno(), fcntl.LOCK_UN)
                except BlockingIOError:
                    held["during_health_check"] = True
            return True, None

        profile = make_profile(path=str(self.project_dir))
        with (
            patch("devctl.commands.ensure_runtime"),
            patch("devctl.commands.resolve_profile", return_value=profile),
            patch("devctl.commands.adapter_for") as adapter_mock,
            patch("devctl.commands.wait_for_port", side_effect=fake_wait_for_port),
            patch("devctl.commands.CaddyfileWriter"),
        ):
            adapter = adapter_mock.return_value
            adapter.command_up.return_value = ["docker", "compose", "up"]
            adapter.command_pre_up.side_effect = lambda c: ["docker", "compose", "run", *c]
            adapter.up.return_value = 0
            up(self.settings, None)

        self.assertEqual(False, held["during_health_check"])

    def test_start_failure_marks_service_unhealthy(self) -> None:
        profile = make_profile(path=str(self.project_dir))
        registry = Registry(self.settings)
        with (
            patch("devctl.commands.ensure_runtime"),
            patch("devctl.commands.resolve_profile", return_value=profile),
            patch("devctl.commands.adapter_for") as adapter_mock,
            patch("devctl.commands.CaddyfileWriter"),
        ):
            adapter = adapter_mock.return_value
            adapter.command_up.return_value = ["docker", "compose", "up"]
            adapter.command_pre_up.side_effect = lambda c: ["docker", "compose", "run", *c]
            adapter.up.return_value = 1
            with self.assertRaises(DevctlError):
                up(self.settings, None)

        services = registry.services()
        self.assertEqual(1, len(services))
        self.assertEqual("unhealthy", services[0].status)

    def test_up_registers_extra_routes_under_project_domain(self) -> None:
        profile = make_profile(
            path=str(self.project_dir),
            extra_port_envs=["PORT_PHPMYADMIN"],
            extra_routes=[ExtraRoute(name="phpmyadmin", port_env="PORT_PHPMYADMIN")],
        )
        registry = Registry(self.settings)
        with (
            patch("devctl.commands.ensure_runtime"),
            patch("devctl.commands.resolve_profile", return_value=profile),
            patch("devctl.commands.adapter_for") as adapter_mock,
            patch("devctl.commands.wait_for_port", return_value=(True, None)),
            patch("devctl.commands.CaddyfileWriter"),
        ):
            adapter = adapter_mock.return_value
            adapter.command_up.return_value = ["docker", "compose", "up"]
            adapter.command_pre_up.side_effect = lambda c: ["docker", "compose", "run", *c]
            adapter.up.return_value = 0
            up(self.settings, None)

        entries = registry.extra_routes_for("app")
        self.assertEqual(1, len(entries))
        self.assertEqual("phpmyadmin.app.localhost", entries[0].domain)

    def test_up_prints_connected_extra_routes(self) -> None:
        profile = make_profile(
            path=str(self.project_dir),
            extra_port_envs=["PORT_PHPMYADMIN"],
            extra_routes=[ExtraRoute(name="phpmyadmin", port_env="PORT_PHPMYADMIN")],
        )
        with (
            patch("devctl.commands.ensure_runtime"),
            patch("devctl.commands.resolve_profile", return_value=profile),
            patch("devctl.commands.adapter_for") as adapter_mock,
            patch("devctl.commands.wait_for_port", return_value=(True, None)),
            patch("devctl.commands.CaddyfileWriter"),
        ):
            adapter = adapter_mock.return_value
            adapter.command_up.return_value = ["docker", "compose", "up"]
            adapter.command_pre_up.side_effect = lambda c: ["docker", "compose", "run", *c]
            adapter.up.return_value = 0
            output = io.StringIO()
            with redirect_stdout(output):
                up(self.settings, None)

        self.assertIn("Service:", output.getvalue())
        self.assertIn("phpmyadmin -> http://phpmyadmin.app.localhost", output.getvalue())
