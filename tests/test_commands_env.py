import io
import json
from contextlib import redirect_stdout
from unittest.mock import patch

from devctl.commands import env_print

from .helpers import TempDirTestCase, make_profile, make_settings


class EnvPrintTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.settings = make_settings(self.tmp_path)
        self.project_dir = self.tmp_path / "app"
        self.project_dir.mkdir(parents=True)

    def _run(self, profile, as_json: bool) -> str:
        stdout = io.StringIO()
        with patch("devctl.commands.resolve_profile", return_value=profile), redirect_stdout(stdout):
            env_print(self.settings, None, as_json)
        return stdout.getvalue()

    def test_json_output_carries_the_compose_context(self) -> None:
        profile = make_profile(path=str(self.project_dir), env={"DB_DATABASE": "app"})

        payload = json.loads(self._run(profile, as_json=True))

        self.assertEqual("app", payload["DB_DATABASE"])
        self.assertEqual("app.localhost", payload["DEVCTL_DOMAIN"])
        self.assertEqual("http://app.localhost", payload["DEVCTL_URL"])
        self.assertTrue(payload["COMPOSE_PROJECT_NAME"].startswith("devctl_app_"))

    def test_compose_project_name_override_wins(self) -> None:
        profile = make_profile(path=str(self.project_dir), compose_project_name="legacy_app")

        payload = json.loads(self._run(profile, as_json=True))

        self.assertEqual("legacy_app", payload["COMPOSE_PROJECT_NAME"])

    def test_human_output_is_evaluable_shell(self) -> None:
        profile = make_profile(path=str(self.project_dir), env={"NOTE": "two words"})

        output = self._run(profile, as_json=False)

        self.assertIn("export NOTE='two words'", output)
        self.assertIn("export COMPOSE_PROJECT_NAME=", output)

    def test_port_variables_are_not_exported(self) -> None:
        profile = make_profile(path=str(self.project_dir), extra_port_envs=["PORT_PHPMYADMIN"])

        payload = json.loads(self._run(profile, as_json=True))

        self.assertNotIn("PORT_HTTP", payload)
        self.assertNotIn("PORT_PHPMYADMIN", payload)
