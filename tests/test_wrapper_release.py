import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parent.parent
WRAPPER = REPO_ROOT / "devctl"

STUB_GIT = """#!/bin/sh
printf '%s\\n' "git $*" >> "${STUB_LOG}"
case "$1" in
  status)
    if [ -n "${STUB_GIT_DIRTY:-}" ]; then
      echo " M tracked-file"
    fi
    if [ -n "${STUB_GIT_UNTRACKED:-}" ]; then
      echo "?? untracked-file"
    fi
    ;;
  tag)
    case "$*" in
      *"-l "*)
        if [ -n "${STUB_GIT_TAGS:-}" ]; then
          printf '%s\\n' "${STUB_GIT_TAGS}"
        fi
        ;;
    esac
    ;;
  rev-parse)
    case "$*" in
      *"refs/tags/"*) exit "${STUB_GIT_TAG_RC:-1}" ;;
      *"--git-dir"*) exit "${STUB_GIT_NOT_REPO_RC:-0}" ;;
      *"-q --verify @{u}"*) exit "${STUB_GIT_NO_UPSTREAM_RC:-0}" ;;
      *"@{u}"*) echo "${STUB_GIT_UPSTREAM:-abc123}" ;;
      *"HEAD"*) echo "abc123" ;;
    esac
    ;;
esac
exit 0
"""

STUB_DOCKER = """#!/bin/sh
printf '%s\\n' "docker $*" >> "${STUB_LOG}"
exit 0
"""


class WrapperReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        bin_dir = self.tmp_path / "bin"
        bin_dir.mkdir()
        for name, body in (("git", STUB_GIT), ("docker", STUB_DOCKER)):
            stub = bin_dir / name
            stub.write_text(body, encoding="utf-8")
            stub.chmod(0o755)
        self.project = self.tmp_path / "proj"
        self.project.mkdir()
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

    def _release(self, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(WRAPPER), "release", *args],
            env=env or self.env,
            cwd=self.project,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_missing_version_usage_error(self) -> None:
        result = self._release()
        self.assertEqual(2, result.returncode)
        self.assertIn("Usage: devctl release X.Y.Z", result.stderr)

    def test_bump_patch_uses_latest_tag(self) -> None:
        result = self._release("patch", env=dict(self.env, STUB_GIT_TAGS="v1.2.3"))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("git tag -a v1.2.4 -m v1.2.4", self._log_lines())
        self.assertIn("git push origin v1.2.4", self._log_lines())
        self.assertIn("Pushed v1.2.4", result.stdout)

    def test_bump_minor_resets_patch(self) -> None:
        result = self._release("minor", env=dict(self.env, STUB_GIT_TAGS="v1.2.3"))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("git tag -a v1.3.0 -m v1.3.0", self._log_lines())

    def test_bump_major_resets_minor_and_patch(self) -> None:
        result = self._release("major", env=dict(self.env, STUB_GIT_TAGS="v1.2.3"))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("git tag -a v2.0.0 -m v2.0.0", self._log_lines())

    def test_bump_with_no_existing_tags_starts_at_zero(self) -> None:
        result = self._release("patch")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("git tag -a v0.0.1 -m v0.0.1", self._log_lines())

    def test_bump_sorts_versions_numerically(self) -> None:
        result = self._release("patch", env=dict(self.env, STUB_GIT_TAGS="v1.9.0\nv1.10.0"))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("git tag -a v1.10.1 -m v1.10.1", self._log_lines())

    def test_bump_rejected_on_dirty_tree(self) -> None:
        result = self._release("patch", env=dict(self.env, STUB_GIT_DIRTY="1"))
        self.assertEqual(2, result.returncode)
        self.assertIn("dirty", result.stderr)
        self.assertFalse(any(" tag " in line for line in self._log_lines()))

    def test_bad_version_rejected(self) -> None:
        result = self._release("1.2")
        self.assertEqual(2, result.returncode)
        self.assertIn("Version must be X.Y.Z", result.stderr)
        self.assertFalse(any(" tag " in line for line in self._log_lines()))

    def test_dirty_tree_rejected(self) -> None:
        result = self._release("1.2.3", env=dict(self.env, STUB_GIT_DIRTY="1"))
        self.assertEqual(2, result.returncode)
        self.assertIn("dirty", result.stderr)
        self.assertFalse(any(" tag " in line for line in self._log_lines()))

    def test_untracked_file_rejected(self) -> None:
        result = self._release("1.2.3", env=dict(self.env, STUB_GIT_UNTRACKED="1"))
        self.assertEqual(2, result.returncode)
        self.assertIn("dirty", result.stderr)
        self.assertFalse(any(" tag " in line for line in self._log_lines()))

    def test_not_a_git_repository_rejected(self) -> None:
        result = self._release("1.2.3", env=dict(self.env, STUB_GIT_NOT_REPO_RC="1"))
        self.assertEqual(2, result.returncode)
        self.assertIn("Not a git repository", result.stderr)
        self.assertFalse(any(" tag " in line for line in self._log_lines()))

    def test_no_upstream_rejected(self) -> None:
        result = self._release("1.2.3", env=dict(self.env, STUB_GIT_NO_UPSTREAM_RC="1"))
        self.assertEqual(2, result.returncode)
        self.assertIn("No upstream tracking branch", result.stderr)
        self.assertFalse(any(" tag " in line for line in self._log_lines()))

    def test_existing_tag_rejected(self) -> None:
        result = self._release("1.2.3", env=dict(self.env, STUB_GIT_TAG_RC="0"))
        self.assertEqual(2, result.returncode)
        self.assertIn("already exists", result.stderr)

    def test_head_differs_from_upstream_rejected(self) -> None:
        result = self._release("1.2.3", env=dict(self.env, STUB_GIT_UPSTREAM="def456"))
        self.assertEqual(2, result.returncode)
        self.assertIn("upstream", result.stderr)

    def test_happy_path_tags_and_pushes_in_order(self) -> None:
        result = self._release("1.2.3")
        self.assertEqual(0, result.returncode, result.stderr)
        lines = self._log_lines()
        fetch = lines.index("git fetch origin --tags")
        tag = lines.index("git tag -a v1.2.3 -m v1.2.3")
        push = lines.index("git push origin v1.2.3")
        self.assertTrue(fetch < tag < push)
        self.assertIn("Pushed v1.2.3", result.stdout)

    def test_leading_v_normalized(self) -> None:
        result = self._release("v1.2.3")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("git tag -a v1.2.3 -m v1.2.3", self._log_lines())

    def test_release_never_touches_docker(self) -> None:
        self._release("1.2.3")
        self.assertFalse(any(line.startswith("docker ") for line in self._log_lines()))
