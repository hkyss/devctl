import os
from dataclasses import dataclass
from pathlib import Path

from .errors import DevctlError

DEFAULT_HOST = "127.0.0.1"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as error:
        raise DevctlError(f"{name} must be an integer, got '{raw}'", 2) from error


@dataclass(frozen=True)
class Settings:
    repo_root: Path
    workspace_root: Path
    state_dir: Path
    log_dir: Path
    registry_path: Path
    caddyfile_path: Path
    lock_path: Path
    dns_suffix: str
    url_scheme: str
    port_start: int
    port_end: int
    upstream_host: str
    publish_host: str


def load_settings() -> Settings:
    repo_root = Path(os.environ.get("DEVCTL_REPO_ROOT", Path(__file__).resolve().parents[2]))
    workspace_root = Path(os.environ.get("DEVCTL_WORKSPACE_ROOT", repo_root.parent))
    state_dir = Path(os.environ.get("DEVCTL_STATE_DIR", Path.home() / ".local" / "state" / "devctl"))

    port_start = _env_int("DEVCTL_PORT_START", 49152)
    port_end = _env_int("DEVCTL_PORT_END", 60999)
    for label, value in (("DEVCTL_PORT_START", port_start), ("DEVCTL_PORT_END", port_end)):
        if not (1 <= value <= 65535):
            raise DevctlError(f"{label} must be between 1 and 65535, got {value}", 2)
    if port_start > port_end:
        raise DevctlError(f"DEVCTL_PORT_START ({port_start}) must not exceed DEVCTL_PORT_END ({port_end})", 2)

    return Settings(
        repo_root=repo_root,
        workspace_root=workspace_root,
        state_dir=state_dir,
        log_dir=state_dir / "logs",
        registry_path=state_dir / "registry.sqlite",
        caddyfile_path=state_dir / "Caddyfile",
        lock_path=state_dir / "devctl.lock",
        dns_suffix=os.environ.get("DEVCTL_DNS_SUFFIX", "localhost"),
        url_scheme=os.environ.get("DEVCTL_URL_SCHEME", "http"),
        port_start=port_start,
        port_end=port_end,
        upstream_host=os.environ.get("DEVCTL_UPSTREAM_HOST", DEFAULT_HOST),
        publish_host=os.environ.get("DEVCTL_PUBLISH_HOST", DEFAULT_HOST),
    )
