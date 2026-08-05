import json
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from devctl.commands import init_project
from devctl.errors import DevctlError
from devctl.profiles import CONFIG_FILENAME

from .helpers import TempDirTestCase, make_settings


class InitProjectTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.settings = make_settings(self.tmp_path)
        profiles_dir = self.settings.repo_root / "examples" / "profiles"
        profiles_dir.mkdir(parents=True)
        (profiles_dir / "vite.devctl.json").write_text(
            json.dumps(
                {
                    "name": "example-web",
                    "adapter": "docker-compose",
                    "compose_file": "docker-compose.yml",
                    "http_port_env": "PORT_HTTP",
                    "preferred_ports": [5173],
                    "host_prefixed_port_envs": ["PORT_HTTP"],
                    "env": {"PROJECT_NAME": "devctl_example_web"},
                    "build": True,
                    "health_timeout_seconds": 90,
                    "health_check_path": "/",
                    "health_check_statuses": [200],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        self.project_root = self.tmp_path / "workspace" / "app"
        self.project_root.mkdir(parents=True)

    def test_init_project_writes_starter_config(self) -> None:
        with patch("devctl.commands.current_git_root", return_value=self.project_root), redirect_stdout(StringIO()):
            init_project(
                self.settings,
                name="app",
                compose_file="docker-compose.yml",
                env_file="docker/.env",
                http_port_env="PORT_HTTP",
                recipe=None,
                force=False,
                dry_run=False,
            )

        payload = json.loads((self.project_root / CONFIG_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual("app", payload["name"])
        self.assertEqual("docker-compose.yml", payload["compose_file"])
        self.assertEqual("docker/.env", payload["env_file"])
        self.assertEqual(["PORT_HTTP"], payload["host_prefixed_port_envs"])

    def test_init_project_refuses_to_overwrite_without_force(self) -> None:
        config_path = self.project_root / CONFIG_FILENAME
        config_path.write_text("{}\n", encoding="utf-8")

        with (
            patch("devctl.commands.current_git_root", return_value=self.project_root),
            self.assertRaisesRegex(DevctlError, "already exists"),
        ):
            init_project(self.settings, None, "docker-compose.yml", None, "PORT_HTTP", None, force=False, dry_run=False)

        self.assertEqual("{}\n", config_path.read_text(encoding="utf-8"))

    def test_init_project_force_overwrites_existing_config(self) -> None:
        config_path = self.project_root / CONFIG_FILENAME
        config_path.write_text("{}\n", encoding="utf-8")

        with patch("devctl.commands.current_git_root", return_value=self.project_root), redirect_stdout(StringIO()):
            init_project(self.settings, "new-name", "compose.yml", None, "PORT_WEB", None, force=True, dry_run=False)

        payload = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual("new-name", payload["name"])
        self.assertEqual("PORT_WEB", payload["http_port_env"])

    def test_init_project_dry_run_does_not_write_file(self) -> None:
        with patch("devctl.commands.current_git_root", return_value=self.project_root), redirect_stdout(StringIO()):
            init_project(self.settings, "app", "compose.yml", None, "PORT_WEB", None, force=False, dry_run=True)

        self.assertFalse((self.project_root / CONFIG_FILENAME).exists())

    def test_init_project_writes_recipe_config(self) -> None:
        with patch("devctl.commands.current_git_root", return_value=self.project_root), redirect_stdout(StringIO()):
            init_project(
                self.settings,
                name="my-app",
                compose_file="compose.dev.yml",
                env_file="docker/.env",
                http_port_env="PORT_WEB",
                recipe="vite",
                force=False,
                dry_run=False,
            )

        payload = json.loads((self.project_root / CONFIG_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual("my-app", payload["name"])
        self.assertEqual("compose.dev.yml", payload["compose_file"])
        self.assertEqual("docker/.env", payload["env_file"])
        self.assertEqual("PORT_WEB", payload["http_port_env"])
        self.assertEqual(["PORT_WEB"], payload["host_prefixed_port_envs"])
        self.assertEqual("devctl_my_app", payload["env"]["PROJECT_NAME"])
        self.assertEqual([5173], payload["preferred_ports"])

    def test_init_project_recipe_dry_run_prints_config(self) -> None:
        stdout = StringIO()

        with patch("devctl.commands.current_git_root", return_value=self.project_root), redirect_stdout(stdout):
            init_project(
                self.settings,
                name=None,
                compose_file="docker-compose.yml",
                env_file=None,
                http_port_env="PORT_HTTP",
                recipe="vite",
                force=False,
                dry_run=True,
            )

        payload = json.loads(stdout.getvalue())
        self.assertEqual("app", payload["name"])
        self.assertEqual("devctl_app", payload["env"]["PROJECT_NAME"])
        self.assertFalse((self.project_root / CONFIG_FILENAME).exists())
