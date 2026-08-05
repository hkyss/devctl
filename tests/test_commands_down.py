from unittest.mock import patch

from devctl.commands import down, status, stop_from_registry
from devctl.errors import DevctlError
from devctl.override import write_override
from devctl.profiles import PublishTarget
from devctl.registry import Registry, StopTarget

from .helpers import TempDirTestCase, make_profile, make_settings


class DownTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.settings = make_settings(self.tmp_path)
        self.registry = Registry(self.settings)
        self.registry.ensure()
        self.registry.upsert_starting(
            name="app",
            domain="app.localhost",
            project_path=str(self.tmp_path / "app"),
            adapter="docker-compose",
            command="docker compose -f docker-compose.yml up -d",
            host="127.0.0.1",
            port=50000,
            log_path=str(self.tmp_path / "app.log"),
        )

    @patch("devctl.commands.stop_from_registry")
    def test_down_stops_using_registry_when_profile_missing(self, stop_mock) -> None:
        down(self.settings, "app", all_projects=False)

        stop_mock.assert_called_once()
        self.assertEqual([], self.registry.names())

    @patch("devctl.commands.stop_from_registry")
    def test_down_removes_the_generated_override_file(self, _stop_mock) -> None:
        profile = make_profile(
            name="app",
            http_port_env=None,
            publish=PublishTarget(service="web", container_port=80),
        )
        override_path = write_override(self.settings, profile, 50000)
        self.assertTrue(override_path.exists())

        down(self.settings, "app", all_projects=False)

        self.assertFalse(override_path.exists())

    def test_down_with_path_traversal_name_does_not_delete_files_outside_state_dir(self) -> None:
        other_profile = make_profile(
            name="other",
            http_port_env=None,
            publish=PublishTarget(service="web", container_port=80),
        )
        write_override(self.settings, other_profile, 50001)
        outside_target = self.settings.state_dir.parent / "evil.yml"
        outside_target.write_text("do not delete me", encoding="utf-8")

        down(self.settings, "../../evil", all_projects=False)

        self.assertTrue(outside_target.exists())

    @patch("devctl.commands.find_profile", return_value=None)
    @patch("devctl.commands.stop_from_registry")
    def test_down_all_stops_every_registered_service(self, stop_mock, _find_mock) -> None:
        self.registry.upsert_starting(
            name="other",
            domain="other.localhost",
            project_path=str(self.tmp_path / "other"),
            adapter="docker-compose",
            command="docker compose up",
            host="127.0.0.1",
            port=50001,
            log_path=str(self.tmp_path / "other.log"),
        )

        down(self.settings, None, all_projects=True)

        self.assertEqual(2, stop_mock.call_count)
        self.assertEqual([], self.registry.names())

    @patch("devctl.commands.port_accepts_connections", return_value=False)
    def test_status_reports_stale_when_backend_unreachable(self, _conn_mock) -> None:
        status(self.settings, "app", as_json=True)

    def test_status_raises_for_unknown_service(self) -> None:
        with self.assertRaises(DevctlError):
            status(self.settings, "nope", as_json=False)


class StopFromRegistryTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.settings = make_settings(self.tmp_path)

    @patch("devctl.commands.subprocess.run")
    def test_sets_compose_project_name_env_when_known(self, run_mock) -> None:
        target = StopTarget(
            name="app",
            adapter="docker-compose",
            project_path=str(self.tmp_path / "app"),
            command="docker compose up -d",
            compose_project_name="devctl_app_bob",
        )

        stop_from_registry(self.settings, target)

        _args, kwargs = run_mock.call_args
        self.assertEqual("devctl_app_bob", kwargs["env"]["COMPOSE_PROJECT_NAME"])

    @patch("devctl.commands.subprocess.run")
    def test_omits_compose_project_name_env_when_unknown(self, run_mock) -> None:
        target = StopTarget(
            name="app",
            adapter="docker-compose",
            project_path=str(self.tmp_path / "app"),
            command="docker compose up -d",
            compose_project_name=None,
        )

        stop_from_registry(self.settings, target)

        _args, kwargs = run_mock.call_args
        self.assertNotIn("COMPOSE_PROJECT_NAME", kwargs["env"])
