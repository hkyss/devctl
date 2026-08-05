# devctl

Dockerized control plane for running multiple local projects behind clean `*.localhost` domains, with a single CLI to boot, inspect, and tear them down.

```text
example-web.localhost -> Caddy -> host.docker.internal:<allocated-port>
example-api.localhost -> Caddy -> host.docker.internal:<allocated-port>
```

## Why

Running several company projects locally usually means juggling ports, `.env` files, and ad-hoc `docker compose` invocations per repo. `devctl` centralizes that: one registry, one proxy, one CLI surface across all of them — while every project's own stack keeps running in its own Compose file untouched.

## Requirements

- Docker (Compose v2) and Git on the host; `make` is only needed to work on devctl itself.
- Nothing else — `devctl` itself, Python, Caddy, dnsmasq, and mkcert all run inside containers.

## Quick Start

```bash
cd ~/Projects/Github/devctl
make install && make boot && make doctor

cd ~/Projects/Github/<project>
devctl init
devctl up
```

Open `http://<project>.localhost`.

Expected workspace layout: sibling repos under one root (default `~/Projects/Github/`, override with `DEVCTL_WORKSPACE_ROOT`).

## Everyday Commands

```text
devctl up | down | restart | status | logs | exec | stats | gc
devctl open [project]                            # open the project URL in the browser
devctl make [target] [args]                      # run a project Makefile target (expanded in the container, executed on the host)
devctl release X.Y.Z|major|minor|patch           # tag and push a release; bump keywords use the latest tag, CI publishes
devctl prune [--dry-run]                         # drop dead registry entries, regenerate Caddyfile
devctl validate --strict
devctl profile [--json]                          # print the resolved project profile
devctl env [project] [--json]                    # print the project's compose context as shell exports
devctl recipes list [--json] | show <name> [--json]  # inspect available profile recipes
devctl doctor [--json] [--workspace] [--fix]
devctl up --json | status --json | list --json   # structured output for scripts and IDEs
```

Run `devctl` with no arguments in a terminal for an interactive shell with history and tab completion. Full command reference: `devctl --help`.

## Project Profiles

Each project declares itself in a `.devctl.json` at its repo root. Scaffold one with `devctl init`, or start from a recipe for a common stack:

```bash
devctl recipes list
devctl init --recipe vite
```

A minimal profile:

```json
{
  "name": "example-web",
  "adapter": "docker-compose",
  "compose_file": "docker-compose.yml",
  "http_port_env": "PORT_HTTP",
  "preferred_ports": [8080],
  "health_check_path": "/"
}
```

Required: `name`, `adapter` (only `docker-compose` today), exactly one of `compose_file` / `compose_files`, and exactly one of `http_port_env` / `publish`.

Useful optional fields:

| Field | Purpose |
|---|---|
| `extra_port_envs` | Additional ports devctl allocates and injects |
| `preferred_ports` | Ports tried before the managed range, one per managed env var, positionally |
| `host_prefixed_port_envs` | Vars whose Compose file expects `127.0.0.1:<port>` rather than a bare number |
| `publish_envs` | Vars whose Compose file expects a full spec like `127.0.0.1:16000:80` |
| `publish` | Let devctl publish the port itself; the project Compose file needs no port config at all |
| `compose_override` | Inline Compose fragment merged last — extra services, networks, volumes |
| `env`, `env_file` | Fixed env overrides and a Compose env file |
| `pre_up_commands` | `docker compose run --rm` commands executed before startup |
| `health_check_path`, `health_check_statuses`, `health_timeout_seconds` | Readiness check; without a path devctl only waits for the TCP port |
| `primary_service` | Service `devctl exec` targets when `--service` is omitted |
| `domain`, `compose_project_name` | Explicit overrides for the generated values |

Ports are allocated positionally: `http_port_env` takes the first slot, then each `extra_port_envs` entry in order. Each slot falls back from its own `preferred_ports` value, to the port it held last run, to the managed range — never to another slot's preferred port. Ports a project's own containers already publish count as available to it, so `devctl up` on a live stack keeps them.

Working examples live in [`examples/profiles/`](examples/profiles/), and the full field list with types and constraints is the JSON Schema at [`schemas/devctl.profile.schema.json`](schemas/devctl.profile.schema.json) — point your editor at it for completion and inline validation. `devctl validate --strict` runs the same checks without starting anything.

## Versioning and Upgrades

`devctl --version` reports the version baked into the container image at build time (from `git describe --tags`). After pulling a new version of this repo, rebuild the image or the CLI keeps running the old code and version:

```bash
git pull
make build
```

Releases are cut by pushing a `v*` tag: CI runs checks and tests, then publishes a [GitHub Release](https://github.com/hkyss/devctl/releases) with generated notes.

## Constraints

- Local development only — not for CI or servers.
- Mounts `/var/run/docker.sock`; treat the container as trusted local tooling.
- HTTP + `*.localhost` only; no TLS, no custom TLDs.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Security reports: [SECURITY.md](SECURITY.md).

## License

Apache-2.0
