import json
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from devctl.commands import stats

from .helpers import TempDirTestCase, make_profile, make_settings


class StatsCommandTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.settings = make_settings(self.tmp_path)

    @patch("devctl.commands.adapter_for")
    @patch("devctl.commands.resolve_profile")
    def test_not_running_prints_clear_message_and_skips_docker_stats(self, resolve_mock, adapter_for_mock) -> None:
        resolve_mock.return_value = make_profile(name="app")
        adapter_for_mock.return_value.container_ids.return_value = []

        with patch("devctl.commands.subprocess.run") as run_mock, patch("sys.stdout", new=StringIO()) as out:
            stats(self.settings, "app", as_json=False, no_stream=False)

        run_mock.assert_not_called()
        self.assertIn("app", out.getvalue())
        self.assertIn("not running", out.getvalue())

    @patch("devctl.commands.adapter_for")
    @patch("devctl.commands.resolve_profile")
    @patch("devctl.commands.subprocess.run")
    def test_scopes_docker_stats_to_project_containers(self, run_mock, resolve_mock, adapter_for_mock) -> None:
        resolve_mock.return_value = make_profile(name="app")
        adapter_for_mock.return_value.container_ids.return_value = ["c1", "c2"]
        run_mock.return_value = SimpleNamespace(returncode=0)

        stats(self.settings, "app", as_json=False, no_stream=True)

        run_mock.assert_called_once_with(["docker", "stats", "--no-stream", "c1", "c2"])

    @patch("devctl.commands.adapter_for")
    @patch("devctl.commands.resolve_profile")
    @patch("devctl.commands.subprocess.run")
    def test_json_mode_emits_single_json_array(self, run_mock, resolve_mock, adapter_for_mock) -> None:
        resolve_mock.return_value = make_profile(name="app")
        adapter_for_mock.return_value.container_ids.return_value = ["c1", "c2"]
        run_mock.return_value = SimpleNamespace(stdout='{"Name": "c1", "CPUPerc": "1.00%"}\n{"Name": "c2", "CPUPerc": "2.00%"}\n')

        with patch("sys.stdout", new=StringIO()) as out:
            stats(self.settings, "app", as_json=True, no_stream=False)

        called_command = run_mock.call_args.args[0]
        self.assertIn("--format", called_command)
        self.assertIn("--no-stream", called_command)
        payload = json.loads(out.getvalue())
        self.assertEqual(2, len(payload))
        self.assertEqual("c1", payload[0]["Name"])
