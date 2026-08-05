import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parent.parent
WRAPPER = REPO_ROOT / "devctl"

STUB_DOCKER = """#!/bin/sh
printf '%s\\n' "docker $*" >> "${STUB_LOG}"
case "$1" in
  compose)
    case " $* " in
      *" --entrypoint make "*)
        case " $* " in
          *" -qp"*)
            if [ -n "${STUB_MAKE_QP_OUT:-}" ]; then cat "${STUB_MAKE_QP_OUT}"; fi
            ;;
          *)
            if [ -n "${STUB_MAKE_N_OUT:-}" ]; then cat "${STUB_MAKE_N_OUT}"; fi
            ;;
        esac
        exit "${STUB_MAKE_RC:-0}"
        ;;
      *" devctl env "*)
        if [ -n "${STUB_ENV_OUT:-}" ]; then cat "${STUB_ENV_OUT}"; fi
        exit "${STUB_ENV_RC:-0}"
        ;;
    esac
    ;;
esac
exit 0
"""


class WrapperMakeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        bin_dir = self.tmp_path / "bin"
        bin_dir.mkdir()
        stub = bin_dir / "docker"
        stub.write_text(STUB_DOCKER, encoding="utf-8")
        stub.chmod(0o755)
        self.workspace = self.tmp_path / "ws"
        self.project = self.workspace / "proj"
        self.project.mkdir(parents=True)
        (self.project / "Makefile").write_text("all:\n\ttrue\n", encoding="utf-8")
        self.log_path = self.tmp_path / "stub.log"
        self.env = os.environ.copy()
        self.env["PATH"] = f"{bin_dir}:{self.env['PATH']}"
        self.env["STUB_LOG"] = str(self.log_path)
        self.env["DEVCTL_WORKSPACE_ROOT"] = str(self.workspace)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _log_lines(self) -> list[str]:
        if not self.log_path.exists():
            return []
        return self.log_path.read_text(encoding="utf-8").splitlines()

    def _make(self, *args: str, cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(WRAPPER), "make", *args],
            env=env or self.env,
            cwd=cwd or self.project,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def _plan_file(self, name: str, content: str) -> str:
        path = self.tmp_path / name
        path.write_text(content, encoding="utf-8")
        return str(path)

    def test_no_makefile_is_an_error(self) -> None:
        empty = self.workspace / "empty"
        empty.mkdir()
        result = self._make("all", cwd=empty)
        self.assertEqual(2, result.returncode)
        self.assertIn("No Makefile", result.stderr)
        self.assertFalse(any(" run " in line for line in self._log_lines()))

    def test_outside_workspace_is_an_error(self) -> None:
        outside = self.tmp_path / "outside"
        outside.mkdir()
        (outside / "Makefile").write_text("all:\n\ttrue\n", encoding="utf-8")
        result = self._make("all", cwd=outside)
        self.assertEqual(2, result.returncode)
        self.assertIn("workspace", result.stderr)

    def test_executes_emitted_lines_in_order_and_filters_diagnostics(self) -> None:
        plan = self._plan_file(
            "plan.txt",
            "echo one >> marker.txt\nmake: Nothing to be done for 'all'.\nmake[1]: Entering directory '/x'\necho two >> marker.txt\n",
        )
        result = self._make("all", env=dict(self.env, STUB_MAKE_N_OUT=plan))
        self.assertEqual(0, result.returncode, result.stderr)
        marker = self.project / "marker.txt"
        self.assertEqual("one\ntwo\n", marker.read_text(encoding="utf-8"))

    def test_recursive_make_line_is_not_replayed(self) -> None:
        plan = self._plan_file(
            "plan.txt",
            'make "legacy:codes" OPTS=""\necho leaf >> marker.txt\n',
        )
        result = self._make("legacy", env=dict(self.env, STUB_MAKE_N_OUT=plan))
        self.assertEqual(0, result.returncode, result.stderr)
        marker = self.project / "marker.txt"
        self.assertEqual("leaf\n", marker.read_text(encoding="utf-8"))

    def test_recipes_run_in_the_project_compose_context(self) -> None:
        env_out = self._plan_file("env.txt", "export COMPOSE_PROJECT_NAME='devctl_proj_dev'\n")
        plan = self._plan_file("plan.txt", 'printf "%s" "${COMPOSE_PROJECT_NAME:-unset}" > marker.txt\n')
        result = self._make("all", env=dict(self.env, STUB_MAKE_N_OUT=plan, STUB_ENV_OUT=env_out))
        self.assertEqual(0, result.returncode, result.stderr)
        marker = self.project / "marker.txt"
        self.assertEqual("devctl_proj_dev", marker.read_text(encoding="utf-8"))

    def test_project_without_profile_still_runs_recipes(self) -> None:
        plan = self._plan_file("plan.txt", 'printf "%s" "${COMPOSE_PROJECT_NAME:-unset}" > marker.txt\n')
        result = self._make("all", env=dict(self.env, STUB_MAKE_N_OUT=plan, STUB_ENV_RC="3"))
        self.assertEqual(0, result.returncode, result.stderr)
        marker = self.project / "marker.txt"
        self.assertEqual("unset", marker.read_text(encoding="utf-8"))

    def test_stops_at_first_failure_with_its_exit_code(self) -> None:
        plan = self._plan_file(
            "plan.txt",
            "echo one >> marker.txt\nexit 7\necho three >> marker.txt\n",
        )
        result = self._make("all", env=dict(self.env, STUB_MAKE_N_OUT=plan))
        self.assertEqual(7, result.returncode)
        marker = self.project / "marker.txt"
        self.assertEqual("one\n", marker.read_text(encoding="utf-8"))

    def test_diagnostics_only_output_reports_nothing_to_do(self) -> None:
        plan = self._plan_file("plan.txt", "make: 'all' is up to date.\n")
        result = self._make("all", env=dict(self.env, STUB_MAKE_N_OUT=plan))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("Nothing to do.", result.stdout)

    def test_phase_one_failure_propagates(self) -> None:
        result = self._make("nope", env=dict(self.env, STUB_MAKE_RC="2"))
        self.assertEqual(2, result.returncode)

    def test_extra_args_reach_make(self) -> None:
        plan = self._plan_file("plan.txt", "")
        self._make("test", "V=1", env=dict(self.env, STUB_MAKE_N_OUT=plan))
        run_lines = [line for line in self._log_lines() if "--entrypoint make" in line]
        self.assertEqual(1, len(run_lines))
        self.assertIn("devctl -n test V=1", run_lines[0])

    def test_backslash_continued_recipe_runs_as_one_command(self) -> None:
        plan = self._plan_file(
            "plan.txt",
            "printf 'one\\n' >> marker.txt && \\\n  printf 'two\\n' >> marker.txt\n",
        )
        result = self._make("all", env=dict(self.env, STUB_MAKE_N_OUT=plan))
        self.assertEqual(0, result.returncode, result.stderr)
        marker = self.project / "marker.txt"
        self.assertEqual("one\ntwo\n", marker.read_text(encoding="utf-8"))

    def test_no_target_excludes_prerequisite_only_files(self) -> None:
        qp = self._plan_file(
            "qp.txt",
            "# GNU Make 4.4\nbuild: \n# Not a target:\nmain.c:\n.PHONY: build\n",
        )
        result = self._make(env=dict(self.env, STUB_MAKE_QP_OUT=qp))
        self.assertEqual(0, result.returncode, result.stderr)
        names = result.stdout.split()
        self.assertIn("build", names)
        self.assertNotIn("main.c", names)

    def test_no_target_listing_propagates_real_errors(self) -> None:
        result = self._make(env=dict(self.env, STUB_MAKE_RC="2"))
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("", result.stdout)

    def test_no_target_lists_targets(self) -> None:
        qp = self._plan_file(
            "qp.txt",
            "# GNU Make 4.4\nbuild: \ntest: build\n.PHONY: build test\nMakefile: \nSHELL := /bin/sh\n",
        )
        result = self._make(env=dict(self.env, STUB_MAKE_QP_OUT=qp))
        self.assertEqual(0, result.returncode, result.stderr)
        names = result.stdout.split()
        self.assertIn("build", names)
        self.assertIn("test", names)
        self.assertNotIn(".PHONY", names)
        self.assertNotIn("Makefile", names)
        self.assertNotIn("SHELL", names)
        run_lines = [line for line in self._log_lines() if "--entrypoint make" in line]
        self.assertEqual(1, len(run_lines))
        self.assertIn("devctl -qp", run_lines[0])
