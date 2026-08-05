from io import StringIO
from unittest.mock import patch

from devctl.commands import (
    RESOURCE_LIMITS_OVERRIDE_FILENAME,
    _fix_missing_resource_limits,
    _resource_limits_override_content,
    doctor,
)
from devctl.errors import DevctlError

from .helpers import TempDirTestCase, make_profile, make_settings


class ResourceLimitsOverrideContentTests(TempDirTestCase):
    def test_content_lists_each_service_as_commented_suggestion(self) -> None:
        content = _resource_limits_override_content(["cms", "queue"])
        self.assertIn("services:", content)
        self.assertIn("  cms:", content)
        self.assertIn("  queue:", content)
        self.assertIn("# mem_limit: 512m", content)
        self.assertIn('# cpus: "1.0"', content)


class FixMissingResourceLimitsTests(TempDirTestCase):
    def test_dry_run_prints_without_writing(self) -> None:
        compose_path = self.tmp_path / "docker-compose.yml"
        compose_path.write_text("services: {}\n", encoding="utf-8")

        with patch("sys.stdout", new=StringIO()) as out:
            override_path = _fix_missing_resource_limits(compose_path, ["cms"], dry_run=True)

        self.assertFalse(override_path.exists())
        self.assertIn("cms", out.getvalue())

    def test_writes_sibling_override_file_without_touching_compose_file(self) -> None:
        compose_path = self.tmp_path / "docker-compose.yml"
        compose_path.write_text("services: {}\n", encoding="utf-8")

        override_path = _fix_missing_resource_limits(compose_path, ["cms"], dry_run=False)

        self.assertEqual(compose_path.parent / RESOURCE_LIMITS_OVERRIDE_FILENAME, override_path)
        self.assertTrue(override_path.exists())
        self.assertEqual("services: {}\n", compose_path.read_text(encoding="utf-8"))
        self.assertIn("cms", override_path.read_text(encoding="utf-8"))


class DoctorFixIntegrationTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.settings = make_settings(self.tmp_path)
        self.settings.state_dir.mkdir(parents=True, exist_ok=True)
        self.settings.workspace_root.mkdir(parents=True, exist_ok=True)

    @patch("devctl.commands._fix_missing_resource_limits")
    @patch("devctl.commands._detect_unbounded_services")
    @patch("devctl.commands._warn_orphan_volumes")
    @patch("devctl.commands._warn_upstream_publish_mismatch")
    @patch("devctl.commands._has_free_port", return_value=True)
    @patch("devctl.commands._can_bind_proxy_port", return_value=True)
    @patch("devctl.commands._command_ok", return_value=True)
    def test_fix_writes_override_when_services_detected(
        self, _cmd_ok, _proxy, _free_port, _publish, _orphan, detect_mock, fix_mock
    ) -> None:
        compose_path = self.tmp_path / "docker-compose.yml"
        detect_mock.return_value = (compose_path, ["cms"])

        with patch("sys.stdout", new=StringIO()), self.assertRaises(DevctlError):
            doctor(self.settings, as_json=False, fix=True, dry_run=True)

        fix_mock.assert_called_once_with(compose_path, ["cms"], True)

    @patch("devctl.commands._detect_unbounded_services", return_value=None)
    @patch("devctl.commands._warn_orphan_volumes")
    @patch("devctl.commands._warn_upstream_publish_mismatch")
    @patch("devctl.commands._has_free_port", return_value=True)
    @patch("devctl.commands._can_bind_proxy_port", return_value=True)
    @patch("devctl.commands._command_ok", return_value=True)
    def test_fix_reports_nothing_to_do_when_no_services_detected(self, _cmd_ok, _proxy, _free_port, _publish, _orphan, _detect) -> None:
        with patch("sys.stdout", new=StringIO()) as out, self.assertRaises(DevctlError):
            doctor(self.settings, as_json=False, fix=True, dry_run=False)

        self.assertIn("nothing to do", out.getvalue())


class DetectUnboundedServicesTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.settings = make_settings(self.tmp_path)

    @patch("devctl.commands.subprocess.run")
    @patch("devctl.commands.resolve_profile")
    def test_resolves_compose_files_relative_to_profile_path_not_git_root(self, resolve_mock, run_mock) -> None:
        from devctl.commands import _detect_unbounded_services

        git_root = self.tmp_path / "worktree"
        git_root.mkdir(parents=True)
        (git_root / ".devctl.json").write_text("{}", encoding="utf-8")

        project_path = self.tmp_path / "elsewhere" / "app"
        project_path.mkdir(parents=True)
        (project_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")

        resolve_mock.return_value = make_profile(path=project_path, compose_files=["docker-compose.yml"])
        run_mock.return_value.returncode = 1

        _detect_unbounded_services(self.settings, git_root)

        run_mock.assert_called_once()
        args, kwargs = run_mock.call_args
        self.assertEqual(project_path, kwargs["cwd"])
        self.assertIn(str(project_path / "docker-compose.yml"), args[0])
