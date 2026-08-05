from pathlib import Path

from devctl.commands import validate
from devctl.errors import DevctlError
from devctl.profiles import CONFIG_FILENAME
from devctl.standard import validate_config_file

from .helpers import TempDirTestCase, make_settings, write_json


class ValidateTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.settings = make_settings(self.tmp_path)
        self.workspace = self.settings.workspace_root
        self.workspace.mkdir(parents=True)

    def write_profile(self, project: str, payload: dict) -> Path:
        config_path = self.workspace / project / CONFIG_FILENAME
        write_json(config_path, payload)
        return config_path

    def base_profile(self, **overrides: object) -> dict:
        payload = {
            "name": "billing-api",
            "adapter": "docker-compose",
            "compose_file": "docker-compose.yml",
            "http_port_env": "PORT_HTTP",
            "env": {"PROJECT_NAME": "devctl_billing_api"},
        }
        payload.update(overrides)
        return payload

    def test_validate_config_file_reports_unknown_fields(self) -> None:
        config_path = self.write_profile("app", {**self.base_profile(), "team": "platform"})
        (config_path.parent / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")

        issues = validate_config_file(self.settings, config_path, strict=False)

        self.assertTrue(any(issue.field == "team" for issue in issues))

    def test_validate_config_file_strict_promotes_warnings(self) -> None:
        config_path = self.write_profile(
            "app",
            {
                **self.base_profile(),
                "env": {},
            },
        )
        (config_path.parent / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")

        issues = validate_config_file(self.settings, config_path, strict=True)

        self.assertTrue(all(issue.severity == "error" for issue in issues))
        self.assertTrue(any(issue.field == "env.PROJECT_NAME" for issue in issues))

    def test_validate_config_file_accepts_primary_service(self) -> None:
        config_path = self.write_profile("app", {**self.base_profile(), "primary_service": "api"})
        (config_path.parent / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")

        issues = validate_config_file(self.settings, config_path, strict=True)

        self.assertFalse(any(issue.field == "primary_service" for issue in issues))

    def test_warns_when_compose_already_publishes_the_publish_container_port(self) -> None:
        payload = self.base_profile()
        del payload["http_port_env"]
        payload["publish"] = {"service": "web", "container_port": 80}
        config_path = self.write_profile("app", payload)
        (config_path.parent / "docker-compose.yml").write_text(
            'services:\n  web:\n    ports:\n      - "8080:80"\n',
            encoding="utf-8",
        )

        issues = validate_config_file(self.settings, config_path, strict=False)

        self.assertTrue(
            any(
                issue.field == "publish" and issue.severity == "warning" and "already publishes container port 80" in issue.message
                for issue in issues
            )
        )

    def test_missing_compose_file_reports_indexed_field(self) -> None:
        payload = self.base_profile()
        del payload["compose_file"]
        payload["compose_files"] = ["a.yml", "b.yml"]
        config_path = self.write_profile("app", payload)
        (config_path.parent / "a.yml").write_text("services: {}\n", encoding="utf-8")

        issues = validate_config_file(self.settings, config_path, strict=False)

        self.assertTrue(any(issue.field == "compose_files[1]" and "b.yml" in issue.message for issue in issues))
        self.assertFalse(any(issue.field == "compose_file" for issue in issues))

    def test_validate_command_succeeds_for_compliant_profile(self) -> None:
        config_path = self.write_profile("billing-api", self.base_profile())
        (config_path.parent / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")

        validate(self.settings, "billing-api", workspace=False, files=None, strict=True, as_json=False)

    def test_validate_command_fails_on_structural_error(self) -> None:
        self.write_profile("billing-api", {"name": "billing-api", "adapter": "docker-compose"})

        with self.assertRaises(DevctlError):
            validate(self.settings, "billing-api", workspace=False, files=None, strict=False, as_json=False)

    def test_validate_workspace_collects_all_profiles(self) -> None:
        for project in ("one", "two"):
            config_path = self.write_profile(project, {**self.base_profile(), "name": project})
            (config_path.parent / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")

        validate(self.settings, None, workspace=True, files=None, strict=False, as_json=False)

    def test_schema_violation_reported_as_error(self) -> None:
        config_path = self.write_profile(
            "app",
            {**self.base_profile(), "preferred_ports": ["not-an-int"]},
        )
        (config_path.parent / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")

        issues = validate_config_file(self.settings, config_path, strict=False)

        self.assertTrue(any(issue.severity == "error" for issue in issues))

    def test_validate_file_flag(self) -> None:
        config_path = self.write_profile("app", self.base_profile())
        (config_path.parent / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")

        validate(
            self.settings,
            None,
            workspace=False,
            files=[str(config_path)],
            strict=True,
            as_json=False,
        )
