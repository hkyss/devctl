import io
import json
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from unittest.mock import patch

from devctl.commands import up
from devctl.errors import DevctlError
from devctl.profiles import ExtraRoute
from devctl.registry import Registry

from .helpers import TempDirTestCase, make_profile, make_settings


class UpJsonTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.settings = make_settings(self.tmp_path)
        Registry(self.settings).ensure()
        self.project_dir = self.tmp_path / "app"
        self.project_dir.mkdir(parents=True)

    def _run_up(self, profile, wait_result=(True, None)) -> tuple[str, str, DevctlError | None]:
        stdout, stderr = io.StringIO(), io.StringIO()
        error: DevctlError | None = None
        with ExitStack() as stack:
            stack.enter_context(patch("devctl.commands.ensure_runtime"))
            stack.enter_context(patch("devctl.commands.resolve_profile", return_value=profile))
            adapter_mock = stack.enter_context(patch("devctl.commands.adapter_for"))
            stack.enter_context(patch("devctl.commands.wait_for_port", return_value=wait_result))
            stack.enter_context(patch("devctl.commands.CaddyfileWriter"))
            adapter = adapter_mock.return_value
            adapter.command_up.return_value = ["docker", "compose", "up"]
            adapter.command_pre_up.side_effect = lambda c: ["docker", "compose", "run", *c]
            adapter.up.return_value = 0
            stack.enter_context(redirect_stdout(stdout))
            stack.enter_context(redirect_stderr(stderr))
            try:
                up(self.settings, None, as_json=True)
            except DevctlError as exc:
                error = exc
        return stdout.getvalue(), stderr.getvalue(), error

    def test_stdout_is_a_single_json_payload(self) -> None:
        profile = make_profile(
            path=str(self.project_dir),
            extra_port_envs=["PORT_PHPMYADMIN"],
            extra_routes=[ExtraRoute(name="phpmyadmin", port_env="PORT_PHPMYADMIN")],
        )

        stdout, stderr, error = self._run_up(profile)

        self.assertIsNone(error)
        payload = json.loads(stdout)
        self.assertEqual("app", payload["name"])
        self.assertEqual("healthy", payload["status"])
        self.assertEqual("http://app.localhost", payload["url"])
        self.assertIn("port", payload)
        self.assertIn("log_path", payload)
        self.assertEqual(1, len(payload["extra_routes"]))
        self.assertEqual("phpmyadmin.app.localhost", payload["extra_routes"][0]["domain"])

    def test_progress_output_goes_to_stderr(self) -> None:
        profile = make_profile(path=str(self.project_dir))

        stdout, stderr, error = self._run_up(profile)

        self.assertIsNone(error)
        self.assertNotIn("Starting containers", stdout)
        self.assertIn("Starting containers", stderr)

    def test_failed_health_check_still_emits_json(self) -> None:
        profile = make_profile(path=str(self.project_dir))

        stdout, stderr, error = self._run_up(profile, wait_result=(False, "connection refused"))

        self.assertIsNotNone(error)
        payload = json.loads(stdout)
        self.assertEqual("unhealthy", payload["status"])
