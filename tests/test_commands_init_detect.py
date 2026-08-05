import io
import json
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from devctl.commands import init_project
from devctl.profiles import CONFIG_FILENAME

from .helpers import TempDirTestCase, make_settings


class InitAutodetectTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.settings = make_settings(self.tmp_path)
        self.project_root = self.tmp_path / "workspace" / "app"
        self.project_root.mkdir(parents=True)

    def _init(self, **overrides) -> tuple[dict, str]:
        kwargs = {
            "name": "app",
            "compose_file": "docker-compose.yml",
            "env_file": None,
            "http_port_env": "PORT_HTTP",
            "recipe": None,
            "force": False,
            "dry_run": False,
        }
        kwargs.update(overrides)
        stderr = io.StringIO()
        with (
            patch("devctl.commands.current_git_root", return_value=self.project_root),
            redirect_stdout(io.StringIO()),
            redirect_stderr(stderr),
        ):
            init_project(self.settings, **kwargs)
        payload = json.loads((self.project_root / CONFIG_FILENAME).read_text(encoding="utf-8"))
        return payload, stderr.getvalue()

    def test_detects_alternative_compose_file_name(self) -> None:
        (self.project_root / "compose.yaml").write_text("services: {}\n", encoding="utf-8")

        payload, _stderr = self._init()

        self.assertEqual("compose.yaml", payload["compose_file"])

    def test_detects_env_file(self) -> None:
        (self.project_root / ".env").write_text("PORT_HTTP=5173\n", encoding="utf-8")

        payload, _stderr = self._init()

        self.assertEqual(".env", payload["env_file"])

    def test_explicit_env_file_wins_over_detection(self) -> None:
        (self.project_root / ".env").write_text("PORT_HTTP=5173\n", encoding="utf-8")

        payload, _stderr = self._init(env_file="docker/.env")

        self.assertEqual("docker/.env", payload["env_file"])

    def test_detects_port_envs_from_compose(self) -> None:
        (self.project_root / "docker-compose.yml").write_text(
            'services:\n  web:\n    ports:\n      - "${PORT_HTTP:-5173}:5173"\n  admin:\n    ports:\n      - "${PORT_ADMIN:-8081}:8081"\n',
            encoding="utf-8",
        )

        payload, _stderr = self._init()

        self.assertEqual("PORT_HTTP", payload["http_port_env"])
        self.assertEqual(["PORT_ADMIN"], payload["extra_port_envs"])
        self.assertEqual([5173, 8081], payload["preferred_ports"])

    def test_picks_first_env_var_when_port_http_is_absent(self) -> None:
        (self.project_root / "docker-compose.yml").write_text(
            'services:\n  web:\n    ports:\n      - "${PORT_WEB:-3000}:3000"\n',
            encoding="utf-8",
        )

        payload, _stderr = self._init()

        self.assertEqual("PORT_WEB", payload["http_port_env"])
        self.assertEqual([], payload["extra_port_envs"])
        self.assertEqual(["PORT_WEB"], payload["host_prefixed_port_envs"])

    def test_literal_ports_become_preferred_and_warn(self) -> None:
        (self.project_root / "docker-compose.yml").write_text(
            'services:\n  web:\n    ports:\n      - "8080:80"\n',
            encoding="utf-8",
        )

        payload, stderr = self._init()

        self.assertEqual([8080], payload["preferred_ports"])
        self.assertEqual("PORT_HTTP", payload["http_port_env"])
        self.assertIn("8080:80", stderr)
        self.assertIn("PORT_HTTP", stderr)

    def test_without_compose_file_keeps_defaults(self) -> None:
        payload, _stderr = self._init()

        self.assertEqual("docker-compose.yml", payload["compose_file"])
        self.assertEqual("PORT_HTTP", payload["http_port_env"])
        self.assertEqual([], payload["preferred_ports"])
        self.assertNotIn("env_file", payload)
