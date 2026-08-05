import io
import json
from contextlib import redirect_stdout
from unittest.mock import patch

from devctl.commands import profile_print
from devctl.profiles import ExtraRoute

from .helpers import TempDirTestCase, make_profile, make_settings


class ProfilePrintTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.settings = make_settings(self.tmp_path)
        self.project_dir = self.tmp_path / "app"
        self.project_dir.mkdir(parents=True)

    def _run(self, profile, as_json: bool) -> str:
        stdout = io.StringIO()
        with patch("devctl.commands.resolve_profile", return_value=profile), redirect_stdout(stdout):
            profile_print(self.settings, None, as_json)
        return stdout.getvalue()

    def test_json_output_is_the_resolved_profile(self) -> None:
        profile = make_profile(
            path=str(self.project_dir),
            host_prefixed_port_envs={"PORT_HTTP"},
            extra_port_envs=["PORT_PHPMYADMIN"],
            extra_routes=[ExtraRoute(name="phpmyadmin", port_env="PORT_PHPMYADMIN")],
        )

        payload = json.loads(self._run(profile, as_json=True))

        self.assertEqual("app", payload["name"])
        self.assertEqual(str(self.project_dir), payload["path"])
        self.assertEqual(["docker-compose.yml"], payload["compose_files"])
        self.assertEqual(90, payload["health_timeout_seconds"])
        self.assertEqual(False, payload["build"])
        self.assertEqual(["PORT_HTTP"], payload["host_prefixed_port_envs"])
        self.assertEqual("app.localhost", payload["domain"])
        self.assertEqual("http://app.localhost", payload["url"])
        self.assertEqual([{"name": "phpmyadmin", "port_env": "PORT_PHPMYADMIN"}], payload["extra_routes"])

    def test_human_output_lists_resolved_fields(self) -> None:
        profile = make_profile(path=str(self.project_dir))

        output = self._run(profile, as_json=False)

        self.assertIn("name: app", output)
        self.assertIn("url: http://app.localhost", output)
        self.assertIn("health_timeout_seconds: 90", output)
