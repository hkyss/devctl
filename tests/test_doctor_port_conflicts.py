import json
from io import StringIO
from unittest.mock import patch

from devctl.commands import _detect_cross_project_port_conflicts, doctor
from devctl.errors import DevctlError
from devctl.registry import ExtraRouteEntry, Registry

from .helpers import TempDirTestCase, make_settings


def _register(registry: Registry, name: str, port: int) -> None:
    registry.upsert_starting(
        name=name,
        domain=f"{name}.localhost",
        project_path=f"/tmp/{name}",
        adapter="docker-compose",
        command="docker compose up",
        host="127.0.0.1",
        port=port,
        log_path=f"/tmp/{name}.log",
    )


class DetectCrossProjectPortConflictsTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.settings = make_settings(self.tmp_path)
        self.registry = Registry(self.settings)
        self.registry.ensure()

    def test_no_conflicts_when_ports_are_distinct(self) -> None:
        _register(self.registry, "app", 50000)
        _register(self.registry, "other", 50001)

        self.assertEqual({}, _detect_cross_project_port_conflicts(self.settings))

    def test_flags_two_profiles_sharing_a_primary_port(self) -> None:
        _register(self.registry, "app", 50000)
        _register(self.registry, "other", 50000)

        conflicts = _detect_cross_project_port_conflicts(self.settings)

        self.assertEqual({50000: ["app", "other"]}, conflicts)

    def test_flags_conflict_via_extra_route_port(self) -> None:
        _register(self.registry, "app", 50000)
        _register(self.registry, "other", 50001)
        self.registry.set_extra_routes(
            "other",
            [ExtraRouteEntry(route_name="admin", domain="admin.other.localhost", host="127.0.0.1", port=50000)],
        )

        conflicts = _detect_cross_project_port_conflicts(self.settings)

        self.assertEqual({50000: ["app", "other"]}, conflicts)

    def test_same_profile_reusing_its_own_port_is_not_a_conflict(self) -> None:
        _register(self.registry, "app", 50000)
        self.registry.set_extra_routes(
            "app",
            [ExtraRouteEntry(route_name="admin", domain="admin.app.localhost", host="127.0.0.1", port=50000)],
        )

        self.assertEqual({}, _detect_cross_project_port_conflicts(self.settings))


class DoctorWorkspaceFlagTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.settings = make_settings(self.tmp_path)
        self.settings.state_dir.mkdir(parents=True, exist_ok=True)
        self.settings.workspace_root.mkdir(parents=True, exist_ok=True)
        (self.settings.workspace_root / "devctl").mkdir(parents=True, exist_ok=True)

    @patch("devctl.commands._warn_missing_resource_limits", return_value=None)
    @patch("devctl.commands._warn_orphan_volumes")
    @patch("devctl.commands._warn_upstream_publish_mismatch")
    @patch("devctl.commands._has_free_port", return_value=True)
    @patch("devctl.commands._can_bind_proxy_port", return_value=True)
    @patch("devctl.commands._command_ok", return_value=True)
    @patch("devctl.commands.current_git_root", return_value=None)
    def test_workspace_flag_prints_conflicts(self, *_mocks) -> None:
        registry = Registry(self.settings)
        registry.ensure()
        _register(registry, "app", 50000)
        _register(registry, "other", 50000)

        with patch("sys.stdout", new=StringIO()) as out, self.assertRaises(DevctlError):
            doctor(self.settings, as_json=False, workspace=True)

        self.assertIn("50000", out.getvalue())
        self.assertIn("app", out.getvalue())
        self.assertIn("other", out.getvalue())

    @patch("devctl.commands._warn_missing_resource_limits", return_value=None)
    @patch("devctl.commands._warn_orphan_volumes")
    @patch("devctl.commands._warn_upstream_publish_mismatch")
    @patch("devctl.commands._has_free_port", return_value=True)
    @patch("devctl.commands._can_bind_proxy_port", return_value=True)
    @patch("devctl.commands._command_ok", return_value=True)
    @patch("devctl.commands.current_git_root", return_value=None)
    def test_workspace_flag_json_includes_conflicts_key(self, *_mocks) -> None:
        registry = Registry(self.settings)
        registry.ensure()
        _register(registry, "app", 50000)
        _register(registry, "other", 50000)

        with patch("sys.stdout", new=StringIO()) as out, self.assertRaises(DevctlError):
            doctor(self.settings, as_json=True, workspace=True)

        payload = json.loads(out.getvalue())
        self.assertEqual({"50000": ["app", "other"]}, payload["cross_project_port_conflicts"])
