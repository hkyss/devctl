import os
import subprocess
import sys
import time

from .console import info, step, success, warning
from .errors import DevctlError
from .settings import Settings

_SKIP_BOOT_ENV = "DEVCTL_SKIP_BOOT"
CADDYFILE_CONTAINER_PATH = "/state/Caddyfile"
_RELOAD_ATTEMPTS = 4
_RELOAD_RETRY_SECONDS = 0.5


def compose_file(settings: Settings) -> str:
    return str(settings.repo_root / ".docker" / "docker-compose.yml")


def compose_env(settings: Settings) -> dict[str, str]:
    env = os.environ.copy()
    env["DEVCTL_WORKSPACE_ROOT"] = str(settings.workspace_root)
    return env


def compose_command(settings: Settings, *args: str) -> list[str]:
    return ["docker", "compose", "-f", compose_file(settings), *args]


def is_proxy_running(settings: Settings) -> bool:
    compose_path = settings.repo_root / ".docker" / "docker-compose.yml"
    if not compose_path.is_file():
        return False

    result = subprocess.run(
        compose_command(settings, "ps", "--status", "running", "--services", "caddy", "-q"),
        cwd=settings.repo_root,
        env=compose_env(settings),
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def ensure_runtime(settings: Settings) -> None:
    if os.environ.get(_SKIP_BOOT_ENV) == "1":
        return
    if is_proxy_running(settings):
        return

    compose_path = settings.repo_root / ".docker" / "docker-compose.yml"
    if not compose_path.is_file():
        raise DevctlError(
            f"devctl runtime is not running and compose file was not found: {compose_path}. Run make boot from the devctl repository.",
            6,
        )

    print(step("devctl runtime is not running; booting proxy (make boot)..."))

    _run_compose(settings, "build", "devctl", check=True)

    from .commands import bootstrap

    bootstrap(settings)
    _run_compose(settings, "up", "-d", "caddy", check=True)

    if not is_proxy_running(settings):
        raise DevctlError("failed to start devctl caddy proxy after boot", 6)

    print(success("devctl proxy is ready"))


def reload_proxy(settings: Settings) -> None:
    if not is_proxy_running(settings):
        return

    command = compose_command(settings, "exec", "-T", "caddy", "caddy", "reload", "--config", CADDYFILE_CONTAINER_PATH)
    for attempt in range(_RELOAD_ATTEMPTS):
        result = subprocess.run(
            command,
            cwd=settings.repo_root,
            env=compose_env(settings),
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return
        if attempt + 1 < _RELOAD_ATTEMPTS:
            time.sleep(_RELOAD_RETRY_SECONDS)

    detail = (result.stderr or result.stdout).strip().splitlines()
    print(
        warning(f"could not reload the devctl proxy; routes may be stale: {detail[-1] if detail else 'no output'}"),
        file=sys.stderr,
    )


def _run_compose(settings: Settings, *args: str, check: bool) -> subprocess.CompletedProcess[str]:
    command = compose_command(settings, *args)
    print(f"{info('Running:')} {' '.join(command)}")
    result = subprocess.run(
        command,
        cwd=settings.repo_root,
        env=compose_env(settings),
        text=True,
    )
    if check and result.returncode != 0:
        raise DevctlError(f"command failed ({result.returncode}): {' '.join(command)}", 6)
    return result
