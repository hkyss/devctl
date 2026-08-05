import unittest
from unittest.mock import patch

from devctl.errors import DevctlError
from devctl.settings import load_settings


class SettingsTests(unittest.TestCase):
    @patch.dict("os.environ", {"DEVCTL_PORT_START": "notaport"}, clear=False)
    def test_invalid_port_start_raises_devctl_error(self) -> None:
        with self.assertRaises(DevctlError):
            load_settings()

    @patch.dict("os.environ", {"DEVCTL_PORT_START": "60000", "DEVCTL_PORT_END": "50000"}, clear=False)
    def test_start_after_end_raises_devctl_error(self) -> None:
        with self.assertRaises(DevctlError):
            load_settings()

    @patch.dict("os.environ", {"DEVCTL_PORT_START": "70000"}, clear=False)
    def test_out_of_range_port_raises_devctl_error(self) -> None:
        with self.assertRaises(DevctlError):
            load_settings()
