import json
import unittest
from dataclasses import replace
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from devctl.commands import _list_dangling_volumes, _warn_upstream_publish_mismatch, doctor
from devctl.errors import DevctlError

from .helpers import TempDirTestCase, make_settings


class UpstreamPublishAdvisoryTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.settings = make_settings(self.tmp_path)

    def _run(self, settings) -> str:
        with patch("sys.stdout", new=StringIO()) as out:
            _warn_upstream_publish_mismatch(settings)
        return out.getvalue()

    def test_warns_on_loopback_publish_with_remote_upstream(self) -> None:
        mismatched = replace(self.settings, publish_host="127.0.0.1", upstream_host="host.docker.internal")
        self.assertIn("host.docker.internal", self._run(mismatched))

    def test_silent_when_hosts_align(self) -> None:
        aligned = replace(self.settings, publish_host="127.0.0.1", upstream_host="127.0.0.1")
        self.assertEqual("", self._run(aligned))

    def test_doctor_json_emits_object_and_still_raises_on_failure(self) -> None:
        with patch("sys.stdout", new=StringIO()) as out, self.assertRaises(DevctlError):
            doctor(self.settings, as_json=True)
        payload = json.loads(out.getvalue())
        self.assertIsInstance(payload, dict)
        self.assertIn("docker", payload)


class ListDanglingVolumesTests(unittest.TestCase):
    @patch("devctl.commands.subprocess.run")
    def test_parses_volume_names(self, run_mock) -> None:
        run_mock.return_value = SimpleNamespace(returncode=0, stdout="vol_a\nvol_b\n")
        self.assertEqual(["vol_a", "vol_b"], _list_dangling_volumes())

    @patch("devctl.commands.subprocess.run")
    def test_empty_when_docker_fails(self, run_mock) -> None:
        run_mock.return_value = SimpleNamespace(returncode=1, stdout="")
        self.assertEqual([], _list_dangling_volumes())
