from unittest.mock import patch

from devctl.errors import DevctlError
from devctl.ports import allocate_ports
from devctl.proxy import CaddyfileWriter
from devctl.registry import ExtraRouteEntry, Registry

from .helpers import TempDirTestCase, make_settings


class RegistryProxyPortsTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.settings = make_settings(self.tmp_path)
        self.registry = Registry(self.settings)
        self.registry.ensure()

    def test_registry_lifecycle_and_active_ports(self) -> None:
        self.registry.upsert_starting(
            name="app",
            domain="app.localhost",
            project_path="/workspace/app",
            adapter="docker-compose",
            command="docker compose up",
            host="127.0.0.1",
            port=8080,
            log_path="/state/logs/app.log",
        )

        self.assertEqual([8080], self.registry.active_ports())
        self.assertEqual(["app"], self.registry.names())
        self.registry.set_status("app", "unhealthy")
        self.assertEqual([], self.registry.active_ports())
        self.registry.delete("app")
        self.assertEqual([], self.registry.names())

    def test_stop_target_returns_stored_compose_project_name(self) -> None:
        self.registry.upsert_starting(
            name="app",
            domain="app.localhost",
            project_path="/workspace/app",
            adapter="docker-compose",
            command="docker compose up",
            host="127.0.0.1",
            port=8080,
            log_path="/state/logs/app.log",
            compose_project_name="devctl_app_bob",
        )

        target = self.registry.stop_target("app")

        self.assertEqual("devctl_app_bob", target.compose_project_name)

    def test_stop_target_compose_project_name_defaults_to_none(self) -> None:
        self.registry.upsert_starting(
            name="app",
            domain="app.localhost",
            project_path="/workspace/app",
            adapter="docker-compose",
            command="docker compose up",
            host="127.0.0.1",
            port=8080,
            log_path="/state/logs/app.log",
        )

        target = self.registry.stop_target("app")

        self.assertIsNone(target.compose_project_name)

    def test_proxy_writes_empty_caddyfile_when_no_routes_exist(self) -> None:
        CaddyfileWriter(self.settings, self.registry).write()

        caddyfile = self.settings.caddyfile_path.read_text(encoding="utf-8")
        self.assertIn("auto_https off", caddyfile)
        self.assertIn("No active devctl services", caddyfile)

    def test_proxy_applies_the_caddyfile_it_just_wrote(self) -> None:
        with patch("devctl.proxy.reload_proxy") as reload_mock:
            CaddyfileWriter(self.settings, self.registry).write()

        reload_mock.assert_called_once_with(self.settings)

    def test_proxy_names_the_missing_host_instead_of_answering_empty(self) -> None:
        CaddyfileWriter(self.settings, self.registry).write()

        caddyfile = self.settings.caddyfile_path.read_text(encoding="utf-8")
        self.assertIn(":80 {", caddyfile)
        self.assertIn("no route for {host}", caddyfile)

    def test_proxy_writes_routes_for_active_services(self) -> None:
        self.registry.upsert_starting(
            name="app",
            domain="app.localhost",
            project_path="/workspace/app",
            adapter="docker-compose",
            command="docker compose up",
            host="host.docker.internal",
            port=50000,
            log_path="/state/logs/app.log",
        )

        CaddyfileWriter(self.settings, self.registry).write()

        caddyfile = self.settings.caddyfile_path.read_text(encoding="utf-8")
        self.assertIn("http://app.localhost {", caddyfile)
        self.assertIn("reverse_proxy host.docker.internal:50000", caddyfile)

    def test_extra_routes_survive_an_unhealthy_parent_and_die_with_it(self) -> None:
        self.registry.upsert_starting(
            name="app",
            domain="app.localhost",
            project_path="/workspace/app",
            adapter="docker-compose",
            command="docker compose up",
            host="host.docker.internal",
            port=50000,
            log_path="/state/logs/app.log",
        )
        self.registry.set_extra_routes(
            "app",
            [ExtraRouteEntry(route_name="phpmyadmin", domain="phpmyadmin.app.localhost", host="host.docker.internal", port=50001)],
        )

        routes = self.registry.routes()
        self.assertIn(("app.localhost", "host.docker.internal", 50000), routes)
        self.assertIn(("phpmyadmin.app.localhost", "host.docker.internal", 50001), routes)

        self.registry.set_status("app", "unhealthy")
        routes = self.registry.routes()
        self.assertIn(("app.localhost", "host.docker.internal", 50000), routes)
        self.assertIn(("phpmyadmin.app.localhost", "host.docker.internal", 50001), routes)

        self.registry.delete("app")
        self.assertEqual([], self.registry.routes())

    def test_set_extra_routes_replaces_prior_entries(self) -> None:
        self.registry.upsert_starting(
            name="app",
            domain="app.localhost",
            project_path="/workspace/app",
            adapter="docker-compose",
            command="docker compose up",
            host="host.docker.internal",
            port=50000,
            log_path="/state/logs/app.log",
        )
        self.registry.set_extra_routes(
            "app",
            [ExtraRouteEntry(route_name="phpmyadmin", domain="phpmyadmin.app.localhost", host="host.docker.internal", port=50001)],
        )
        self.registry.set_extra_routes(
            "app",
            [ExtraRouteEntry(route_name="phpmyadmin", domain="phpmyadmin.app.localhost", host="host.docker.internal", port=50002)],
        )

        entries = self.registry.extra_routes_for("app")
        self.assertEqual(1, len(entries))
        self.assertEqual(50002, entries[0].port)

    def test_delete_removes_extra_routes_for_project(self) -> None:
        self.registry.upsert_starting(
            name="app",
            domain="app.localhost",
            project_path="/workspace/app",
            adapter="docker-compose",
            command="docker compose up",
            host="host.docker.internal",
            port=50000,
            log_path="/state/logs/app.log",
        )
        self.registry.set_extra_routes(
            "app",
            [ExtraRouteEntry(route_name="phpmyadmin", domain="phpmyadmin.app.localhost", host="host.docker.internal", port=50001)],
        )

        self.registry.delete("app")

        self.assertEqual([], self.registry.extra_routes_for("app"))

    def _reserve_port(self, port: int) -> None:
        self.registry.upsert_starting(
            name=f"used-{port}",
            domain=f"used-{port}.localhost",
            project_path=f"/workspace/used-{port}",
            adapter="docker-compose",
            command="docker compose up",
            host="127.0.0.1",
            port=port,
            log_path=f"/state/logs/used-{port}.log",
        )

    def test_allocate_ports_prefers_preferred_ports_and_skips_active_ports(self) -> None:
        self._reserve_port(50001)

        with patch("devctl.ports.is_port_free", return_value=True):
            self.assertEqual([50000, 50002], allocate_ports(self.settings, self.registry, 2, [50001, 50002]))

    def test_allocate_ports_keeps_each_slot_on_its_own_preferred_port(self) -> None:
        self._reserve_port(50001)

        with patch("devctl.ports.is_port_free", return_value=True):
            allocated = allocate_ports(self.settings, self.registry, 4, [50001, 50002, 50003, 50004])

        self.assertEqual([50002, 50003, 50004], allocated[1:])
        self.assertNotIn(allocated[0], (50002, 50003, 50004))

    def test_allocate_ports_falls_back_when_preferred_is_exhausted(self) -> None:
        with patch("devctl.ports.is_port_free", return_value=True):
            self.assertEqual([50005, 50000], allocate_ports(self.settings, self.registry, 2, [50005]))

    def test_allocate_ports_raises_when_no_ports_are_free(self) -> None:
        with patch("devctl.ports.is_port_free", return_value=False), self.assertRaisesRegex(DevctlError, "could not allocate"):
            allocate_ports(self.settings, self.registry, 1, [])

    def test_allocate_ports_reclaims_ports_the_project_already_publishes(self) -> None:
        self._reserve_port(50001)
        self.registry.upsert_starting(
            name="app",
            domain="app.localhost",
            project_path="/workspace/app",
            adapter="docker-compose",
            command="docker compose up",
            host="127.0.0.1",
            port=50000,
            log_path="/state/logs/app.log",
        )

        with patch("devctl.ports.is_port_free", return_value=False):
            allocated = allocate_ports(
                self.settings,
                self.registry,
                2,
                [50000, 50002],
                reclaimable={50000, 50002},
                exclude_name="app",
            )

        self.assertEqual([50000, 50002], allocated)

    def test_allocate_ports_reuses_remembered_ports_without_preferred_ports(self) -> None:
        with patch("devctl.ports.is_port_free", return_value=True):
            allocated = allocate_ports(self.settings, self.registry, 2, [], sticky=[50007, 50008])

        self.assertEqual([50007, 50008], allocated)

    def test_preferred_ports_win_over_remembered_ones(self) -> None:
        with patch("devctl.ports.is_port_free", return_value=True):
            allocated = allocate_ports(self.settings, self.registry, 1, [50003], sticky=[50007])

        self.assertEqual([50003], allocated)

    def test_remembered_port_is_skipped_when_someone_else_took_it(self) -> None:
        self._reserve_port(50007)

        with patch("devctl.ports.is_port_free", return_value=True):
            allocated = allocate_ports(self.settings, self.registry, 1, [], sticky=[50007])

        self.assertEqual([50000], allocated)

    def test_remembered_port_never_swallows_another_slots_preferred_port(self) -> None:
        with patch("devctl.ports.is_port_free", return_value=True):
            allocated = allocate_ports(self.settings, self.registry, 2, [50003, 50007], sticky=[50007, 50008])

        self.assertEqual([50003, 50007], allocated)

    def test_allocated_ports_are_remembered_per_slot_and_survive_delete(self) -> None:
        self.registry.set_allocated_ports("app", {"@http": 18080, "PORT_DB": 13306})

        self.assertEqual({"@http": 18080, "PORT_DB": 13306}, self.registry.allocated_ports_for("app"))

        self.registry.delete("app")
        self.assertEqual({"@http": 18080, "PORT_DB": 13306}, self.registry.allocated_ports_for("app"))

        self.registry.forget_allocated_ports("app")
        self.assertEqual({}, self.registry.allocated_ports_for("app"))

    def test_active_ports_can_exclude_a_single_project(self) -> None:
        self._reserve_port(50001)
        self._reserve_port(50002)

        self.assertEqual([50002], self.registry.active_ports(exclude="used-50001"))

    def test_connection_helper_closes_connections(self) -> None:
        import gc
        import sqlite3
        from unittest.mock import patch

        real_connect = sqlite3.connect
        opened = []

        def tracking_connect(*args, **kwargs):
            conn = real_connect(*args, **kwargs)
            opened.append(conn)
            return conn

        with patch("devctl.registry.sqlite3.connect", side_effect=tracking_connect):
            self.registry.ensure()
            self.registry.names()

        gc.collect()
        for conn in opened:
            with self.assertRaises(sqlite3.ProgrammingError):
                conn.execute("SELECT 1")
