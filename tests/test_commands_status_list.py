import io
import json
from contextlib import ExitStack, redirect_stdout
from unittest.mock import patch

from devctl.commands import list_services, status, up
from devctl.errors import DevctlError
from devctl.registry import Registry

from .helpers import TempDirTestCase, make_profile, make_settings


class StatusListTestCase(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.settings = make_settings(self.tmp_path)
        Registry(self.settings).ensure()

    def _register(self, name: str = "app", port: int = 50000, status_value: str = "healthy") -> None:
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
        registry.set_status(name, status_value)


class StatusTests(StatusListTestCase):
    def _status(self, as_json: bool = False, live: bool = True, profile=None) -> str:
        stdout = io.StringIO()
        with (
            patch("devctl.commands.port_accepts_connections", return_value=live),
            patch("devctl.commands.find_profile", return_value=profile),
            redirect_stdout(stdout),
        ):
            status(self.settings, "app", as_json)
        return stdout.getvalue()

    def test_human_output_shows_url_backend_path_and_logs(self) -> None:
        self._register()

        output = self._status()

        self.assertIn("URL: http://app.localhost", output)
        self.assertIn("Backend: 127.0.0.1:50000", output)
        self.assertIn(f"Path: {self.tmp_path / 'app'}", output)
        self.assertIn("Logs: ", output)
        self.assertIn("app.log", output)

    def test_stale_service_shows_reason(self) -> None:
        self._register()

        output = self._status(live=False)

        self.assertIn("Status: stale", output)
        self.assertIn("Reason: port 50000 is not accepting connections", output)

    def test_unhealthy_service_shows_persisted_reason(self) -> None:
        self._register()
        Registry(self.settings).set_status("app", "unhealthy", detail="health check failed: connection refused")

        output = self._status(live=True)

        self.assertIn("Status: unhealthy", output)
        self.assertIn("Reason: health check failed: connection refused", output)

    def test_profile_adds_compose_project_and_health_check(self) -> None:
        self._register()
        profile = make_profile(
            path=str(self.tmp_path / "app"),
            compose_project_name="myproj",
            health_check_path="/health",
        )

        output = self._status(profile=profile)

        self.assertIn("Compose project: myproj", output)
        self.assertIn("Health check: HTTP /health", output)
        self.assertIn("timeout 90s", output)

    def test_json_includes_url_backend_logs_and_reason(self) -> None:
        self._register()

        payload = json.loads(self._status(as_json=True, live=False))

        self.assertEqual("stale", payload["status"])
        self.assertEqual("http://app.localhost", payload["url"])
        self.assertEqual("127.0.0.1:50000", payload["backend"])
        self.assertIn("app.log", payload["log_path"])
        self.assertEqual("port 50000 is not accepting connections", payload["reason"])


class ListTests(StatusListTestCase):
    def _list(self, as_json: bool = False, live: bool = True) -> str:
        stdout = io.StringIO()
        with (
            patch("devctl.commands.port_accepts_connections", return_value=live),
            redirect_stdout(stdout),
        ):
            list_services(self.settings, as_json)
        return stdout.getvalue()

    def test_table_shows_url(self) -> None:
        self._register()

        output = self._list()

        self.assertIn("http://app.localhost", output)

    def test_table_shows_reason_for_stale_service(self) -> None:
        self._register()

        output = self._list(live=False)

        self.assertIn("port 50000 is not accepting connections", output)

    def test_json_includes_effective_status_and_reason(self) -> None:
        self._register()

        payload = json.loads(self._list(as_json=True, live=False))

        self.assertEqual("stale", payload[0]["status"])
        self.assertEqual("http://app.localhost", payload[0]["url"])
        self.assertEqual("port 50000 is not accepting connections", payload[0]["reason"])


class UpPersistsReasonTests(StatusListTestCase):
    def _up(self, adapter_up_result: int = 0, wait_result=(True, None)) -> DevctlError | None:
        self.project_dir = self.tmp_path / "app"
        self.project_dir.mkdir(parents=True, exist_ok=True)
        profile = make_profile(path=str(self.project_dir))
        error: DevctlError | None = None
        with ExitStack() as stack:
            stack.enter_context(patch("devctl.commands.ensure_runtime"))
            stack.enter_context(patch("devctl.commands.resolve_profile", return_value=profile))
            adapter_mock = stack.enter_context(patch("devctl.commands.adapter_for"))
            stack.enter_context(patch("devctl.commands.wait_for_port", return_value=wait_result))
            stack.enter_context(patch("devctl.commands.CaddyfileWriter"))
            stack.enter_context(redirect_stdout(io.StringIO()))
            adapter = adapter_mock.return_value
            adapter.command_up.return_value = ["docker", "compose", "up"]
            adapter.command_pre_up.side_effect = lambda c: ["docker", "compose", "run", *c]
            adapter.up.return_value = adapter_up_result
            try:
                up(self.settings, None)
            except DevctlError as exc:
                error = exc
        return error

    def test_failed_health_check_persists_reason(self) -> None:
        error = self._up(wait_result=(False, "connection refused"))

        self.assertIsNotNone(error)
        service = Registry(self.settings).services()[0]
        self.assertEqual("unhealthy", service.status)
        self.assertEqual("connection refused", service.status_detail)

    def test_failed_start_persists_reason(self) -> None:
        error = self._up(adapter_up_result=1)

        self.assertIsNotNone(error)
        service = Registry(self.settings).services()[0]
        self.assertEqual("unhealthy", service.status)
        self.assertIn("exit code 1", service.status_detail)

    def test_successful_up_clears_previous_reason(self) -> None:
        self._up(wait_result=(False, "connection refused"))

        error = self._up()

        self.assertIsNone(error)
        service = Registry(self.settings).services()[0]
        self.assertEqual("healthy", service.status)
        self.assertIsNone(service.status_detail)


class RegistryMigrationTests(TempDirTestCase):
    def test_adds_status_detail_column_to_existing_database(self) -> None:
        import sqlite3

        settings = make_settings(self.tmp_path)
        settings.state_dir.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(settings.registry_path) as db:
            db.execute(
                """
                CREATE TABLE services (
                  name TEXT PRIMARY KEY,
                  domain TEXT NOT NULL UNIQUE,
                  project_path TEXT NOT NULL,
                  adapter TEXT NOT NULL,
                  command TEXT NOT NULL,
                  host TEXT NOT NULL,
                  port INTEGER NOT NULL,
                  pid INTEGER,
                  status TEXT NOT NULL,
                  log_path TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                )
                """
            )

        registry = Registry(settings)
        registry.ensure()
        registry.upsert_starting(
            name="app",
            domain="app.localhost",
            project_path="/tmp/app",
            adapter="docker-compose",
            command="docker compose up",
            host="127.0.0.1",
            port=50000,
            log_path="/tmp/app.log",
        )
        registry.set_status("app", "unhealthy", detail="boom")

        service = registry.services()[0]
        self.assertEqual("boom", service.status_detail)
