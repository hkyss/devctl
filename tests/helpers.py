import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from devctl.profiles import ProjectProfile
from devctl.settings import Settings


class TempDirTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def make_settings(tmp_path: Path) -> Settings:
    state_dir = tmp_path / "state"
    return Settings(
        repo_root=tmp_path / "devctl",
        workspace_root=tmp_path / "workspace",
        state_dir=state_dir,
        log_dir=state_dir / "logs",
        registry_path=state_dir / "registry.sqlite",
        caddyfile_path=state_dir / "Caddyfile",
        lock_path=state_dir / "devctl.lock",
        dns_suffix="localhost",
        url_scheme="http",
        port_start=50000,
        port_end=50010,
        upstream_host="127.0.0.1",
        publish_host="127.0.0.1",
    )


def make_profile(**overrides: Any) -> ProjectProfile:
    path = Path(overrides.pop("path", os.getcwd()))
    values = {
        "name": "app",
        "path": path,
        "adapter": "docker-compose",
        "compose_files": ["docker-compose.yml"],
        "env_file": None,
        "http_port_env": "PORT_HTTP",
        "publish": None,
        "compose_override": {},
        "extra_port_envs": [],
        "preferred_ports": [],
        "host_prefixed_port_envs": set(),
        "publish_envs": {},
        "env": {},
        "pre_up_commands": [],
        "build": False,
        "health_timeout_seconds": 90,
        "health_check_path": None,
        "health_check_statuses": [200],
        "compose_project_name": None,
        "domain": None,
        "extra_routes": [],
        "primary_service": None,
    }
    if "compose_file" in overrides:
        overrides["compose_files"] = [overrides.pop("compose_file")]
    values.update(overrides)
    return ProjectProfile(**values)
