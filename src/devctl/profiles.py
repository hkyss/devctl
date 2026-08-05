import json
import os
import re
import subprocess
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from .errors import DevctlError
from .settings import Settings

CONFIG_FILENAME = ".devctl.json"

PROFILE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
ROUTE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")


@dataclass(frozen=True)
class ExtraRoute:
    name: str
    port_env: str


@dataclass(frozen=True)
class PublishTarget:
    service: str
    container_port: int


@dataclass(frozen=True)
class ProjectProfile:
    name: str
    path: Path
    adapter: str
    compose_files: list[str]
    env_file: str | None
    http_port_env: str | None
    publish: PublishTarget | None
    compose_override: dict[str, Any]
    extra_port_envs: list[str]
    preferred_ports: list[int]
    host_prefixed_port_envs: set[str]
    publish_envs: dict[str, dict[str, Any]]
    env: dict[str, str]
    pre_up_commands: list[list[str]]
    build: bool
    health_timeout_seconds: int
    health_check_path: str | None
    health_check_statuses: list[int]
    compose_project_name: str | None
    domain: str | None
    extra_routes: list[ExtraRoute]
    primary_service: str | None


def expand_path(value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(value)))


def load_profile_file(path: Path) -> ProjectProfile:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except JSONDecodeError as error:
        raise DevctlError(f"invalid profile JSON in {path}: {error.msg}", 3) from error
    if not isinstance(raw, dict):
        raise DevctlError(f"invalid profile {path}: expected a JSON object", 3)

    raw = _validate_profile(path, raw)
    project_path = expand_path(raw["path"]) if "path" in raw else path.parent
    return ProjectProfile(
        name=raw["name"],
        path=project_path.resolve(),
        adapter=raw["adapter"],
        compose_files=list(raw["compose_files"]) if "compose_files" in raw else [raw["compose_file"]],
        env_file=raw.get("env_file"),
        http_port_env=raw.get("http_port_env"),
        publish=(
            PublishTarget(service=raw["publish"]["service"], container_port=int(raw["publish"]["container_port"]))
            if "publish" in raw
            else None
        ),
        compose_override=dict(raw.get("compose_override", {})),
        extra_port_envs=list(raw.get("extra_port_envs", [])),
        preferred_ports=[int(port) for port in raw.get("preferred_ports", [])],
        host_prefixed_port_envs=set(raw.get("host_prefixed_port_envs", [])),
        publish_envs=dict(raw.get("publish_envs", {})),
        env={key: str(value) for key, value in raw.get("env", {}).items()},
        pre_up_commands=[list(command) for command in raw.get("pre_up_commands", [])],
        build=bool(raw.get("build", False)),
        health_timeout_seconds=int(raw.get("health_timeout_seconds", 90)),
        health_check_path=raw.get("health_check_path"),
        health_check_statuses=[int(status) for status in raw.get("health_check_statuses", [200])],
        compose_project_name=raw.get("compose_project_name"),
        domain=raw.get("domain"),
        extra_routes=[ExtraRoute(name=item["name"], port_env=item["port_env"]) for item in raw.get("extra_routes", [])],
        primary_service=raw.get("primary_service"),
    )


def port_slot_keys(profile: ProjectProfile) -> list[str]:
    return [profile.http_port_env or "@http", *profile.extra_port_envs]


def load_profiles(settings: Settings) -> dict[str, ProjectProfile]:
    profiles = {}
    for path in sorted(settings.workspace_root.glob(f"*/{CONFIG_FILENAME}")):
        profile = load_profile_file(path)
        if profile.name in profiles:
            raise DevctlError(f"duplicate project profile name '{profile.name}' in {path}", 3)
        profiles[profile.name] = profile
    return profiles


def current_git_root() -> Path | None:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=Path.cwd(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip()).resolve()


def nearest_project_config(start: Path | None = None) -> Path | None:
    cwd = (start or Path.cwd()).resolve()
    for path in [cwd, *cwd.parents]:
        config_path = path / CONFIG_FILENAME
        if config_path.exists():
            return config_path
    return None


def resolve_profile(settings: Settings, name: str | None) -> ProjectProfile:
    if name:
        profile = find_profile(settings, name)
        if profile:
            return profile
        raise DevctlError(f"unknown project '{name}'. Expected a profile named '{name}' under {settings.workspace_root}", 3)

    git_root = current_git_root()
    if git_root:
        project_config = git_root / CONFIG_FILENAME
        if project_config.exists():
            return load_profile_file(project_config)

    project_config = nearest_project_config()
    if project_config:
        return load_profile_file(project_config)

    raise DevctlError("cannot detect project config. Run devctl init or pass a project name.", 3)


def find_profile(settings: Settings, name: str) -> ProjectProfile | None:
    return load_profiles(settings).get(name)


def _validate_profile(path: Path, raw: dict[str, Any]) -> dict[str, Any]:
    for field in ("name", "adapter"):
        _require_string(path, raw, field)
    if not PROFILE_NAME_PATTERN.fullmatch(raw["name"]):
        raise DevctlError(
            f"invalid profile {path}: field 'name' must match ^[a-z][a-z0-9-]*$ (lowercase letters, digits, hyphens)",
            3,
        )

    if ("compose_file" in raw) == ("compose_files" in raw):
        raise DevctlError(f"invalid profile {path}: exactly one of 'compose_file' or 'compose_files' is required", 3)
    if "compose_file" in raw:
        _require_string(path, raw, "compose_file")
    else:
        _require_string_list(path, raw, "compose_files")
        if len(set(raw["compose_files"])) != len(raw["compose_files"]):
            raise DevctlError(f"invalid profile {path}: field 'compose_files' contains duplicate entries", 3)

    if ("http_port_env" in raw) == ("publish" in raw):
        raise DevctlError(f"invalid profile {path}: exactly one of 'http_port_env' or 'publish' is required", 3)
    if "http_port_env" in raw:
        _require_string(path, raw, "http_port_env")
    else:
        _validate_publish(path, raw)

    if raw["adapter"] != "docker-compose":
        raise DevctlError(f"invalid profile {path}: adapter must be 'docker-compose'", 3)

    for field in ("path", "env_file", "health_check_path", "compose_project_name", "domain"):
        _optional_string(path, raw, field)

    _validate_compose_override(path, raw)

    _optional_string_list(path, raw, "extra_port_envs")
    _optional_string_list(path, raw, "host_prefixed_port_envs")
    _optional_int_list(path, raw, "preferred_ports", min_value=1, max_value=65535)
    _optional_int_list(path, raw, "health_check_statuses", min_value=100, max_value=599)
    _optional_string_map(path, raw, "env")
    _optional_pre_up_commands(path, raw)
    _optional_publish_envs(path, raw)
    _optional_bool(path, raw, "build")
    _optional_positive_int(path, raw, "health_timeout_seconds")

    managed_ports = [*([raw["http_port_env"]] if "http_port_env" in raw else []), *raw.get("extra_port_envs", [])]
    if len(set(managed_ports)) != len(managed_ports):
        raise DevctlError(f"invalid profile {path}: duplicate managed port env names", 3)

    host_prefixed = set(raw.get("host_prefixed_port_envs", []))
    unknown_host_prefixed = host_prefixed - set(managed_ports)
    if unknown_host_prefixed:
        names = ", ".join(sorted(unknown_host_prefixed))
        raise DevctlError(f"invalid profile {path}: host_prefixed_port_envs references unmanaged port env(s): {names}", 3)

    for key, spec in raw.get("publish_envs", {}).items():
        source = spec["source"]
        if source not in managed_ports:
            raise DevctlError(f"invalid profile {path}: publish_envs.{key}.source references unmanaged port env '{source}'", 3)
        if source in host_prefixed:
            raise DevctlError(
                f"invalid profile {path}: publish_envs.{key}.source '{source}' cannot also be in host_prefixed_port_envs",
                3,
            )

    _validate_extra_routes(path, raw)

    return raw


def _validate_extra_routes(path: Path, raw: dict[str, Any]) -> None:
    if "extra_routes" not in raw:
        return
    routes = raw["extra_routes"]
    if not isinstance(routes, list):
        raise DevctlError(f"invalid profile {path}: field 'extra_routes' must be a list of objects", 3)

    extra_port_envs = set(raw.get("extra_port_envs", []))
    seen_names: set[str] = set()
    seen_port_envs: set[str] = set()
    for index, item in enumerate(routes):
        if not isinstance(item, dict):
            raise DevctlError(f"invalid profile {path}: field 'extra_routes[{index}]' must be an object", 3)
        name = item.get("name")
        port_env = item.get("port_env")
        if not isinstance(name, str) or not name.strip():
            raise DevctlError(f"invalid profile {path}: field 'extra_routes[{index}].name' must be a non-empty string", 3)
        if not ROUTE_NAME_PATTERN.fullmatch(name):
            raise DevctlError(
                f"invalid profile {path}: field 'extra_routes[{index}].name' must match ^[a-z][a-z0-9-]*$",
                3,
            )
        if not isinstance(port_env, str) or not port_env.strip():
            raise DevctlError(f"invalid profile {path}: field 'extra_routes[{index}].port_env' must be a non-empty string", 3)
        if port_env not in extra_port_envs:
            raise DevctlError(
                f"invalid profile {path}: field 'extra_routes[{index}].port_env' must reference an entry in extra_port_envs",
                3,
            )
        if name in seen_names:
            raise DevctlError(f"invalid profile {path}: duplicate extra_routes name '{name}'", 3)
        if port_env in seen_port_envs:
            raise DevctlError(f"invalid profile {path}: duplicate extra_routes port_env '{port_env}'", 3)
        seen_names.add(name)
        seen_port_envs.add(port_env)


def _require_string(path: Path, raw: dict[str, Any], field: str) -> None:
    if field not in raw:
        raise DevctlError(f"invalid profile {path}: missing required field '{field}'", 3)
    if not isinstance(raw[field], str) or not raw[field].strip():
        raise DevctlError(f"invalid profile {path}: field '{field}' must be a non-empty string", 3)


def _optional_string(path: Path, raw: dict[str, Any], field: str) -> None:
    if field in raw and raw[field] is not None and not isinstance(raw[field], str):
        raise DevctlError(f"invalid profile {path}: field '{field}' must be a string", 3)


def _optional_bool(path: Path, raw: dict[str, Any], field: str) -> None:
    if field in raw and not isinstance(raw[field], bool):
        raise DevctlError(f"invalid profile {path}: field '{field}' must be a boolean", 3)


def _optional_positive_int(path: Path, raw: dict[str, Any], field: str) -> None:
    if field not in raw:
        return
    value = _coerce_int(path, field, raw[field])
    if value <= 0:
        raise DevctlError(f"invalid profile {path}: field '{field}' must be greater than 0", 3)


def _require_string_list(path: Path, raw: dict[str, Any], field: str) -> None:
    values = raw[field]
    if not isinstance(values, list) or not values:
        raise DevctlError(f"invalid profile {path}: field '{field}' must be a non-empty list of strings", 3)
    for index, value in enumerate(values):
        if not isinstance(value, str) or not value.strip():
            raise DevctlError(f"invalid profile {path}: field '{field}[{index}]' must be a non-empty string", 3)


def _optional_string_list(path: Path, raw: dict[str, Any], field: str) -> None:
    if field not in raw:
        return
    values = raw[field]
    if not isinstance(values, list):
        raise DevctlError(f"invalid profile {path}: field '{field}' must be a list of strings", 3)
    for index, value in enumerate(values):
        if not isinstance(value, str) or not value.strip():
            raise DevctlError(f"invalid profile {path}: field '{field}[{index}]' must be a non-empty string", 3)


def _optional_int_list(path: Path, raw: dict[str, Any], field: str, *, min_value: int, max_value: int) -> None:
    if field not in raw:
        return
    values = raw[field]
    if not isinstance(values, list):
        raise DevctlError(f"invalid profile {path}: field '{field}' must be a list of integers", 3)
    for index, value in enumerate(values):
        item = _coerce_int(path, f"{field}[{index}]", value)
        if item < min_value or item > max_value:
            raise DevctlError(f"invalid profile {path}: field '{field}[{index}]' must be between {min_value} and {max_value}", 3)


def _optional_string_map(path: Path, raw: dict[str, Any], field: str) -> None:
    if field not in raw:
        return
    values = raw[field]
    if not isinstance(values, dict):
        raise DevctlError(f"invalid profile {path}: field '{field}' must be an object", 3)
    for key in values:
        if not isinstance(key, str) or not key.strip():
            raise DevctlError(f"invalid profile {path}: field '{field}' contains an invalid key", 3)


def _optional_pre_up_commands(path: Path, raw: dict[str, Any]) -> None:
    if "pre_up_commands" not in raw:
        return
    commands = raw["pre_up_commands"]
    if not isinstance(commands, list):
        raise DevctlError(f"invalid profile {path}: field 'pre_up_commands' must be a list of command arrays", 3)
    for index, command in enumerate(commands):
        if not isinstance(command, list) or not command:
            raise DevctlError(f"invalid profile {path}: field 'pre_up_commands[{index}]' must be a non-empty command array", 3)
        for part_index, part in enumerate(command):
            if not isinstance(part, str) or not part.strip():
                field = f"pre_up_commands[{index}][{part_index}]"
                raise DevctlError(f"invalid profile {path}: field '{field}' must be a non-empty string", 3)


def _optional_publish_envs(path: Path, raw: dict[str, Any]) -> None:
    if "publish_envs" not in raw:
        return
    publish_envs = raw["publish_envs"]
    if not isinstance(publish_envs, dict):
        raise DevctlError(f"invalid profile {path}: field 'publish_envs' must be an object", 3)

    for key, spec in publish_envs.items():
        if not isinstance(key, str) or not key.strip():
            raise DevctlError(f"invalid profile {path}: field 'publish_envs' contains an invalid key", 3)
        if not isinstance(spec, dict):
            raise DevctlError(f"invalid profile {path}: field 'publish_envs.{key}' must be an object", 3)
        if "source" not in spec:
            raise DevctlError(f"invalid profile {path}: missing required field 'publish_envs.{key}.source'", 3)
        if not isinstance(spec["source"], str) or not spec["source"].strip():
            raise DevctlError(f"invalid profile {path}: field 'publish_envs.{key}.source' must be a non-empty string", 3)
        if "target" not in spec:
            raise DevctlError(f"invalid profile {path}: missing required field 'publish_envs.{key}.target'", 3)
        target = _coerce_int(path, f"publish_envs.{key}.target", spec["target"])
        if target < 1 or target > 65535:
            raise DevctlError(f"invalid profile {path}: field 'publish_envs.{key}.target' must be between 1 and 65535", 3)
        if "host" in spec and not isinstance(spec["host"], str):
            raise DevctlError(f"invalid profile {path}: field 'publish_envs.{key}.host' must be a string", 3)


def _validate_compose_override(path: Path, raw: dict[str, Any]) -> None:
    if "compose_override" not in raw:
        return
    override = raw["compose_override"]
    if not isinstance(override, dict):
        raise DevctlError(f"invalid profile {path}: field 'compose_override' must be an object", 3)
    if "services" not in override:
        return
    services = override["services"]
    if not isinstance(services, dict):
        raise DevctlError(f"invalid profile {path}: field 'compose_override.services' must be an object", 3)
    for name, service in services.items():
        if not isinstance(service, dict):
            raise DevctlError(f"invalid profile {path}: field 'compose_override.services.{name}' must be an object", 3)
        if "ports" in service and not isinstance(service["ports"], list):
            raise DevctlError(f"invalid profile {path}: field 'compose_override.services.{name}.ports' must be a list", 3)


def _validate_publish(path: Path, raw: dict[str, Any]) -> None:
    publish = raw["publish"]
    if not isinstance(publish, dict):
        raise DevctlError(f"invalid profile {path}: field 'publish' must be an object", 3)
    unknown = set(publish) - {"service", "container_port"}
    if unknown:
        names = ", ".join(sorted(unknown))
        raise DevctlError(f"invalid profile {path}: field 'publish' has unknown key(s): {names}", 3)
    if not isinstance(publish.get("service"), str) or not publish["service"].strip():
        raise DevctlError(f"invalid profile {path}: field 'publish.service' must be a non-empty string", 3)
    port = _coerce_int(path, "publish.container_port", publish.get("container_port"))
    if port < 1 or port > 65535:
        raise DevctlError(f"invalid profile {path}: field 'publish.container_port' must be between 1 and 65535", 3)


def _coerce_int(path: Path, field: str, value: Any) -> int:
    if isinstance(value, bool):
        raise DevctlError(f"invalid profile {path}: field '{field}' must be an integer", 3)
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise DevctlError(f"invalid profile {path}: field '{field}' must be an integer", 3) from error
