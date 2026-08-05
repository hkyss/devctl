import argparse
import os
import sys

from . import commands
from .console import error as red
from .errors import DevctlError
from .recipes import RECIPES
from .settings import Settings, load_settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="devctl")
    parser.add_argument("--no-color", action="store_true", help="disable colored output")
    parser.add_argument("--version", action="store_true", help="print version and exit")
    sub = parser.add_subparsers(dest="command", required=False)

    sub.add_parser("bootstrap", help="initialize state and write the Caddyfile")
    sub.add_parser("version", help="print version")

    doctor_parser = sub.add_parser("doctor", help="check the local environment")
    doctor_parser.add_argument("--json", action="store_true")
    doctor_parser.add_argument("--fix", action="store_true")
    doctor_parser.add_argument("--dry-run", action="store_true")
    doctor_parser.add_argument("--workspace", action="store_true", help="also check for cross-project port conflicts")

    init_parser = sub.add_parser("init", help="create .devctl.json for the current project")
    init_parser.add_argument("--name")
    init_parser.add_argument("--compose-file", default="docker-compose.yml")
    init_parser.add_argument("--env-file")
    init_parser.add_argument("--http-port-env", default="PORT_HTTP")
    init_parser.add_argument("--recipe", choices=sorted(RECIPES))
    init_parser.add_argument("--force", action="store_true")
    init_parser.add_argument("--dry-run", action="store_true")

    recipes_parser = sub.add_parser("recipes", help="inspect available profile recipes")
    recipes_sub = recipes_parser.add_subparsers(dest="recipes_command", required=True)
    recipes_list_parser = recipes_sub.add_parser("list", help="list available recipes")
    recipes_list_parser.add_argument("--json", action="store_true")
    recipes_show_parser = recipes_sub.add_parser("show", help="show a recipe's resolved profile")
    recipes_show_parser.add_argument("name", choices=sorted(RECIPES))
    recipes_show_parser.add_argument("--json", action="store_true")

    up_parser = sub.add_parser("up", help="start a project")
    up_parser.add_argument("projects", nargs="*")
    up_build_group = up_parser.add_mutually_exclusive_group()
    up_build_group.add_argument("--build", action="store_true")
    up_build_group.add_argument("--no-build", action="store_true")
    up_parser.add_argument("--json", action="store_true")

    restart_parser = sub.add_parser("restart", help="restart a project")
    restart_parser.add_argument("project", nargs="?")
    restart_build_group = restart_parser.add_mutually_exclusive_group()
    restart_build_group.add_argument("--build", action="store_true")
    restart_build_group.add_argument("--no-build", action="store_true")

    down_parser = sub.add_parser("down", help="stop a project")
    down_parser.add_argument("project", nargs="?")
    down_parser.add_argument("--all", action="store_true")

    list_parser = sub.add_parser("list", help="list registered services")
    list_parser.add_argument("--json", action="store_true")

    status_parser = sub.add_parser("status", help="show a project's status")
    status_parser.add_argument("project", nargs="?")
    status_parser.add_argument("--json", action="store_true")

    profile_parser = sub.add_parser("profile", help="print the resolved project profile")
    profile_parser.add_argument("project", nargs="?")
    profile_parser.add_argument("--json", action="store_true")

    env_parser = sub.add_parser("env", help="print the project's compose context as shell exports")
    env_parser.add_argument("project", nargs="?")
    env_parser.add_argument("--json", action="store_true")

    open_parser = sub.add_parser("open", help="print a project's URL and open it in the browser")
    open_parser.add_argument("project", nargs="?")

    logs_parser = sub.add_parser("logs", help="show project logs")
    logs_parser.add_argument("project", nargs="?")
    logs_parser.add_argument("-f", "--follow", action="store_true")
    logs_parser.add_argument("--service", action="append", dest="services", metavar="NAME")
    logs_parser.add_argument("--since")
    logs_parser.add_argument("--tail", type=int)

    validate_parser = sub.add_parser("validate", help="validate .devctl.json structure and team conventions")
    validate_parser.add_argument("project", nargs="?")
    validate_parser.add_argument("--workspace", action="store_true", help="validate every profile under DEVCTL_WORKSPACE_ROOT")
    validate_parser.add_argument(
        "--file",
        action="append",
        dest="files",
        metavar="PATH",
        help="validate a specific profile file (repeatable)",
    )
    validate_parser.add_argument("--strict", action="store_true", help="treat convention warnings as errors")
    validate_parser.add_argument("--json", action="store_true")

    prune_parser = sub.add_parser("prune", help="remove dead registry entries and regenerate the Caddyfile")
    prune_parser.add_argument("--dry-run", action="store_true")

    gc_parser = sub.add_parser("gc", help="remove orphan docker volumes and/or dangling images")
    gc_parser.add_argument("--dry-run", action="store_true")
    gc_parser.add_argument("--yes", action="store_true")
    gc_parser.add_argument("--volumes", action="store_true")
    gc_parser.add_argument("--images", action="store_true")

    exec_parser = sub.add_parser("exec", help="run a command inside a project's service container")
    exec_parser.add_argument("project", nargs="?")
    exec_parser.add_argument("--service")
    exec_parser.add_argument("-T", dest="no_tty", action="store_true", help="disable pseudo-TTY allocation")

    stats_parser = sub.add_parser("stats", help="show resource usage for a project's containers")
    stats_parser.add_argument("project", nargs="?")
    stats_parser.add_argument("--json", action="store_true")
    stats_parser.add_argument("--no-stream", action="store_true")

    sub.add_parser("shell", help="start the interactive shell")

    release_parser = sub.add_parser("release", help="tag and push a release (runs on the host via the wrapper)")
    release_parser.add_argument("version", nargs="?")

    make_parser = sub.add_parser("make", help="run a project Makefile target (runs on the host via the wrapper)")
    make_parser.add_argument("args", nargs=argparse.REMAINDER)

    return parser


def dispatch(args: argparse.Namespace, settings: Settings, exec_cmd: list[str] | None) -> int:
    if args.command == "bootstrap":
        commands.bootstrap(settings)
    elif args.command == "doctor":
        commands.doctor(settings, as_json=args.json, fix=args.fix, dry_run=args.dry_run, workspace=args.workspace)
    elif args.command == "init":
        commands.init_project(
            settings,
            name=args.name,
            compose_file=args.compose_file,
            env_file=args.env_file,
            http_port_env=args.http_port_env,
            recipe=args.recipe,
            force=args.force,
            dry_run=args.dry_run,
        )
    elif args.command == "recipes":
        if args.recipes_command == "list":
            commands.recipes_list(settings, args.json)
        elif args.recipes_command == "show":
            commands.recipes_show(settings, args.name, args.json)
    elif args.command == "up":
        for name in args.projects or [None]:
            commands.up(settings, name, build=args.build, no_build=args.no_build, as_json=args.json)
    elif args.command == "restart":
        commands.restart(settings, args.project, build=args.build, no_build=args.no_build)
    elif args.command == "down":
        commands.down(settings, args.project, args.all)
    elif args.command == "list":
        commands.list_services(settings, args.json)
    elif args.command == "status":
        commands.status(settings, args.project, args.json)
    elif args.command == "profile":
        commands.profile_print(settings, args.project, args.json)
    elif args.command == "env":
        commands.env_print(settings, args.project, args.json)
    elif args.command == "open":
        commands.open_project(settings, args.project)
    elif args.command == "logs":
        commands.logs(settings, args.project, args.follow, args.services, args.since, args.tail)
    elif args.command == "validate":
        commands.validate(
            settings,
            args.project,
            workspace=args.workspace,
            files=args.files,
            strict=args.strict,
            as_json=args.json,
        )
    elif args.command == "prune":
        commands.prune(settings, dry_run=args.dry_run)
    elif args.command == "gc":
        commands.gc(
            dry_run=args.dry_run,
            yes=args.yes,
            volumes=args.volumes,
            images=args.images,
        )
    elif args.command == "exec":
        return commands.exec_command(
            settings,
            args.project,
            service=args.service,
            tty=not args.no_tty,
            cmd=exec_cmd or [],
        )
    elif args.command == "stats":
        commands.stats(settings, args.project, args.json, args.no_stream)
    elif args.command in ("release", "make"):
        raise DevctlError(
            f"'{args.command}' runs on the host: invoke it through the devctl wrapper, not inside the container",
            2,
        )
    else:
        raise DevctlError(f"unknown command: {args.command}", 2)
    return 0


def subcommand_help(parser: argparse.ArgumentParser) -> dict[str, str]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return {choice.dest: choice.help or "" for choice in action._choices_actions}
    return {}


def main() -> int:
    argv = sys.argv[1:]
    exec_cmd: list[str] | None = None
    if "--" in argv:
        separator = argv.index("--")
        exec_cmd = argv[separator + 1 :]
        argv = argv[:separator]

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.no_color:
        os.environ["NO_COLOR"] = "1"
    if args.version or args.command == "version":
        commands.print_version()
        return 0
    if args.command == "shell" or (args.command is None and sys.stdin.isatty() and sys.stdout.isatty()):
        from . import shell

        return shell.run_shell(load_settings())
    if args.command is None:
        parser.print_help(sys.stderr)
        return 2
    settings = load_settings()
    try:
        return dispatch(args, settings, exec_cmd)
    except KeyboardInterrupt:
        return 130
    except DevctlError as error:
        print(red(f"error: {error}"), file=sys.stderr)
        return error.code


if __name__ == "__main__":
    raise SystemExit(main())
