import fcntl
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

from devctl.commands import restart
from devctl.lock import state_lock
from devctl.registry import Registry

from .helpers import TempDirTestCase, make_profile, make_settings


class RestartLockScopeTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.settings = make_settings(self.tmp_path)
        Registry(self.settings).ensure()
        self.project_dir = self.tmp_path / "app"
        self.project_dir.mkdir(parents=True)
        self._register_running_service()

    def _register_running_service(self) -> None:
        registry = Registry(self.settings)
        registry.upsert_starting(
            name="app",
            domain="app.localhost",
            project_path=str(self.project_dir),
            adapter="docker-compose",
            command="docker compose up",
            host=self.settings.upstream_host,
            port=50000,
            log_path=str(self.settings.log_dir / "app.log"),
        )
        registry.set_status("app", "healthy")

    def _patched_restart(self, lock_factory=None, adapter_up=None) -> None:
        profile = make_profile(path=str(self.project_dir))
        patches = [
            patch("devctl.commands.ensure_runtime"),
            patch("devctl.commands.resolve_profile", return_value=profile),
            patch("devctl.commands.find_profile", return_value=profile),
            patch("devctl.commands.wait_for_port", return_value=(True, None)),
            patch("devctl.commands.CaddyfileWriter"),
        ]
        if lock_factory:
            patches.append(patch("devctl.commands.state_lock", lock_factory))
        with patch("devctl.commands.adapter_for") as adapter_mock:
            adapter = adapter_mock.return_value
            adapter.command_up.return_value = ["docker", "compose", "up"]
            adapter.command_pre_up.side_effect = lambda c: ["docker", "compose", "run", *c]
            adapter.up.side_effect = adapter_up or (lambda *args: 0)
            adapter.down.return_value = None
            with ExitStack() as stack:
                for item in patches:
                    stack.enter_context(item)
                restart(self.settings, "app")

    def test_lock_never_released_while_project_unregistered(self) -> None:
        releases: list[list[str]] = []

        @contextmanager
        def recording_lock(settings):
            with state_lock(settings):
                yield
                releases.append([service.name for service in Registry(settings).services()])

        self._patched_restart(lock_factory=recording_lock)

        self.assertTrue(releases, "restart never acquired the state lock")
        for names in releases:
            self.assertIn("app", names, "state lock released while project was unregistered")

    def test_lock_released_before_container_start(self) -> None:
        held = {"during_start": None}

        def fake_adapter_up(port, extra_ports, log):
            with self.settings.lock_path.open("w") as probe:
                try:
                    fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    held["during_start"] = False
                    fcntl.flock(probe.fileno(), fcntl.LOCK_UN)
                except BlockingIOError:
                    held["during_start"] = True
            return 0

        self._patched_restart(adapter_up=fake_adapter_up)

        self.assertEqual(False, held["during_start"])

    def test_restart_leaves_service_healthy(self) -> None:
        self._patched_restart()

        services = Registry(self.settings).services()
        self.assertEqual(1, len(services))
        self.assertEqual("app", services[0].name)
        self.assertEqual("healthy", services[0].status)
