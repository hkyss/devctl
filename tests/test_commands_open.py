import io
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from devctl.commands import open_project
from devctl.errors import DevctlError
from devctl.registry import Registry

from .helpers import TempDirTestCase, make_settings


class OpenProjectTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.settings = make_settings(self.tmp_path)
        Registry(self.settings).ensure()

    def _register(self, name: str = "app", port: int = 50000) -> None:
        registry = Registry(self.settings)
        registry.upsert_starting(
            name=name,
            domain=f"{name}.localhost",
            project_path=str(self.tmp_path / name),
            adapter="docker-compose",
            command="docker compose up",
            host=self.settings.upstream_host,
            port=port,
            log_path=str(self.settings.log_dir / f"{name}.log"),
        )
        registry.set_status(name, "healthy")

    def _run(self, project: str | None, in_container: bool, live: bool = True):
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            patch("devctl.commands._in_container", return_value=in_container),
            patch("devctl.commands.port_accepts_connections", return_value=live),
            patch("devctl.commands.webbrowser") as browser_mock,
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            open_project(self.settings, project)
        return stdout.getvalue(), stderr.getvalue(), browser_mock

    def test_prints_bare_url_on_stdout(self) -> None:
        self._register()

        stdout, _stderr, _browser = self._run("app", in_container=True)

        self.assertEqual("http://app.localhost\n", stdout)

    def test_opens_browser_outside_a_container(self) -> None:
        self._register()

        _stdout, _stderr, browser = self._run("app", in_container=False)

        browser.open.assert_called_once_with("http://app.localhost")

    def test_skips_browser_inside_a_container(self) -> None:
        self._register()

        _stdout, _stderr, browser = self._run("app", in_container=True)

        browser.open.assert_not_called()

    def test_unregistered_project_fails_with_hint(self) -> None:
        with self.assertRaises(DevctlError) as ctx:
            self._run("ghost", in_container=True)

        self.assertIn("devctl up ghost", str(ctx.exception))

    def test_stale_service_warns_on_stderr_but_still_prints_url(self) -> None:
        self._register()

        stdout, stderr, _browser = self._run("app", in_container=True, live=False)

        self.assertEqual("http://app.localhost\n", stdout)
        self.assertIn("stale", stderr)
