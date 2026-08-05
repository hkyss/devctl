import io
from contextlib import redirect_stdout
from unittest.mock import patch

from devctl.commands import prune
from devctl.registry import Registry

from .helpers import TempDirTestCase, make_settings

LIVE_PORT = 50001


class PruneTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.settings = make_settings(self.tmp_path)
        Registry(self.settings).ensure()

    def _register(self, name: str, port: int, status: str = "healthy") -> None:
        registry = Registry(self.settings)
        registry.upsert_starting(
            name=name,
            domain=f"{name}.localhost",
            project_path=str(self.tmp_path / name),
            adapter="docker-compose",
            command="docker compose up",
            host=self.settings.upstream_host,
            port=port,
            log_path=str(self.settings.log_dir / f"{name}.log"),
        )
        registry.set_status(name, status)

    def _run(self, dry_run: bool = False):
        stdout = io.StringIO()
        with (
            patch("devctl.commands.port_accepts_connections", side_effect=lambda host, port: port == LIVE_PORT),
            patch("devctl.commands.CaddyfileWriter") as caddy_mock,
            redirect_stdout(stdout),
        ):
            prune(self.settings, dry_run=dry_run)
        return stdout.getvalue(), caddy_mock

    def test_removes_dead_entries_and_keeps_live_ones(self) -> None:
        self._register("dead", 50000)
        self._register("live", LIVE_PORT)

        output, caddy_mock = self._run()

        self.assertEqual(["live"], Registry(self.settings).names())
        self.assertIn("dead", output)
        caddy_mock.return_value.write.assert_called_once()

    def test_dry_run_reports_without_deleting(self) -> None:
        self._register("dead", 50000)

        output, caddy_mock = self._run(dry_run=True)

        self.assertEqual(["dead"], Registry(self.settings).names())
        self.assertIn("dead", output)
        caddy_mock.return_value.write.assert_not_called()

    def test_spares_services_that_are_still_starting(self) -> None:
        self._register("booting", 50000, status="starting")

        self._run()

        self.assertEqual(["booting"], Registry(self.settings).names())

    def test_reports_when_nothing_is_stale(self) -> None:
        self._register("live", LIVE_PORT)

        output, caddy_mock = self._run()

        self.assertIn("No stale services", output)
        caddy_mock.return_value.write.assert_not_called()
