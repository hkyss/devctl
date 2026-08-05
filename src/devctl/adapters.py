import json
import os
import subprocess
import sys

from .errors import DevctlError
from .override import ensure_override_stub, write_override
from .profiles import ProjectProfile
from .routing import domain_for, url_for
from .settings import Settings


def compose_project_name(profile: ProjectProfile) -> str:
    return profile.compose_project_name or f"devctl_{profile.name}_{os.environ.get('USER', 'user')}"


def published_ports(compose_project_name: str) -> set[int]:
    result = subprocess.run(
        ["docker", "compose", "-p", compose_project_name, "ps", "--format", "json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return set()

    ports: set[int] = set()
    for entry in _parse_compose_ps(result.stdout):
        for publisher in entry.get("Publishers") or []:
            port = publisher.get("PublishedPort")
            if isinstance(port, int) and port > 0:
                ports.add(port)
    return ports


def _parse_compose_ps(payload: str) -> list[dict]:
    stripped = payload.strip()
    if not stripped:
        return []
    if stripped.startswith("["):
        try:
            document = json.loads(stripped)
        except json.JSONDecodeError:
            return []
        return [entry for entry in document if isinstance(entry, dict)]

    entries = []
    for line in stripped.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


def compose_context_env(settings: Settings, profile: ProjectProfile) -> dict[str, str]:
    env = {key: str(value) for key, value in profile.env.items()}
    env["DEVCTL_DOMAIN"] = domain_for(settings, profile)
    env["DEVCTL_URL"] = url_for(settings, profile)
    env["COMPOSE_PROJECT_NAME"] = compose_project_name(profile)
    return env


class DockerComposeAdapter:
    name = "docker-compose"

    def __init__(self, settings: Settings, profile: ProjectProfile):
        self.settings = settings
        self.profile = profile

    def _compose_file_args(self) -> list[str]:
        args: list[str] = []
        for compose_file in self.profile.compose_files:
            args.extend(["-f", compose_file])
        if self.profile.publish or self.profile.compose_override:
            args.extend(["-f", str(ensure_override_stub(self.settings, self.profile))])
        return args

    def command_up(self) -> list[str]:
        args = ["docker", "compose"]
        if self.profile.env_file:
            args.extend(["--env-file", self.profile.env_file])
        args.extend(self._compose_file_args())
        args.extend(["up", "-d"])
        if self.profile.build:
            args.append("--build")
        args.append("--remove-orphans")
        return args

    def command_down(self) -> list[str]:
        args = ["docker", "compose"]
        if self.profile.env_file:
            args.extend(["--env-file", self.profile.env_file])
        args.extend(self._compose_file_args())
        args.extend(["down", "--remove-orphans"])
        return args

    def command_pre_up(self, command: list[str]) -> list[str]:
        args = ["docker", "compose"]
        if self.profile.env_file:
            args.extend(["--env-file", self.profile.env_file])
        args.extend(self._compose_file_args())
        args.extend(["run", "--rm"])
        args.extend(command)
        return args

    def env(self, backend_port: int, extra_ports: list[int]) -> dict[str, str]:
        env = os.environ.copy()
        env["DEVCTL_DOMAIN"] = domain_for(self.settings, self.profile)
        env["DEVCTL_URL"] = url_for(self.settings, self.profile)
        env["DEVCTL_BACKEND_PORT"] = str(backend_port)

        for key, value in self.profile.env.items():
            env[key] = str(value)

        if self.profile.http_port_env is not None:
            self._put_port(env, self.profile.http_port_env, backend_port)
        for key, port in zip(self.profile.extra_port_envs, extra_ports, strict=True):
            self._put_port(env, key, port)

        for key, spec in self.profile.publish_envs.items():
            source = spec["source"]
            target = spec["target"]
            host = os.path.expandvars(str(spec.get("host", self.settings.publish_host)))
            env[key] = f"{host}:{env[source]}:{target}"

        env["COMPOSE_PROJECT_NAME"] = compose_project_name(self.profile)
        return env

    def _put_port(self, env: dict[str, str], key: str, port: int) -> None:
        if key in self.profile.host_prefixed_port_envs:
            env[key] = f"{self.settings.publish_host}:{port}"
        else:
            env[key] = str(port)

    def up(self, backend_port: int, extra_ports: list[int], log_file) -> int:
        if self.profile.publish or self.profile.compose_override:
            write_override(self.settings, self.profile, backend_port)
        env = self.env(backend_port, extra_ports)
        for command in self.profile.pre_up_commands:
            exit_code = self._run_streaming(
                self.command_pre_up(command),
                env,
                log_file,
            )
            if exit_code != 0:
                return exit_code

        return self._run_streaming(
            self.command_up(),
            env,
            log_file,
        )

    def _run_streaming(self, command: list[str], env: dict[str, str], log_file) -> int:
        process = subprocess.Popen(
            command,
            cwd=self.profile.path,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        assert process.stdout is not None
        for line in process.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            log_file.write(line.encode())
            log_file.flush()

        return process.wait()

    def down(self) -> int:
        return subprocess.run(
            self.command_down(),
            cwd=self.profile.path,
            env=self.env(0, [0] * len(self.profile.extra_port_envs)),
        ).returncode

    def command_exec(self, service: str, cmd: list[str], tty: bool) -> list[str]:
        args = ["docker", "compose"]
        if self.profile.env_file:
            args.extend(["--env-file", self.profile.env_file])
        args.extend(self._compose_file_args())
        args.append("exec")
        if not tty:
            args.append("-T")
        args.append(service)
        args.extend(cmd)
        return args

    def exec(self, service: str, cmd: list[str], tty: bool) -> int:
        return subprocess.run(
            self.command_exec(service, cmd, tty),
            cwd=self.profile.path,
            env=self.env(0, [0] * len(self.profile.extra_port_envs)),
        ).returncode

    def command_logs(self, *, follow: bool, services: list[str], since: str | None, tail: int | None) -> list[str]:
        args = ["docker", "compose"]
        if self.profile.env_file:
            args.extend(["--env-file", self.profile.env_file])
        args.extend(self._compose_file_args())
        args.append("logs")
        if follow:
            args.append("-f")
        if since:
            args.extend(["--since", since])
        if tail is not None:
            args.extend(["--tail", str(tail)])
        args.extend(services)
        return args

    def logs(self, *, follow: bool, services: list[str], since: str | None, tail: int | None) -> int:
        return subprocess.run(
            self.command_logs(follow=follow, services=services, since=since, tail=tail),
            cwd=self.profile.path,
            env=self.env(0, [0] * len(self.profile.extra_port_envs)),
        ).returncode

    def command_ps_ids(self) -> list[str]:
        args = ["docker", "compose"]
        if self.profile.env_file:
            args.extend(["--env-file", self.profile.env_file])
        args.extend(self._compose_file_args())
        args.extend(["ps", "-q"])
        return args

    def container_ids(self) -> list[str]:
        result = subprocess.run(
            self.command_ps_ids(),
            cwd=self.profile.path,
            env=self.env(0, [0] * len(self.profile.extra_port_envs)),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def adapter_for(settings: Settings, profile: ProjectProfile) -> DockerComposeAdapter:
    if profile.adapter != DockerComposeAdapter.name:
        raise DevctlError(f"unsupported adapter '{profile.adapter}'", 3)
    return DockerComposeAdapter(settings, profile)
