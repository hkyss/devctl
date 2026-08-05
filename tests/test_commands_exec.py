from unittest.mock import patch

from devctl.commands import exec_command
from devctl.errors import DevctlError

from .helpers import TempDirTestCase, make_profile, make_settings


class ExecCommandTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.settings = make_settings(self.tmp_path)

    @patch("devctl.commands.adapter_for")
    @patch("devctl.commands.resolve_profile")
    def test_uses_explicit_service_flag(self, resolve_mock, adapter_for_mock) -> None:
        profile = make_profile(name="app", primary_service="web")
        resolve_mock.return_value = profile
        adapter_for_mock.return_value.exec.return_value = 0

        exit_code = exec_command(self.settings, "app", service="cms", tty=True, cmd=["ls"])

        self.assertEqual(0, exit_code)
        adapter_for_mock.return_value.exec.assert_called_once_with("cms", ["ls"], True)

    @patch("devctl.commands.adapter_for")
    @patch("devctl.commands.resolve_profile")
    def test_falls_back_to_primary_service(self, resolve_mock, adapter_for_mock) -> None:
        profile = make_profile(name="app", primary_service="web")
        resolve_mock.return_value = profile
        adapter_for_mock.return_value.exec.return_value = 0

        exec_command(self.settings, None, service=None, tty=False, cmd=["sh"])

        adapter_for_mock.return_value.exec.assert_called_once_with("web", ["sh"], False)

    @patch("devctl.commands.adapter_for")
    @patch("devctl.commands.resolve_profile")
    def test_propagates_child_exit_code(self, resolve_mock, adapter_for_mock) -> None:
        resolve_mock.return_value = make_profile(primary_service="web")
        adapter_for_mock.return_value.exec.return_value = 7

        self.assertEqual(7, exec_command(self.settings, None, service=None, tty=True, cmd=["ls"]))

    @patch("devctl.commands.resolve_profile")
    def test_requires_service_when_no_primary_configured(self, resolve_mock) -> None:
        resolve_mock.return_value = make_profile(primary_service=None)
        with self.assertRaisesRegex(DevctlError, "no --service given"):
            exec_command(self.settings, None, service=None, tty=True, cmd=["ls"])

    @patch("devctl.commands.resolve_profile")
    def test_requires_a_command(self, resolve_mock) -> None:
        resolve_mock.return_value = make_profile(primary_service="web")
        with self.assertRaisesRegex(DevctlError, "requires a command"):
            exec_command(self.settings, None, service=None, tty=True, cmd=[])
