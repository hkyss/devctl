import json
import re
from dataclasses import asdict, dataclass
from json import JSONDecodeError
from pathlib import Path
from typing import Any, Literal

import jsonschema

from .detect import scan_published_ports
from .errors import DevctlError
from .profiles import CONFIG_FILENAME, ProjectProfile, load_profile_file
from .settings import Settings

Severity = Literal["error", "warning"]

KNOWN_PROFILE_KEYS = frozenset(
    {
        "name",
        "adapter",
        "compose_file",
        "compose_files",
        "http_port_env",
        "publish",
        "compose_override",
        "path",
        "env_file",
        "extra_port_envs",
        "preferred_ports",
        "host_prefixed_port_envs",
        "publish_envs",
        "env",
        "pre_up_commands",
        "build",
        "health_timeout_seconds",
        "health_check_path",
        "health_check_statuses",
        "compose_project_name",
        "domain",
        "primary_service",
        "extra_routes",
    }
)

PROJECT_NAME_PATTERN = re.compile(r"^devctl_[a-z0-9_]+$")


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    field: str
    severity: Severity
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def schema_path(settings: Settings) -> Path:
    return settings.repo_root / "schemas" / "devctl.profile.schema.json"


def _schema_issues(settings: Settings, label: str, raw: dict[str, Any]) -> list[ValidationIssue]:
    schema_file = schema_path(settings)
    if not schema_file.is_file():
        return []
    schema = json.loads(schema_file.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    issues: list[ValidationIssue] = []
    for error in sorted(validator.iter_errors(raw), key=lambda err: list(err.path)):
        if error.validator == "additionalProperties":
            continue
        field = ".".join(str(part) for part in error.path) or "$"
        issues.append(ValidationIssue(label, field, "error", error.message))
    return issues


def discover_config_paths(settings: Settings) -> list[Path]:
    return sorted(settings.workspace_root.glob(f"*/{CONFIG_FILENAME}"))


def validate_config_file(settings: Settings, config_path: Path, *, strict: bool) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    label = str(config_path)

    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except JSONDecodeError as error:
        issues.append(ValidationIssue(label, "$", "error", f"invalid JSON: {error.msg}"))
        return issues

    if not isinstance(raw, dict):
        issues.append(ValidationIssue(label, "$", "error", "profile must be a JSON object"))
        return issues

    issues.extend(_unknown_field_issues(label, raw))
    schema_issues = _schema_issues(settings, label, raw)
    issues.extend(schema_issues)
    try:
        profile = load_profile_file(config_path)
    except DevctlError as error:
        issues.append(ValidationIssue(label, "$", "error", str(error)))
        return issues

    issues.extend(_convention_issues(settings, label, profile, config_path))
    if strict:
        issues = [
            ValidationIssue(issue.path, issue.field, "error", issue.message) if issue.severity == "warning" else issue for issue in issues
        ]
    return issues


def resolve_validation_paths(
    settings: Settings,
    *,
    project: str | None,
    workspace: bool,
    files: list[str] | None,
) -> list[Path]:
    if files:
        paths: list[Path] = []
        for item in files:
            path = Path(item).expanduser()
            if not path.is_absolute():
                path = Path.cwd() / path
            path = path.resolve()
            if not path.is_file():
                raise DevctlError(f"profile not found: {path}", 3)
            paths.append(path)
        return paths

    if workspace:
        paths = discover_config_paths(settings)
        if not paths:
            raise DevctlError(f"no profiles found under {settings.workspace_root}", 3)
        return paths

    if project:
        return [_config_path_for_project(settings, project)]

    from .profiles import current_git_root, nearest_project_config

    config = nearest_project_config()
    if config:
        return [config]

    git_root = current_git_root()
    if git_root:
        candidate = git_root / CONFIG_FILENAME
        if candidate.is_file():
            return [candidate]

    raise DevctlError(
        "cannot detect profile. Run from a project with .devctl.json, pass a project name, or use --workspace.",
        3,
    )


def _config_path_for_project(settings: Settings, project: str) -> Path:
    by_directory = settings.workspace_root / project / CONFIG_FILENAME
    if by_directory.is_file():
        return by_directory

    for path in discover_config_paths(settings):
        if load_profile_file(path).name == project:
            return path

    raise DevctlError(f"unknown project '{project}'", 3)


def _unknown_field_issues(label: str, raw: dict[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for key in raw:
        if key not in KNOWN_PROFILE_KEYS:
            issues.append(
                ValidationIssue(
                    label,
                    key,
                    "warning",
                    f"unknown field '{key}'; see docs/devctl-profile-standard.md",
                )
            )
    return issues


def _convention_issues(
    settings: Settings,
    label: str,
    profile: ProjectProfile,
    config_path: Path,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    managed_port_count = 1 + len(profile.extra_port_envs)
    if profile.preferred_ports and len(profile.preferred_ports) != managed_port_count:
        actual = len(profile.preferred_ports)
        issues.append(
            ValidationIssue(
                label,
                "preferred_ports",
                "warning",
                f"expected {managed_port_count} preferred port(s) for managed env vars, got {actual}",
            )
        )

    project_name = profile.env.get("PROJECT_NAME")
    if project_name is None:
        issues.append(
            ValidationIssue(
                label,
                "env.PROJECT_NAME",
                "warning",
                "set env.PROJECT_NAME to a devctl-prefixed Compose project name",
            )
        )
    elif not PROJECT_NAME_PATTERN.fullmatch(project_name):
        issues.append(
            ValidationIssue(
                label,
                "env.PROJECT_NAME",
                "warning",
                "use a devctl_ prefix and lowercase letters, digits, or underscores (example: devctl_example_api)",
            )
        )

    for index, compose_file in enumerate(profile.compose_files):
        compose_path = profile.path / compose_file
        if not compose_path.is_file():
            issues.append(
                ValidationIssue(
                    label,
                    f"compose_files[{index}]",
                    "warning",
                    f"compose file not found: {compose_path}",
                )
            )

    if profile.publish:
        for compose_file in profile.compose_files:
            compose_path = profile.path / compose_file
            if not compose_path.is_file():
                continue
            for binding in scan_published_ports(compose_path.read_text(encoding="utf-8")):
                if binding.container_port == profile.publish.container_port:
                    issues.append(
                        ValidationIssue(
                            label,
                            "publish",
                            "warning",
                            f"{compose_file} already publishes container port {profile.publish.container_port}; "
                            "devctl will publish it a second time",
                        )
                    )
                    break

    if profile.env_file:
        env_path = profile.path / profile.env_file
        if not env_path.is_file():
            issues.append(
                ValidationIssue(
                    label,
                    "env_file",
                    "warning",
                    f"env file not found: {env_path}",
                )
            )

    expected_domain = f"{profile.name}.{settings.dns_suffix}"
    if profile.domain and profile.domain != expected_domain and "${USER}" not in profile.domain:
        issues.append(
            ValidationIssue(
                label,
                "domain",
                "warning",
                f"custom domain '{profile.domain}' overrides the standard '{expected_domain}'",
            )
        )

    if config_path.parent.resolve() != profile.path.resolve():
        issues.append(
            ValidationIssue(
                label,
                "path",
                "warning",
                f"profile path '{profile.path}' differs from the repository root '{config_path.parent}'",
            )
        )

    return issues
