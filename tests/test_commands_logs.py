from unittest.mock import patch

from devctl.commands import logs
from devctl.errors import DevctlError

from .helpers import TempDirTestCase, make_profile, make_settings


class LogsCommandTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.settings = make_settings(self.tmp_path)

    @patch("devctl.commands.resolve_profile")
    def test_no_flags_falls_back_to_static_log_file(self, resolve_mock) -> None:
        profile = make_profile(name="app")
        resolve_mock.return_value = profile
        log_path = self.settings.log_dir / "app.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("hello\n", encoding="utf-8")

        with patch("devctl.commands.adapter_for") as adapter_for_mock:
            logs(self.settings, "app", follow=False)
            adapter_for_mock.assert_not_called()

    @patch("devctl.commands.adapter_for")
    @patch("devctl.commands.resolve_profile")
    def test_service_flag_uses_docker_compose_logs(self, resolve_mock, adapter_for_mock) -> None:
        resolve_mock.return_value = make_profile(name="app")
        adapter_for_mock.return_value.logs.return_value = 0

        logs(self.settings, "app", follow=True, services=["cms"], since="10m", tail=50)

        adapter_for_mock.return_value.logs.assert_called_once_with(follow=True, services=["cms"], since="10m", tail=50)

    @patch("devctl.commands.adapter_for")
    @patch("devctl.commands.resolve_profile")
    def test_since_alone_also_switches_to_compose_logs(self, resolve_mock, adapter_for_mock) -> None:
        resolve_mock.return_value = make_profile(name="app")
        adapter_for_mock.return_value.logs.return_value = 0

        logs(self.settings, "app", follow=False, since="5m")

        adapter_for_mock.return_value.logs.assert_called_once_with(follow=False, services=[], since="5m", tail=None)

    @patch("devctl.commands.adapter_for")
    @patch("devctl.commands.resolve_profile")
    def test_nonzero_exit_raises_devctl_error(self, resolve_mock, adapter_for_mock) -> None:
        resolve_mock.return_value = make_profile(name="app")
        adapter_for_mock.return_value.logs.return_value = 1

        with self.assertRaises(DevctlError):
            logs(self.settings, "app", follow=False, services=["cms"])
