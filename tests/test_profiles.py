from pathlib import Path
from unittest.mock import patch

from devctl.errors import DevctlError
from devctl.profiles import (
    CONFIG_FILENAME,
    PublishTarget,
    find_profile,
    load_profile_file,
    load_profiles,
    nearest_project_config,
    resolve_profile,
)

from .helpers import TempDirTestCase, make_settings, write_json


class ProfileTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.settings = make_settings(self.tmp_path)
        self.workspace = self.settings.workspace_root
        self.workspace.mkdir(parents=True)

    def write_profile(self, project: str, payload: dict) -> Path:
        config_path = self.workspace / project / CONFIG_FILENAME
        write_json(config_path, payload)
        return config_path

    def test_load_profile_defaults_path_to_config_directory(self) -> None:
        config_path = self.write_profile(
            "app",
            {
                "name": "app",
                "adapter": "docker-compose",
                "compose_file": "compose.yml",
                "http_port_env": "PORT_HTTP",
            },
        )

        profile = load_profile_file(config_path)

        self.assertEqual("app", profile.name)
        self.assertEqual(config_path.parent.resolve(), profile.path)
        self.assertEqual([], profile.extra_port_envs)
        self.assertEqual([], profile.pre_up_commands)
        self.assertEqual([200], profile.health_check_statuses)

    def test_load_profile_expands_path_and_normalizes_types(self) -> None:
        project_dir = self.workspace / "custom-root"
        config_path = self.write_profile(
            "app",
            {
                "name": "app",
                "path": str(project_dir),
                "adapter": "docker-compose",
                "compose_file": "compose.yml",
                "env_file": "docker/.env",
                "http_port_env": "PORT_HTTP",
                "extra_port_envs": ["PORT_DB", "PORT_REDIS"],
                "preferred_ports": ["8080", 3306],
                "host_prefixed_port_envs": ["PORT_HTTP"],
                "publish_envs": {"REDIS_PUBLISH": {"source": "PORT_REDIS", "target": 6379}},
                "env": {"DEBUG": True},
                "pre_up_commands": [["cms", "composer", "install"]],
                "build": False,
                "health_timeout_seconds": "12",
                "health_check_path": "/health",
                "health_check_statuses": ["200", 204],
                "compose_project_name": "custom",
                "domain": "custom.localhost",
            },
        )

        profile = load_profile_file(config_path)

        self.assertEqual(project_dir.resolve(), profile.path)
        self.assertEqual([8080, 3306], profile.preferred_ports)
        self.assertEqual({"PORT_HTTP"}, profile.host_prefixed_port_envs)
        self.assertEqual({"DEBUG": "True"}, profile.env)
        self.assertFalse(profile.build)
        self.assertEqual([200, 204], profile.health_check_statuses)

    def test_load_profiles_discovers_only_project_local_configs(self) -> None:
        self.write_profile(
            "app",
            {"name": "app", "adapter": "docker-compose", "compose_file": "a.yml", "http_port_env": "PORT_HTTP"},
        )
        self.write_profile(
            "api",
            {"name": "api", "adapter": "docker-compose", "compose_file": "b.yml", "http_port_env": "PORT_HTTP"},
        )

        profiles = load_profiles(self.settings)

        self.assertEqual(["api", "app"], sorted(profiles))

    def test_find_profile_uses_profile_name(self) -> None:
        self.write_profile(
            "app",
            {"name": "custom-name", "adapter": "docker-compose", "compose_file": "compose.yml", "http_port_env": "PORT_HTTP"},
        )

        profile = find_profile(self.settings, "custom-name")

        self.assertIsNotNone(profile)
        self.assertEqual("custom-name", profile.name)

    def test_resolve_profile_by_name_requires_project_local_config(self) -> None:
        with self.assertRaisesRegex(DevctlError, "unknown project"):
            resolve_profile(self.settings, "missing")

    def test_load_profile_rejects_invalid_json(self) -> None:
        config_path = self.workspace / "app" / CONFIG_FILENAME
        config_path.parent.mkdir(parents=True)
        config_path.write_text("{invalid\n", encoding="utf-8")

        with self.assertRaisesRegex(DevctlError, "invalid profile JSON"):
            load_profile_file(config_path)

    def test_load_profile_rejects_missing_required_field(self) -> None:
        config_path = self.write_profile(
            "app",
            {"adapter": "docker-compose", "compose_file": "compose.yml", "http_port_env": "PORT_HTTP"},
        )

        with self.assertRaisesRegex(DevctlError, "missing required field 'name'"):
            load_profile_file(config_path)

    def test_load_profile_rejects_unsupported_adapter(self) -> None:
        config_path = self.write_profile(
            "app",
            {"name": "app", "adapter": "make", "compose_file": "compose.yml", "http_port_env": "PORT_HTTP"},
        )

        with self.assertRaisesRegex(DevctlError, "adapter must be 'docker-compose'"):
            load_profile_file(config_path)

    def test_load_profile_rejects_unmanaged_publish_env_source(self) -> None:
        config_path = self.write_profile(
            "app",
            {
                "name": "app",
                "adapter": "docker-compose",
                "compose_file": "compose.yml",
                "http_port_env": "PORT_HTTP",
                "publish_envs": {"REDIS_PUBLISH": {"source": "PORT_REDIS", "target": 6379}},
            },
        )

        with self.assertRaisesRegex(DevctlError, "references unmanaged port env 'PORT_REDIS'"):
            load_profile_file(config_path)

    def test_load_profile_parses_extra_routes(self) -> None:
        config_path = self.write_profile(
            "app",
            {
                "name": "app",
                "adapter": "docker-compose",
                "compose_file": "compose.yml",
                "http_port_env": "PORT_HTTP",
                "extra_port_envs": ["PORT_PHPMYADMIN"],
                "extra_routes": [{"name": "phpmyadmin", "port_env": "PORT_PHPMYADMIN"}],
            },
        )

        profile = load_profile_file(config_path)

        self.assertEqual(1, len(profile.extra_routes))
        self.assertEqual("phpmyadmin", profile.extra_routes[0].name)
        self.assertEqual("PORT_PHPMYADMIN", profile.extra_routes[0].port_env)

    def test_load_profile_rejects_extra_route_port_env_not_managed(self) -> None:
        config_path = self.write_profile(
            "app",
            {
                "name": "app",
                "adapter": "docker-compose",
                "compose_file": "compose.yml",
                "http_port_env": "PORT_HTTP",
                "extra_routes": [{"name": "phpmyadmin", "port_env": "PORT_PHPMYADMIN"}],
            },
        )

        with self.assertRaisesRegex(DevctlError, "must reference an entry in extra_port_envs"):
            load_profile_file(config_path)

    def test_load_profile_rejects_duplicate_extra_route_names(self) -> None:
        config_path = self.write_profile(
            "app",
            {
                "name": "app",
                "adapter": "docker-compose",
                "compose_file": "compose.yml",
                "http_port_env": "PORT_HTTP",
                "extra_port_envs": ["PORT_A", "PORT_B"],
                "extra_routes": [
                    {"name": "pma", "port_env": "PORT_A"},
                    {"name": "pma", "port_env": "PORT_B"},
                ],
            },
        )

        with self.assertRaisesRegex(DevctlError, "duplicate extra_routes name 'pma'"):
            load_profile_file(config_path)

    def test_load_profile_rejects_invalid_extra_route_name(self) -> None:
        config_path = self.write_profile(
            "app",
            {
                "name": "app",
                "adapter": "docker-compose",
                "compose_file": "compose.yml",
                "http_port_env": "PORT_HTTP",
                "extra_port_envs": ["PORT_A"],
                "extra_routes": [{"name": "PMA_Admin", "port_env": "PORT_A"}],
            },
        )

        with self.assertRaisesRegex(DevctlError, r"extra_routes\[0\].name"):
            load_profile_file(config_path)

    def test_publish_source_cannot_be_host_prefixed(self) -> None:
        config_path = self.write_profile(
            "app",
            {
                "name": "app",
                "adapter": "docker-compose",
                "compose_file": "docker-compose.yml",
                "http_port_env": "PORT_HTTP",
                "host_prefixed_port_envs": ["PORT_HTTP"],
                "publish_envs": {"DB_PUBLISH": {"source": "PORT_HTTP", "target": 5432}},
            },
        )

        with self.assertRaisesRegex(DevctlError, "host_prefixed"):
            load_profile_file(config_path)

    def test_load_profile_rejects_non_positive_health_timeout(self) -> None:
        config_path = self.write_profile(
            "app",
            {
                "name": "app",
                "adapter": "docker-compose",
                "compose_file": "compose.yml",
                "http_port_env": "PORT_HTTP",
                "health_timeout_seconds": 0,
            },
        )

        with self.assertRaisesRegex(DevctlError, "health_timeout_seconds"):
            load_profile_file(config_path)

    def test_compose_file_string_normalizes_to_single_item_list(self) -> None:
        config_path = self.write_profile(
            "app",
            {"name": "app", "adapter": "docker-compose", "compose_file": "compose.yml", "http_port_env": "PORT_HTTP"},
        )

        profile = load_profile_file(config_path)

        self.assertEqual(["compose.yml"], profile.compose_files)

    def test_compose_files_list_is_preserved_in_order(self) -> None:
        config_path = self.write_profile(
            "app",
            {
                "name": "app",
                "adapter": "docker-compose",
                "compose_files": ["docker/base.yml", "docker/dev.yml"],
                "http_port_env": "PORT_HTTP",
            },
        )

        profile = load_profile_file(config_path)

        self.assertEqual(["docker/base.yml", "docker/dev.yml"], profile.compose_files)

    def test_rejects_duplicate_compose_files_entries(self) -> None:
        config_path = self.write_profile(
            "app",
            {
                "name": "app",
                "adapter": "docker-compose",
                "compose_files": ["docker/base.yml", "docker/base.yml"],
                "http_port_env": "PORT_HTTP",
            },
        )

        with self.assertRaisesRegex(DevctlError, "compose_files' contains duplicate entries"):
            load_profile_file(config_path)

    def test_rejects_compose_file_and_compose_files_together(self) -> None:
        config_path = self.write_profile(
            "app",
            {
                "name": "app",
                "adapter": "docker-compose",
                "compose_file": "compose.yml",
                "compose_files": ["compose.yml"],
                "http_port_env": "PORT_HTTP",
            },
        )

        with self.assertRaises(DevctlError) as ctx:
            load_profile_file(config_path)
        self.assertIn("exactly one of 'compose_file' or 'compose_files'", str(ctx.exception))

    def test_rejects_profile_without_any_compose_file_field(self) -> None:
        config_path = self.write_profile(
            "app",
            {"name": "app", "adapter": "docker-compose", "http_port_env": "PORT_HTTP"},
        )

        with self.assertRaises(DevctlError):
            load_profile_file(config_path)

    def test_rejects_empty_compose_files_list(self) -> None:
        config_path = self.write_profile(
            "app",
            {"name": "app", "adapter": "docker-compose", "compose_files": [], "http_port_env": "PORT_HTTP"},
        )

        with self.assertRaises(DevctlError):
            load_profile_file(config_path)

    def test_publish_profile_parses_target_and_has_no_http_port_env(self) -> None:
        config_path = self.write_profile(
            "app",
            {
                "name": "app",
                "adapter": "docker-compose",
                "compose_file": "compose.yml",
                "publish": {"service": "web", "container_port": 80},
            },
        )

        profile = load_profile_file(config_path)

        self.assertEqual(PublishTarget(service="web", container_port=80), profile.publish)
        self.assertIsNone(profile.http_port_env)

    def test_rejects_publish_and_http_port_env_together(self) -> None:
        config_path = self.write_profile(
            "app",
            {
                "name": "app",
                "adapter": "docker-compose",
                "compose_file": "compose.yml",
                "http_port_env": "PORT_HTTP",
                "publish": {"service": "web", "container_port": 80},
            },
        )

        with self.assertRaises(DevctlError) as ctx:
            load_profile_file(config_path)
        self.assertIn("exactly one of 'http_port_env' or 'publish'", str(ctx.exception))

    def test_rejects_profile_without_http_port_env_or_publish(self) -> None:
        config_path = self.write_profile(
            "app",
            {"name": "app", "adapter": "docker-compose", "compose_file": "compose.yml"},
        )

        with self.assertRaises(DevctlError):
            load_profile_file(config_path)

    def test_rejects_publish_with_invalid_container_port(self) -> None:
        config_path = self.write_profile(
            "app",
            {
                "name": "app",
                "adapter": "docker-compose",
                "compose_file": "compose.yml",
                "publish": {"service": "web", "container_port": 70000},
            },
        )

        with self.assertRaises(DevctlError):
            load_profile_file(config_path)

    def test_publish_profile_keeps_extra_port_envs_as_managed_ports(self) -> None:
        config_path = self.write_profile(
            "app",
            {
                "name": "app",
                "adapter": "docker-compose",
                "compose_file": "compose.yml",
                "publish": {"service": "web", "container_port": 80},
                "extra_port_envs": ["PORT_DB"],
                "host_prefixed_port_envs": ["PORT_DB"],
            },
        )

        profile = load_profile_file(config_path)

        self.assertEqual(["PORT_DB"], profile.extra_port_envs)

    def test_publish_profile_rejects_host_prefixed_reference_to_unmanaged_env(self) -> None:
        config_path = self.write_profile(
            "app",
            {
                "name": "app",
                "adapter": "docker-compose",
                "compose_file": "compose.yml",
                "publish": {"service": "web", "container_port": 80},
                "host_prefixed_port_envs": ["PORT_HTTP"],
            },
        )

        with self.assertRaises(DevctlError):
            load_profile_file(config_path)

    def test_compose_override_defaults_to_empty_dict(self) -> None:
        config_path = self.write_profile(
            "app",
            {"name": "app", "adapter": "docker-compose", "compose_file": "compose.yml", "http_port_env": "PORT_HTTP"},
        )

        profile = load_profile_file(config_path)

        self.assertEqual({}, profile.compose_override)

    def test_compose_override_parses_arbitrary_fragment(self) -> None:
        fragment = {
            "services": {"db": {"image": "mysql:8.0.33"}},
            "networks": {"proxy": {"external": False}},
            "volumes": {"db-data": None},
        }
        config_path = self.write_profile(
            "app",
            {
                "name": "app",
                "adapter": "docker-compose",
                "compose_file": "compose.yml",
                "http_port_env": "PORT_HTTP",
                "compose_override": fragment,
            },
        )

        profile = load_profile_file(config_path)

        self.assertEqual(fragment, profile.compose_override)

    def test_rejects_non_object_compose_override(self) -> None:
        config_path = self.write_profile(
            "app",
            {
                "name": "app",
                "adapter": "docker-compose",
                "compose_file": "compose.yml",
                "http_port_env": "PORT_HTTP",
                "compose_override": ["services"],
            },
        )

        with self.assertRaisesRegex(DevctlError, "compose_override"):
            load_profile_file(config_path)

    def test_rejects_compose_override_with_non_object_service(self) -> None:
        config_path = self.write_profile(
            "app",
            {
                "name": "app",
                "adapter": "docker-compose",
                "compose_file": "compose.yml",
                "http_port_env": "PORT_HTTP",
                "compose_override": {"services": {"db": "mysql"}},
            },
        )

        with self.assertRaisesRegex(DevctlError, "compose_override.services.db"):
            load_profile_file(config_path)

    def test_rejects_compose_override_with_explicit_null_services(self) -> None:
        config_path = self.write_profile(
            "app",
            {
                "name": "app",
                "adapter": "docker-compose",
                "compose_file": "compose.yml",
                "http_port_env": "PORT_HTTP",
                "compose_override": {"services": None},
            },
        )

        with self.assertRaisesRegex(DevctlError, "compose_override.services' must be an object"):
            load_profile_file(config_path)

    def test_rejects_compose_override_service_with_non_list_ports(self) -> None:
        config_path = self.write_profile(
            "app",
            {
                "name": "app",
                "adapter": "docker-compose",
                "compose_file": "compose.yml",
                "publish": {"service": "web", "container_port": 80},
                "compose_override": {"services": {"web": {"ports": "8080:80"}}},
            },
        )

        with self.assertRaisesRegex(DevctlError, "compose_override.services.web.ports' must be a list"):
            load_profile_file(config_path)

    def test_rejects_name_with_path_separator(self) -> None:
        config_path = self.write_profile(
            "app",
            {
                "name": "../evil",
                "adapter": "docker-compose",
                "compose_file": "compose.yml",
                "http_port_env": "PORT_HTTP",
            },
        )

        with self.assertRaisesRegex(DevctlError, "field 'name' must match"):
            load_profile_file(config_path)

    def test_rejects_name_with_uppercase_or_underscore(self) -> None:
        config_path = self.write_profile(
            "app",
            {
                "name": "My_App",
                "adapter": "docker-compose",
                "compose_file": "compose.yml",
                "http_port_env": "PORT_HTTP",
            },
        )

        with self.assertRaisesRegex(DevctlError, "field 'name' must match"):
            load_profile_file(config_path)

    def test_load_profiles_rejects_duplicate_profile_names(self) -> None:
        self.write_profile(
            "app-one",
            {"name": "app", "adapter": "docker-compose", "compose_file": "a.yml", "http_port_env": "PORT_HTTP"},
        )
        self.write_profile(
            "app-two",
            {"name": "app", "adapter": "docker-compose", "compose_file": "b.yml", "http_port_env": "PORT_HTTP"},
        )

        with self.assertRaisesRegex(DevctlError, "duplicate project profile name 'app'"):
            load_profiles(self.settings)

    def test_nearest_project_config_walks_up_from_nested_directory(self) -> None:
        config_path = self.write_profile(
            "app",
            {"name": "app", "adapter": "docker-compose", "compose_file": "compose.yml", "http_port_env": "PORT_HTTP"},
        )
        nested = config_path.parent / "src" / "feature"
        nested.mkdir(parents=True)

        self.assertEqual(config_path, nearest_project_config(nested))

    def test_resolve_profile_uses_nearest_config_when_git_root_is_unavailable(self) -> None:
        config_path = self.write_profile(
            "app",
            {"name": "app", "adapter": "docker-compose", "compose_file": "compose.yml", "http_port_env": "PORT_HTTP"},
        )
        with (
            patch("devctl.profiles.current_git_root", return_value=None),
            patch("pathlib.Path.cwd", return_value=config_path.parent / "src"),
        ):
            (config_path.parent / "src").mkdir()
            profile = resolve_profile(self.settings, None)

        self.assertEqual("app", profile.name)
