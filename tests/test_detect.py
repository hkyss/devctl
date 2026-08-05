from devctl.detect import PortBinding, detect_compose_file, detect_env_file, scan_published_ports

from .helpers import TempDirTestCase


class DetectComposeFileTests(TempDirTestCase):
    def test_returns_preferred_file_when_it_exists(self) -> None:
        (self.tmp_path / "compose.dev.yml").write_text("services: {}\n", encoding="utf-8")

        self.assertEqual("compose.dev.yml", detect_compose_file(self.tmp_path, "compose.dev.yml"))

    def test_falls_back_to_standard_candidates(self) -> None:
        (self.tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")

        self.assertEqual("compose.yaml", detect_compose_file(self.tmp_path, "docker-compose.yml"))

    def test_returns_none_when_nothing_exists(self) -> None:
        self.assertIsNone(detect_compose_file(self.tmp_path, "docker-compose.yml"))


class DetectEnvFileTests(TempDirTestCase):
    def test_finds_dot_env(self) -> None:
        (self.tmp_path / ".env").write_text("PORT_HTTP=5173\n", encoding="utf-8")

        self.assertEqual(".env", detect_env_file(self.tmp_path))

    def test_returns_none_without_dot_env(self) -> None:
        self.assertIsNone(detect_env_file(self.tmp_path))


class ScanPublishedPortsTests(TempDirTestCase):
    def test_env_var_with_default(self) -> None:
        text = 'services:\n  web:\n    ports:\n      - "${PORT_HTTP:-5173}:5173"\n'

        self.assertEqual(
            [PortBinding(env="PORT_HTTP", default=5173, host_port=None, container_port=5173)],
            scan_published_ports(text),
        )

    def test_env_var_without_default(self) -> None:
        text = "services:\n  api:\n    ports:\n      - ${PORT_API}:8080\n"

        self.assertEqual(
            [PortBinding(env="PORT_API", default=None, host_port=None, container_port=8080)],
            scan_published_ports(text),
        )

    def test_env_var_with_ip_prefix(self) -> None:
        text = 'services:\n  db:\n    ports:\n      - "127.0.0.1:${PORT_DB:-5432}:5432"\n'

        self.assertEqual(
            [PortBinding(env="PORT_DB", default=5432, host_port=None, container_port=5432)],
            scan_published_ports(text),
        )

    def test_literal_published_port(self) -> None:
        text = 'services:\n  web:\n    ports:\n      - "8080:80"\n'

        self.assertEqual(
            [PortBinding(env=None, default=None, host_port=8080, container_port=80)],
            scan_published_ports(text),
        )

    def test_container_only_port_is_ignored(self) -> None:
        text = 'services:\n  redis:\n    ports:\n      - "6379"\n'

        self.assertEqual([], scan_published_ports(text))

    def test_long_syntax_published(self) -> None:
        text = "services:\n  web:\n    ports:\n      - target: 3000\n        published: ${PORT_WEB:-3000}\n"

        self.assertEqual(
            [PortBinding(env="PORT_WEB", default=3000, host_port=None, container_port=None)],
            scan_published_ports(text),
        )

    def test_long_syntax_literal_published(self) -> None:
        text = "services:\n  web:\n    ports:\n      - target: 80\n        published: 9000\n"

        self.assertEqual(
            [PortBinding(env=None, default=None, host_port=9000, container_port=None)],
            scan_published_ports(text),
        )

    def test_multiple_services_keep_order(self) -> None:
        text = (
            'services:\n  web:\n    ports:\n      - "${PORT_HTTP:-5173}:5173"\n  admin:\n    ports:\n      - "${PORT_ADMIN:-8081}:8081"\n'
        )

        self.assertEqual(
            ["PORT_HTTP", "PORT_ADMIN"],
            [binding.env for binding in scan_published_ports(text)],
        )
