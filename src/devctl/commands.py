import json
import os
import shlex
import socket
import subprocess
import sys
import webbrowser
from contextlib import redirect_stdout
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from .adapters import DockerComposeAdapter, adapter_for, compose_context_env, compose_project_name, published_ports
from .console import error as red
from .console import info, step, success, warning
from .detect import detect_compose_file, detect_env_file, scan_published_ports
from .errors import DevctlError
from .lock import state_lock
from .net import port_accepts_connections, wait_for_http, wait_for_port
from .override import remove_override
from .ports import allocate_ports
from .profiles import CONFIG_FILENAME, ProjectProfile, current_git_root, find_profile, port_slot_keys, resolve_profile
from .proxy import CaddyfileWriter
from .recipes import RECIPES, load_recipe, recipe_names
from .registry import ExtraRouteEntry, Registry, Service, StopTarget
from .routing import domain_for, url_for
from .runtime import ensure_runtime
from .settings import Settings
from .standard import ValidationIssue, resolve_validation_paths, schema_path, validate_config_file
from .timeutil import now_iso


def bootstrap(settings: Settings) -> None:
    with state_lock(settings):
        registry = Registry(settings)
        registry.ensure()
        CaddyfileWriter(settings, registry).write()
    print(f"State: {settings.state_dir}")
    print(f"Registry: {settings.registry_path}")
    print(f"Logs: {settings.log_dir}")
    print(f"Caddyfile: {settings.caddyfile_path}")
    print("Next:")
    print("  make doctor")
    print("  make up p=<project>")


def get_version() -> str:
    env_version = os.environ.get("DEVCTL_VERSION")
    if env_version:
        return env_version
    try:
        from importlib.metadata import version

        return version("devctl")
    except Exception:
        return "0.0.0-dev"


def print_version() -> None:
    print(get_version())


RESOURCE_LIMITS_OVERRIDE_FILENAME = "docker-compose.override.devctl-suggested.yml"


def doctor(
    settings: Settings,
    as_json: bool = False,
    fix: bool = False,
    dry_run: bool = False,
    workspace: bool = False,
) -> None:
    registry = Registry(settings)
    registry.ensure()
    git_root = current_git_root()
    current_config = bool(git_root and (git_root / CONFIG_FILENAME).exists())
    checks = [
        ("state directory", settings.state_dir.exists()),
        ("registry", settings.registry_path.exists()),
        ("docker", _command_ok(["docker", "version"])),
        ("docker compose", _command_ok(["docker", "compose", "version"])),
        ("workspace root", settings.workspace_root.exists()),
        ("devctl repository", (settings.workspace_root / "devctl").exists()),
        ("proxy port 80", _can_bind_proxy_port(settings)),
        ("free managed port", _has_free_port(settings, registry)),
        ("project config", current_config),
    ]
    if as_json:
        payload: dict[str, object] = {name: ok for name, ok in checks}
        if workspace:
            payload["cross_project_port_conflicts"] = _detect_cross_project_port_conflicts(settings)
        print(json.dumps(payload, indent=2))
    else:
        for name, ok in checks:
            state = success("ok") if ok else red("missing")
            print(f"{name}: {state}")
        _warn_upstream_publish_mismatch(settings)
        _warn_orphan_volumes()
        detected = _warn_missing_resource_limits(settings, git_root)
        if fix:
            if detected:
                compose_path, unbounded = detected
                _fix_missing_resource_limits(compose_path, unbounded, dry_run)
            else:
                print(info("doctor --fix: no missing resource limits detected, nothing to do"))
        if workspace:
            _warn_cross_project_port_conflicts(settings)
    if not all(ok for _name, ok in checks):
        raise DevctlError("doctor found failed checks", 1)


def _detect_profile_ports(project_root: Path, compose_file: str, http_port_env: str) -> tuple[str, list[str], list[int]]:
    compose_path = project_root / compose_file
    if not compose_path.exists():
        return http_port_env, [], []
    bindings = scan_published_ports(compose_path.read_text(encoding="utf-8"))

    env_names: list[str] = []
    for binding in bindings:
        if binding.env and binding.env not in env_names:
            env_names.append(binding.env)
    if http_port_env not in env_names and env_names and http_port_env == "PORT_HTTP":
        http_port_env = env_names[0]
    extra_port_envs = [name for name in env_names if name != http_port_env]

    preferred_ports: list[int] = []
    for binding in bindings:
        value = binding.default if binding.env else binding.host_port
        if value and value not in preferred_ports:
            preferred_ports.append(value)

    for binding in bindings:
        if binding.env is None and binding.host_port:
            container = binding.container_port or binding.host_port
            print(
                warning(
                    f"published port {binding.host_port}:{container} in {compose_file} is not configurable "
                    f'via an env var; devctl needs e.g. "${{{http_port_env}:-{binding.host_port}}}:{container}"'
                ),
                file=sys.stderr,
            )
    return http_port_env, extra_port_envs, preferred_ports


def recipes_list(settings: Settings, as_json: bool) -> None:
    names = recipe_names()
    if as_json:
        payload = [{"name": name, "description": RECIPES[name]} for name in names]
        print(json.dumps(payload, indent=2))
        return
    for name in names:
        print(f"{name:<14} {RECIPES[name]}")


def recipes_show(settings: Settings, name: str, as_json: bool) -> None:
    profile = load_recipe(settings, name)
    print(json.dumps(profile, indent=2))


def init_project(
    settings: Settings,
    name: str | None,
    compose_file: str,
    env_file: str | None,
    http_port_env: str,
    recipe: str | None,
    force: bool,
    dry_run: bool,
) -> None:
    project_root = current_git_root() or Path.cwd().resolve()
    config_path = project_root / CONFIG_FILENAME
    if config_path.exists() and not force and not dry_run:
        raise DevctlError(f"{config_path} already exists. Use --force to overwrite.", 3)

    detected_compose = detect_compose_file(project_root, compose_file)
    if detected_compose:
        compose_file = detected_compose
    env_file = env_file or detect_env_file(project_root)

    project_name = name or project_root.name
    if recipe:
        profile = load_recipe(settings, recipe)
        profile["name"] = project_name
        profile["env"] = {**profile.get("env", {}), "PROJECT_NAME": _compose_project_name(project_name)}
        if compose_file != "docker-compose.yml":
            profile["compose_file"] = compose_file
        if env_file:
            profile["env_file"] = env_file
        if http_port_env != "PORT_HTTP":
            profile = _rename_http_port_env(profile, http_port_env)
    else:
        http_port_env, extra_port_envs, preferred_ports = _detect_profile_ports(project_root, compose_file, http_port_env)
        profile = {
            "name": project_name,
            "adapter": "docker-compose",
            "compose_file": compose_file,
            "http_port_env": http_port_env,
            "extra_port_envs": extra_port_envs,
            "preferred_ports": preferred_ports,
            "host_prefixed_port_envs": [http_port_env],
            "env": {
                "PROJECT_NAME": _compose_project_name(project_name),
            },
            "build": False,
            "health_timeout_seconds": 90,
        }
        if env_file:
            profile["env_file"] = env_file

    content = json.dumps(profile, indent=2) + "\n"
    if dry_run:
        print(content, end="")
        return

    config_path.write_text(content, encoding="utf-8")
    print(success(f"Created {config_path}"))
    print(f"{info('Next:')} devctl validate --strict && devctl up")


@dataclass(frozen=True)
class _UpPlan:
    registry: Registry
    profile: ProjectProfile
    adapter: DockerComposeAdapter
    log_path: Path
    command: str


def _prepare_up(settings: Settings, project: str | None, no_build: bool, build: bool = False) -> _UpPlan:
    ensure_runtime(settings)
    registry = Registry(settings)
    registry.ensure()
    profile = resolve_profile(settings, project)
    if not profile.path.exists():
        raise DevctlError(f"project path does not exist: {profile.path}", 3)
    if build:
        profile = replace(profile, build=True)
    elif no_build:
        profile = replace(profile, build=False)

    print(f"{info('Project:')} {profile.name}")
    print(f"{info('Path:')} {profile.path}")

    adapter = adapter_for(settings, profile)
    log_path = settings.log_dir / f"{profile.name}.log"
    command = " ".join(adapter.command_up())
    return _UpPlan(registry=registry, profile=profile, adapter=adapter, log_path=log_path, command=command)


def _register_up(settings: Settings, plan: _UpPlan) -> tuple[int, list[int]]:
    registry, profile = plan.registry, plan.profile
    print(step("Allocating ports..."))
    slot_keys = port_slot_keys(profile)
    remembered = registry.allocated_ports_for(profile.name)
    sticky = [remembered.get(key) for key in slot_keys]
    reclaimable = published_ports(compose_project_name(profile)) if profile.preferred_ports or remembered else set()
    ports = allocate_ports(
        settings,
        registry,
        len(slot_keys),
        profile.preferred_ports,
        sticky=sticky,
        reclaimable=reclaimable,
        exclude_name=profile.name,
    )
    backend_port, extra_ports = ports[0], ports[1:]
    registry.set_allocated_ports(profile.name, dict(zip(slot_keys, ports, strict=True)))
    registry.upsert_starting(
        name=profile.name,
        domain=domain_for(settings, profile),
        project_path=str(profile.path),
        adapter=profile.adapter,
        command=plan.command,
        host=settings.upstream_host,
        port=backend_port,
        log_path=str(plan.log_path),
        compose_project_name=compose_project_name(profile),
    )
    port_by_env = dict(zip(profile.extra_port_envs, extra_ports, strict=True))
    project_domain = domain_for(settings, profile)
    registry.set_extra_routes(
        profile.name,
        [
            ExtraRouteEntry(
                route_name=route.name,
                domain=f"{route.name}.{project_domain}",
                host=settings.upstream_host,
                port=port_by_env[route.port_env],
            )
            for route in profile.extra_routes
        ],
    )
    CaddyfileWriter(settings, registry).write()
    return backend_port, extra_ports


def _up_payload(settings: Settings, plan: _UpPlan) -> dict[str, object]:
    registry, profile = plan.registry, plan.profile
    service = next(service for service in registry.services() if service.name == profile.name)
    return {
        **service.__dict__,
        "url": url_for(settings, profile),
        "log_path": str(plan.log_path),
        "extra_routes": [route.__dict__ for route in registry.extra_routes_for(profile.name)],
    }


def up(settings: Settings, project: str | None, no_build: bool = False, build: bool = False, as_json: bool = False) -> None:
    if not as_json:
        plan = _prepare_up(settings, project, no_build, build)
        with state_lock(settings):
            backend_port, extra_ports = _register_up(settings, plan)
        _start_and_wait(settings, plan, backend_port, extra_ports)
        return

    stdout = sys.stdout
    with redirect_stdout(sys.stderr):
        plan = _prepare_up(settings, project, no_build, build)
        with state_lock(settings):
            backend_port, extra_ports = _register_up(settings, plan)
        try:
            _start_and_wait(settings, plan, backend_port, extra_ports)
        finally:
            print(json.dumps(_up_payload(settings, plan), indent=2), file=stdout)


def _start_and_wait(settings: Settings, plan: _UpPlan, backend_port: int, extra_ports: list[int]) -> None:
    registry, profile, adapter, log_path = plan.registry, plan.profile, plan.adapter, plan.log_path
    command = plan.command
    with log_path.open("ab") as log:
        for pre_up_command in profile.pre_up_commands:
            printable = " ".join(adapter.command_pre_up(pre_up_command))
            print(f"{step('Running pre-up:')} {printable}")
            log.write(f"\n[{now_iso()}] $ {printable}\n".encode())
        print(f"{step('Starting containers:')} {command}")
        log.write(f"\n[{now_iso()}] $ {command}\n".encode())
        exit_code = adapter.up(backend_port, extra_ports, log)

    if exit_code != 0:
        with state_lock(settings):
            registry.set_status(profile.name, "unhealthy", detail=f"start command failed with exit code {exit_code}")
            CaddyfileWriter(settings, registry).write()
        raise DevctlError(f"start command failed for {profile.name}. See logs: {log_path}", 1)

    if profile.health_check_path:
        print(step(f"Waiting for HTTP health check on {settings.upstream_host}:{backend_port}{profile.health_check_path}..."))
        ok, error = wait_for_http(
            settings.upstream_host,
            backend_port,
            profile.health_check_path,
            profile.health_check_statuses,
            profile.health_timeout_seconds,
            lambda message: print(warning(f"Health check still failing: {message}")),
        )
    else:
        print(step(f"Waiting for TCP health check on {settings.upstream_host}:{backend_port}..."))
        ok, error = wait_for_port(settings.upstream_host, backend_port, profile.health_timeout_seconds)

    status_value = "healthy" if ok else "unhealthy"
    with state_lock(settings):
        registry.set_status(profile.name, status_value, detail=None if ok else error)
        CaddyfileWriter(settings, registry).write()

    colored_status = success(status_value) if ok else red(status_value)
    print(f"{info('URL:')} {url_for(settings, profile)}")
    print(f"{info('Backend:')} {settings.upstream_host}:{backend_port}")
    print(f"{info('Status:')} {colored_status}")
    print(f"{info('Logs:')} {log_path}")
    for route in registry.extra_routes_for(profile.name):
        print(f"{info('Service:')} {route.route_name} -> {settings.url_scheme}://{route.domain} ({route.host}:{route.port})")
    if not ok:
        print(red(f"Health check failed: {error}"), file=sys.stderr)
        raise DevctlError("health check failed", 8)


def stop_from_registry(settings: Settings, target: StopTarget) -> None:
    if target.adapter != "docker-compose":
        return
    env = os.environ.copy()
    if target.compose_project_name:
        env["COMPOSE_PROJECT_NAME"] = target.compose_project_name
    subprocess.run(
        ["docker", "compose", "down", "--remove-orphans"],
        cwd=target.project_path,
        env=env,
    )


def _stop_projects(settings: Settings, registry: Registry, names: list[str]) -> None:
    for name in names:
        target = registry.stop_target(name)
        profile = find_profile(settings, name)
        if profile:
            adapter_for(settings, profile).down()
        elif target:
            stop_from_registry(settings, target)
        registry.delete(name)
        remove_override(settings, name)
        print(success(f"Stopped: {name}"))


def down(settings: Settings, project: str | None, all_projects: bool) -> None:
    with state_lock(settings):
        registry = Registry(settings)
        registry.ensure()
        if all_projects:
            names = registry.names()
        elif project:
            names = [project]
        else:
            names = [resolve_profile(settings, None).name]

        _stop_projects(settings, registry, names)
        CaddyfileWriter(settings, registry).write()


def restart(settings: Settings, project: str | None, no_build: bool = False, build: bool = False) -> None:
    plan = _prepare_up(settings, project, no_build, build)
    with state_lock(settings):
        _stop_projects(settings, plan.registry, [plan.profile.name])
        backend_port, extra_ports = _register_up(settings, plan)
    _start_and_wait(settings, plan, backend_port, extra_ports)


def _in_container() -> bool:
    return Path("/.dockerenv").exists()


def open_project(settings: Settings, project: str | None) -> None:
    registry = Registry(settings)
    registry.ensure()
    name = project or resolve_profile(settings, None).name
    services = [service for service in registry.services() if service.name == name]
    if not services:
        raise DevctlError(f"no registered service named '{name}'. Start it with: devctl up {name}", 1)
    service = services[0]
    url = f"{settings.url_scheme}://{service.domain}"
    if not port_accepts_connections(settings.upstream_host, service.port):
        print(warning(f"{name} looks stale (port {service.port} is not responding); opening anyway"), file=sys.stderr)
    print(url)
    if not _in_container():
        webbrowser.open(url)


def prune(settings: Settings, dry_run: bool = False) -> None:
    with state_lock(settings):
        registry = Registry(settings)
        registry.ensure()
        stale = [
            service
            for service in registry.services()
            if service.status != "starting" and not port_accepts_connections(settings.upstream_host, service.port)
        ]
        if not stale:
            print("No stale services found.")
            return

        for service in stale:
            if dry_run:
                print(f"{info('Would remove:')} {service.name} ({service.domain}, port {service.port})")
            else:
                registry.delete(service.name)
                registry.forget_allocated_ports(service.name)
                print(success(f"Removed stale entry: {service.name} ({service.domain}, port {service.port})"))

        if not dry_run:
            CaddyfileWriter(settings, registry).write()


def profile_print(settings: Settings, project: str | None, as_json: bool) -> None:
    profile = resolve_profile(settings, project)
    payload = {
        **profile.__dict__,
        "path": str(profile.path),
        "publish": asdict(profile.publish) if profile.publish else None,
        "host_prefixed_port_envs": sorted(profile.host_prefixed_port_envs),
        "extra_routes": [route.__dict__ for route in profile.extra_routes],
        "domain": domain_for(settings, profile),
        "url": url_for(settings, profile),
    }
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        for key, value in payload.items():
            print(f"{info(f'{key}:')} {value}")


def env_print(settings: Settings, project: str | None, as_json: bool) -> None:
    profile = resolve_profile(settings, project)
    values = compose_context_env(settings, profile)
    if as_json:
        print(json.dumps(values, indent=2))
        return
    for key in sorted(values):
        print(f"export {key}={shlex.quote(values[key])}")


def _effective_status(settings: Settings, service: Service) -> tuple[str, bool, str | None]:
    live = port_accepts_connections(settings.upstream_host, service.port)
    if not live:
        return "stale", False, f"port {service.port} is not accepting connections"
    return service.status, True, service.status_detail


def _health_check_description(profile: ProjectProfile) -> str:
    if profile.health_check_path:
        statuses = ", ".join(str(code) for code in profile.health_check_statuses)
        return f"HTTP {profile.health_check_path} expecting {statuses} (timeout {profile.health_timeout_seconds}s)"
    return f"TCP port check (timeout {profile.health_timeout_seconds}s)"


def status(settings: Settings, project: str | None, as_json: bool) -> None:
    registry = Registry(settings)
    registry.ensure()
    name = project or resolve_profile(settings, None).name
    services = [service for service in registry.services() if service.name == name]
    if not services:
        raise DevctlError(f"no registered service named '{name}'", 1)
    service = services[0]
    effective, live, reason = _effective_status(settings, service)
    url = f"{settings.url_scheme}://{service.domain}"
    backend = f"{service.host}:{service.port}"
    profile = find_profile(settings, name)
    extra_routes = registry.extra_routes_for(name)
    if as_json:
        payload = {
            **service.__dict__,
            "status": effective,
            "reachable": live,
            "reason": reason,
            "url": url,
            "backend": backend,
            "extra_routes": [route.__dict__ for route in extra_routes],
        }
        if profile:
            payload["compose_project_name"] = compose_project_name(profile)
            payload["health_check"] = {
                "path": profile.health_check_path,
                "statuses": profile.health_check_statuses,
                "timeout_seconds": profile.health_timeout_seconds,
            }
        print(json.dumps(payload, indent=2))
    else:
        print(f"{info('Name:')} {service.name}")
        print(f"{info('URL:')} {url}")
        print(f"{info('Status:')} {_colored_status(effective)}")
        if reason:
            print(f"{info('Reason:')} {reason}")
        print(f"{info('Backend:')} {backend}")
        print(f"{info('Path:')} {service.project_path}")
        if profile:
            print(f"{info('Compose project:')} {compose_project_name(profile)}")
            print(f"{info('Health check:')} {_health_check_description(profile)}")
        print(f"{info('Logs:')} {service.log_path}")
        for route in extra_routes:
            print(f"{info('Route:')} {route.route_name} -> {settings.url_scheme}://{route.domain} ({route.port})")


def list_services(settings: Settings, as_json: bool) -> None:
    registry = Registry(settings)
    registry.ensure()
    services = registry.services()
    if as_json:
        payload = []
        for service in services:
            effective, live, reason = _effective_status(settings, service)
            payload.append(
                {
                    **service.__dict__,
                    "status": effective,
                    "reachable": live,
                    "reason": reason,
                    "url": f"{settings.url_scheme}://{service.domain}",
                    "extra_routes": [route.__dict__ for route in registry.extra_routes_for(service.name)],
                }
            )
        print(json.dumps(payload, indent=2))
        return

    if not services:
        print("No services registered.")
        return

    print(f"{'NAME':<14} {'URL':<36} {'STATUS':<10} {'PORT':<7} PID")
    for service in services:
        effective, _live, reason = _effective_status(settings, service)
        colored_status = _colored_status(effective)
        url = f"{settings.url_scheme}://{service.domain}"
        print(f"{service.name:<14} {url:<36} {colored_status:<19} {service.port:<7} {service.pid or '-'}")
        for route in registry.extra_routes_for(service.name):
            route_label = f"  {route.route_name}@{service.name}"
            route_url = f"{settings.url_scheme}://{route.domain}"
            print(f"{route_label:<14} {route_url:<36} {colored_status:<19} {route.port:<7} -")
        if reason:
            print(f"{'':<14} {warning(reason)}")


def validate(
    settings: Settings,
    project: str | None,
    *,
    workspace: bool,
    files: list[str] | None,
    strict: bool,
    as_json: bool,
) -> None:
    paths = resolve_validation_paths(settings, project=project, workspace=workspace, files=files)
    issues: list[ValidationIssue] = []
    for path in paths:
        issues.extend(validate_config_file(settings, path, strict=strict))

    if as_json:
        errors = [issue for issue in issues if issue.severity == "error"]
        print(
            json.dumps(
                {
                    "ok": not errors,
                    "profiles": [str(path) for path in paths],
                    "schema": str(schema_path(settings)),
                    "issues": [issue.to_dict() for issue in issues],
                },
                indent=2,
            )
        )
    else:
        if not issues:
            print(success(f"Validated {len(paths)} profile(s). Schema: {schema_path(settings)}"))
        else:
            for issue in issues:
                label = red("error") if issue.severity == "error" else warning("warning")
                print(f"{issue.path}: {issue.field}: {label}: {issue.message}")
            print(f"{info('Schema:')} {schema_path(settings)}")

    errors = [issue for issue in issues if issue.severity == "error"]
    if errors:
        raise DevctlError(f"validation failed with {len(errors)} error(s)", 5)


def logs(
    settings: Settings,
    project: str | None,
    follow: bool,
    services: list[str] | None = None,
    since: str | None = None,
    tail: int | None = None,
) -> None:
    profile = resolve_profile(settings, project)
    services = services or []
    if services or since or tail is not None:
        adapter = adapter_for(settings, profile)
        exit_code = adapter.logs(follow=follow, services=services, since=since, tail=tail)
        if exit_code != 0:
            raise DevctlError(f"docker compose logs failed for {profile.name}", exit_code)
        return

    log_path = settings.log_dir / f"{profile.name}.log"
    if not log_path.exists():
        raise DevctlError(f"log file does not exist: {log_path}", 1)
    if follow:
        subprocess.run(["tail", "-f", str(log_path)])
    else:
        print(log_path.read_text(encoding="utf-8", errors="replace"))


def exec_command(settings: Settings, project: str | None, service: str | None, tty: bool, cmd: list[str]) -> int:
    profile = resolve_profile(settings, project)
    target_service = service or profile.primary_service
    if not target_service:
        raise DevctlError(
            f"no --service given and '{profile.name}' has no primary_service configured in .devctl.json",
            2,
        )
    if not cmd:
        raise DevctlError("devctl exec requires a command after '--'", 2)
    adapter = adapter_for(settings, profile)
    return adapter.exec(target_service, cmd, tty)


def stats(settings: Settings, project: str | None, as_json: bool, no_stream: bool) -> None:
    profile = resolve_profile(settings, project)
    adapter = adapter_for(settings, profile)
    container_ids = adapter.container_ids()
    if not container_ids:
        print(warning(f"project '{profile.name}' is not running"))
        return

    command = ["docker", "stats"]
    if no_stream or as_json:
        command.append("--no-stream")
    if as_json:
        command.extend(["--format", "{{json .}}"])
    command.extend(container_ids)

    if as_json:
        result = subprocess.run(command, stdout=subprocess.PIPE, text=True)
        entries = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        print(json.dumps(entries, indent=2))
    else:
        subprocess.run(command)


def _compose_project_name(project_name: str) -> str:
    safe_name = "".join(char if char.isalnum() else "_" for char in project_name.lower()).strip("_")
    return f"devctl_{safe_name or 'project'}"


def _rename_http_port_env(profile: dict[str, object], http_port_env: str) -> dict[str, object]:
    old_http_port_env = profile.get("http_port_env")
    if not isinstance(old_http_port_env, str):
        raise DevctlError("recipe is missing http_port_env", 3)

    profile["http_port_env"] = http_port_env
    for field in ("extra_port_envs", "host_prefixed_port_envs"):
        values = profile.get(field)
        if isinstance(values, list):
            profile[field] = [http_port_env if value == old_http_port_env else value for value in values]

    publish_envs = profile.get("publish_envs")
    if isinstance(publish_envs, dict):
        for spec in publish_envs.values():
            if isinstance(spec, dict) and spec.get("source") == old_http_port_env:
                spec["source"] = http_port_env

    return profile


_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _warn_upstream_publish_mismatch(settings: Settings) -> None:
    if settings.publish_host in _LOOPBACK_HOSTS and settings.upstream_host not in _LOOPBACK_HOSTS:
        print(
            warning(
                f"note: backends publish on loopback ({settings.publish_host}) but the proxy "
                f"connects via '{settings.upstream_host}'. This works on Docker Desktop; on native "
                "Linux set DEVCTL_PUBLISH_HOST to a host address reachable from containers."
            )
        )


def _list_dangling_volumes() -> list[str]:
    result = subprocess.run(
        ["docker", "volume", "ls", "-f", "dangling=true", "--format", "{{.Name}}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [name for name in result.stdout.splitlines() if name.strip()]


def _list_dangling_images() -> list[tuple[str, str]]:
    result = subprocess.run(
        ["docker", "image", "ls", "-f", "dangling=true", "--format", "{{.ID}}\t{{.Repository}}:{{.Tag}}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if result.returncode != 0:
        return []
    images = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 1)
        if len(parts) == 2:
            images.append((parts[0], parts[1]))
    return images


def _system_df_volume_sizes() -> dict[str, str]:
    try:
        result = subprocess.run(
            ["docker", "system", "df", "-v"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError:
        return {}
    if result.returncode != 0:
        return {}
    sizes: dict[str, str] = {}
    in_volumes_section = False
    for line in result.stdout.splitlines():
        if line.strip() == "Local Volumes:":
            in_volumes_section = True
            continue
        if in_volumes_section and line.strip().endswith("SIZE") and "VOLUME NAME" in line:
            continue
        if not in_volumes_section:
            continue
        if not line.strip():
            in_volumes_section = False
            continue
        columns = line.split()
        if len(columns) >= 3:
            sizes[columns[0]] = columns[-1]
    return sizes


def gc(*, dry_run: bool, yes: bool, volumes: bool, images: bool) -> None:
    if not volumes and not images:
        volumes = True

    candidate_volumes = _list_dangling_volumes() if volumes else []
    candidate_images = _list_dangling_images() if images else []

    if not candidate_volumes and not candidate_images:
        print(success("nothing to clean up"))
        return

    sizes = _system_df_volume_sizes() if candidate_volumes else {}

    if candidate_volumes:
        print(info(f"{len(candidate_volumes)} orphan volume(s):"))
        for name in candidate_volumes:
            size = sizes.get(name)
            print(f"  - {name}" + (f" ({size})" if size else ""))
    if candidate_images:
        print(info(f"{len(candidate_images)} dangling image(s):"))
        for image_id, name in candidate_images:
            print(f"  - {image_id}  {name}")

    if dry_run:
        return

    if not yes:
        if not sys.stdin.isatty():
            return
        parts = []
        if candidate_volumes:
            parts.append(f"{len(candidate_volumes)} volume(s)")
        if candidate_images:
            parts.append(f"{len(candidate_images)} image(s)")
        answer = input(f"Remove {' and '.join(parts)}? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            print("aborted, nothing removed")
            return

    failures = []
    for name in candidate_volumes:
        result = subprocess.run(
            ["docker", "volume", "rm", name],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print(success(f"removed volume: {name}"))
        else:
            failures.append(name)
            print(red(f"failed to remove volume: {name} ({result.stderr.strip()})"))
    for image_id, name in candidate_images:
        result = subprocess.run(
            ["docker", "image", "rm", image_id],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print(success(f"removed image: {name}"))
        else:
            failures.append(name)
            print(red(f"failed to remove image: {name} ({result.stderr.strip()})"))

    if failures:
        raise DevctlError(f"gc: {len(failures)} removal(s) failed", 1)


def _warn_orphan_volumes() -> None:
    names = _list_dangling_volumes()
    if not names:
        return
    print(warning(f"note: {len(names)} orphan docker volume(s) not attached to any container:"))
    for name in names[:10]:
        print(f"  - {name}")
    if len(names) > 10:
        print(f"  ... and {len(names) - 10} more")
    print(warning("review and remove manually with 'docker volume rm <name>' if no longer needed"))
    print(warning("or run 'devctl gc' to remove them"))


def _detect_cross_project_port_conflicts(settings: Settings) -> dict[int, list[str]]:
    registry = Registry(settings)
    registry.ensure()
    by_port: dict[int, set[str]] = {}
    for service in registry.services():
        by_port.setdefault(service.port, set()).add(service.name)
        for route in registry.extra_routes_for(service.name):
            by_port.setdefault(route.port, set()).add(service.name)
    return {port: sorted(names) for port, names in sorted(by_port.items()) if len(names) > 1}


def _warn_cross_project_port_conflicts(settings: Settings) -> dict[int, list[str]]:
    conflicts = _detect_cross_project_port_conflicts(settings)
    for port, names in conflicts.items():
        print(warning(f"note: port {port} is claimed by multiple registered profiles: {', '.join(names)}"))
    return conflicts


def _detect_unbounded_services(settings: Settings, git_root: Path | None) -> tuple[Path, list[str]] | None:
    if git_root is None or not (git_root / CONFIG_FILENAME).exists():
        return None
    try:
        profile = resolve_profile(settings, None)
    except DevctlError:
        return None
    compose_paths = [profile.path / compose_file for compose_file in profile.compose_files]
    if not all(path.exists() for path in compose_paths):
        return None
    file_args: list[str] = []
    for path in compose_paths:
        file_args.extend(["-f", str(path)])
    result = subprocess.run(
        ["docker", "compose", *file_args, "config", "--format", "json"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        cwd=profile.path,
    )
    if result.returncode != 0:
        return None
    try:
        config = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    unbounded = []
    for name, service in (config.get("services") or {}).items():
        limits = ((service.get("deploy") or {}).get("resources") or {}).get("limits") or {}
        has_mem = bool(service.get("mem_limit") or limits.get("memory"))
        has_cpu = bool(service.get("cpus") or limits.get("cpus"))
        if not (has_mem and has_cpu):
            unbounded.append(name)
    if not unbounded:
        return None
    return compose_paths[0], sorted(unbounded)


def _warn_missing_resource_limits(settings: Settings, git_root: Path | None) -> tuple[Path, list[str]] | None:
    detected = _detect_unbounded_services(settings, git_root)
    if not detected:
        return None
    _compose_path, unbounded = detected
    print(warning(f"note: {len(unbounded)} compose service(s) without CPU/memory limits: {', '.join(unbounded)}"))
    print(warning("a stuck process in one of these can consume all host resources unnoticed; consider setting mem_limit/cpus"))
    return detected


def _resource_limits_override_content(unbounded: list[str]) -> str:
    lines = [
        "# Generated by `devctl doctor --fix`.",
        "# Review and adjust before use -- not auto-loaded by `docker compose up`.",
        "",
        "services:",
    ]
    for name in unbounded:
        lines.extend([f"  {name}:", "    # mem_limit: 512m", '    # cpus: "1.0"'])
    return "\n".join(lines) + "\n"


def _fix_missing_resource_limits(compose_path: Path, unbounded: list[str], dry_run: bool) -> Path:
    override_path = compose_path.parent / RESOURCE_LIMITS_OVERRIDE_FILENAME
    content = _resource_limits_override_content(unbounded)
    if dry_run:
        print(info(f"would write {override_path}:"))
        print(content, end="")
    else:
        override_path.write_text(content, encoding="utf-8")
        print(success(f"wrote suggested resource limits to {override_path}"))
    return override_path


def _command_ok(command: list[str]) -> bool:
    return subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def _colored_status(status: str) -> str:
    if status == "healthy":
        return success(status)
    if status == "unhealthy":
        return red(status)
    if status == "stale":
        return warning(status)
    return info(status)


def _has_free_port(settings: Settings, registry: Registry) -> bool:
    from .net import is_port_free

    end = min(settings.port_start + 50, settings.port_end + 1)
    return any(is_port_free(settings, port) for port in range(settings.port_start, end))


def _can_bind_proxy_port(settings: Settings) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((settings.publish_host, 80))
        except OSError:
            return port_accepts_connections(settings.publish_host, 80)
    return True
