import re
from dataclasses import dataclass
from pathlib import Path

COMPOSE_CANDIDATES = [
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
]

_ENV_REF = r"\$\{(?P<env>[A-Za-z_][A-Za-z0-9_]*)(?::-(?P<default>\d+))?\}"
_SHORT_PORT = re.compile(
    r"^\s*-\s*[\"']?"
    r"(?:\d{1,3}(?:\.\d{1,3}){3}:)?"
    rf"(?:{_ENV_REF}|(?P<host>\d+))"
    r":(?P<container>\d+)"
)
_LONG_PUBLISHED = re.compile(rf"^\s*published:\s*[\"']?(?:{_ENV_REF}|(?P<host>\d+))")


@dataclass(frozen=True)
class PortBinding:
    env: str | None
    default: int | None
    host_port: int | None
    container_port: int | None


def detect_compose_file(root: Path, preferred: str) -> str | None:
    if (root / preferred).exists():
        return preferred
    for candidate in COMPOSE_CANDIDATES:
        if (root / candidate).exists():
            return candidate
    return None


def detect_env_file(root: Path) -> str | None:
    return ".env" if (root / ".env").exists() else None


def scan_published_ports(text: str) -> list[PortBinding]:
    bindings: list[PortBinding] = []
    for line in text.splitlines():
        match = _SHORT_PORT.match(line) or _LONG_PUBLISHED.match(line)
        if not match:
            continue
        groups = match.groupdict()
        container = groups.get("container")
        bindings.append(
            PortBinding(
                env=groups["env"],
                default=int(groups["default"]) if groups["default"] else None,
                host_port=int(groups["host"]) if groups["host"] else None,
                container_port=int(container) if container else None,
            )
        )
    return bindings
