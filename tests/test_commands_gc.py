from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from devctl.commands import _list_dangling_images, _system_df_volume_sizes, gc
from devctl.errors import DevctlError

from .helpers import TempDirTestCase


class ListDanglingImagesTests(TempDirTestCase):
    @patch("devctl.commands.subprocess.run")
    def test_parses_id_and_name(self, run_mock) -> None:
        run_mock.return_value = SimpleNamespace(returncode=0, stdout="abc123\t<none>:<none>\ndef456\tmyapp:latest\n")
        self.assertEqual(
            [("abc123", "<none>:<none>"), ("def456", "myapp:latest")],
            _list_dangling_images(),
        )

    @patch("devctl.commands.subprocess.run")
    def test_empty_when_docker_fails(self, run_mock) -> None:
        run_mock.return_value = SimpleNamespace(returncode=1, stdout="")
        self.assertEqual([], _list_dangling_images())


class SystemDfVolumeSizesTests(TempDirTestCase):
    @patch("devctl.commands.subprocess.run")
    def test_maps_name_to_size(self, run_mock) -> None:
        run_mock.return_value = SimpleNamespace(
            returncode=0,
            stdout=("Local Volumes:\nVOLUME NAME   LINKS     SIZE\nvol_a         0         12MB\nvol_b         0         3.4MB\n"),
        )
        sizes = _system_df_volume_sizes()
        self.assertEqual("12MB", sizes.get("vol_a"))
        self.assertEqual("3.4MB", sizes.get("vol_b"))

    @patch("devctl.commands.subprocess.run")
    def test_empty_on_unparseable_output(self, run_mock) -> None:
        run_mock.return_value = SimpleNamespace(returncode=0, stdout="garbage\n")
        self.assertEqual({}, _system_df_volume_sizes())

    @patch("devctl.commands.subprocess.run", side_effect=OSError("no docker"))
    def test_empty_when_docker_missing(self, run_mock) -> None:
        self.assertEqual({}, _system_df_volume_sizes())


class GcDryRunTests(TempDirTestCase):
    @patch("devctl.commands._system_df_volume_sizes", return_value={})
    @patch("devctl.commands._list_dangling_images", return_value=[])
    @patch("devctl.commands._list_dangling_volumes", return_value=["vol_a", "vol_b"])
    @patch("devctl.commands.subprocess.run")
    def test_dry_run_prints_and_removes_nothing(self, run_mock, *_mocks) -> None:
        with patch("sys.stdout", new=StringIO()) as out:
            gc(dry_run=True, yes=False, volumes=True, images=False)
        run_mock.assert_not_called()
        self.assertIn("vol_a", out.getvalue())
        self.assertIn("vol_b", out.getvalue())

    @patch("devctl.commands._list_dangling_images", return_value=[])
    @patch("devctl.commands._list_dangling_volumes", return_value=[])
    def test_nothing_to_clean_up(self, *_mocks) -> None:
        with patch("sys.stdout", new=StringIO()) as out:
            gc(dry_run=False, yes=True, volumes=True, images=False)
        self.assertIn("nothing to clean up", out.getvalue())


class GcYesModeTests(TempDirTestCase):
    @patch("devctl.commands._list_dangling_images", return_value=[])
    @patch("devctl.commands._list_dangling_volumes", return_value=["vol_a", "vol_b"])
    @patch("devctl.commands.subprocess.run")
    def test_yes_removes_all_without_prompt(self, run_mock, *_mocks) -> None:
        run_mock.return_value = SimpleNamespace(returncode=0, stdout="", stderr="")
        with patch("sys.stdout", new=StringIO()):
            gc(dry_run=False, yes=True, volumes=True, images=False)
        calls = [call.args[0] for call in run_mock.call_args_list]
        self.assertIn(["docker", "volume", "rm", "vol_a"], calls)
        self.assertIn(["docker", "volume", "rm", "vol_b"], calls)

    @patch("devctl.commands._list_dangling_images", return_value=[("img1", "myapp:latest")])
    @patch("devctl.commands._list_dangling_volumes", return_value=["vol_a"])
    @patch("devctl.commands.subprocess.run")
    def test_images_only_leaves_volumes_untouched(self, run_mock, *_mocks) -> None:
        run_mock.return_value = SimpleNamespace(returncode=0, stdout="", stderr="")
        with patch("sys.stdout", new=StringIO()):
            gc(dry_run=False, yes=True, volumes=False, images=True)
        calls = [call.args[0] for call in run_mock.call_args_list]
        self.assertIn(["docker", "image", "rm", "img1"], calls)
        self.assertNotIn(["docker", "volume", "rm", "vol_a"], calls)

    @patch("devctl.commands._list_dangling_images", return_value=[])
    @patch("devctl.commands._list_dangling_volumes", return_value=["vol_a", "vol_b"])
    @patch("devctl.commands.subprocess.run")
    def test_partial_failure_raises_and_reports(self, run_mock, *_mocks) -> None:
        def side_effect(cmd, **kwargs):
            if cmd == ["docker", "volume", "rm", "vol_b"]:
                return SimpleNamespace(returncode=1, stdout="", stderr="volume is in use")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        run_mock.side_effect = side_effect
        with patch("sys.stdout", new=StringIO()) as out, self.assertRaises(DevctlError) as ctx:
            gc(dry_run=False, yes=True, volumes=True, images=False)
        self.assertEqual(1, ctx.exception.code)
        self.assertIn("vol_b", out.getvalue())


class GcInteractivePromptTests(TempDirTestCase):
    @patch("devctl.commands._system_df_volume_sizes", return_value={})
    @patch("devctl.commands._list_dangling_images", return_value=[])
    @patch("devctl.commands._list_dangling_volumes", return_value=["vol_a"])
    @patch("devctl.commands.subprocess.run")
    @patch("devctl.commands.sys.stdin")
    def test_tty_accept_removes(self, stdin_mock, run_mock, *_mocks) -> None:
        stdin_mock.isatty.return_value = True
        run_mock.return_value = SimpleNamespace(returncode=0, stdout="", stderr="")
        with patch("builtins.input", return_value="y"), patch("sys.stdout", new=StringIO()):
            gc(dry_run=False, yes=False, volumes=True, images=False)
        calls = [call.args[0] for call in run_mock.call_args_list]
        self.assertIn(["docker", "volume", "rm", "vol_a"], calls)

    @patch("devctl.commands._system_df_volume_sizes", return_value={})
    @patch("devctl.commands._list_dangling_images", return_value=[])
    @patch("devctl.commands._list_dangling_volumes", return_value=["vol_a"])
    @patch("devctl.commands.subprocess.run")
    @patch("devctl.commands.sys.stdin")
    def test_tty_decline_removes_nothing(self, stdin_mock, run_mock, *_mocks) -> None:
        stdin_mock.isatty.return_value = True
        with patch("builtins.input", return_value="n"), patch("sys.stdout", new=StringIO()) as out:
            gc(dry_run=False, yes=False, volumes=True, images=False)
        run_mock.assert_not_called()
        self.assertIn("aborted", out.getvalue())

    @patch("devctl.commands._system_df_volume_sizes", return_value={})
    @patch("devctl.commands._list_dangling_images", return_value=[])
    @patch("devctl.commands._list_dangling_volumes", return_value=["vol_a"])
    @patch("devctl.commands.subprocess.run")
    @patch("devctl.commands.sys.stdin")
    def test_non_tty_no_yes_behaves_like_dry_run(self, stdin_mock, run_mock, *_mocks) -> None:
        stdin_mock.isatty.return_value = False
        with patch("sys.stdout", new=StringIO()):
            gc(dry_run=False, yes=False, volumes=True, images=False)
        run_mock.assert_not_called()

    @patch("devctl.commands._system_df_volume_sizes", return_value={})
    @patch("devctl.commands._list_dangling_images", return_value=[])
    @patch("devctl.commands._list_dangling_volumes", return_value=["vol_a"])
    @patch("devctl.commands.subprocess.run")
    def test_dry_run_wins_even_with_yes(self, run_mock, *_mocks) -> None:
        with patch("sys.stdout", new=StringIO()):
            gc(dry_run=True, yes=True, volumes=True, images=False)
        run_mock.assert_not_called()
