import os
import signal
import subprocess
import time
import unittest
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parent.parent
WRAPPER = REPO_ROOT / "devctl"

STUB_DOCKER = """#!/bin/sh
printf '%s\\n' "docker $*" >> "${STUB_LOG}"
case "$1" in
  ps)
    if [ -n "${STUB_PS_FILE:-}" ]; then cat "${STUB_PS_FILE}"; fi
    ;;
  compose)
    case " $* " in
      *" run "*)
        if [ -n "${STUB_RUN_SLEEP:-}" ]; then
          trap '' HUP
          sleep "${STUB_RUN_SLEEP}"
        fi
        ;;
    esac
    ;;
esac
exit 0
"""


class WrapperTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        bin_dir = self.tmp_path / "bin"
        bin_dir.mkdir()
        stub = bin_dir / "docker"
        stub.write_text(STUB_DOCKER, encoding="utf-8")
        stub.chmod(0o755)
        self.log_path = self.tmp_path / "stub.log"
        self.env = os.environ.copy()
        self.env["PATH"] = f"{bin_dir}:{self.env['PATH']}"
        self.env["STUB_LOG"] = str(self.log_path)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _log_lines(self) -> list[str]:
        if not self.log_path.exists():
            return []
        return self.log_path.read_text(encoding="utf-8").splitlines()

    def _wait_for(self, predicate: Callable[[], bool], timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.05)
        return False

    def _run_wrapper(self, *args: str, env: dict[str, str] | None = None, **popen_kwargs) -> subprocess.Popen:
        return subprocess.Popen(
            [str(WRAPPER), *args],
            env=env or self.env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **popen_kwargs,
        )

    def test_run_names_container_after_wrapper_pid(self) -> None:
        proc = self._run_wrapper("list")
        proc.wait(timeout=30)

        run_lines = [line for line in self._log_lines() if " run " in line]
        self.assertEqual(1, len(run_lines))
        self.assertIn(f"--name devctl-cli-{proc.pid}", run_lines[0])

    def test_sighup_removes_own_container(self) -> None:
        env = dict(self.env, STUB_RUN_SLEEP="30")
        proc = self._run_wrapper("list", env=env, start_new_session=True)
        self.assertTrue(
            self._wait_for(lambda: any(" run " in line for line in self._log_lines())),
            "wrapper never started the run container",
        )

        os.killpg(proc.pid, signal.SIGHUP)

        self.assertTrue(
            self._wait_for(lambda: f"docker rm -f devctl-cli-{proc.pid}" in self._log_lines()),
            f"container devctl-cli-{proc.pid} was not removed after SIGHUP: {self._log_lines()}",
        )
        proc.wait(timeout=30)

    def test_reaper_removes_only_orphaned_containers(self) -> None:
        dead = subprocess.Popen(["sh", "-c", "exit 0"])
        dead.wait(timeout=30)
        dead_pid = dead.pid
        live_pid = os.getpid()
        ps_file = self.tmp_path / "ps.txt"
        ps_file.write_text(
            f"devctl-cli-{dead_pid}\ndevctl-cli-{live_pid}\ndevctl-cli-abc\n",
            encoding="utf-8",
        )
        env = dict(self.env, STUB_PS_FILE=str(ps_file))

        proc = self._run_wrapper("list", env=env)
        proc.wait(timeout=30)

        lines = self._log_lines()
        self.assertIn(f"docker rm -f devctl-cli-{dead_pid}", lines)
        self.assertNotIn(f"docker rm -f devctl-cli-{live_pid}", lines)
        self.assertNotIn("docker rm -f devctl-cli-abc", lines)
