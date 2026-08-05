import argparse
import time
from collections.abc import Callable

from rich.console import Console

from ..cli import build_parser, dispatch
from ..commands import get_version, print_version
from ..errors import DevctlError
from ..registry import Registry
from ..settings import Settings
from . import ui
from .meta import ShellContext, find_meta, meta_names
from .parsing import ParsedLine, parse_line

PromptFn = Callable[[], str]


def run_shell(
    settings: Settings,
    *,
    console: Console | None = None,
    prompt: PromptFn | None = None,
    parser: argparse.ArgumentParser | None = None,
) -> int:
    console = console or ui.make_console()
    parser = parser or build_parser()
    ctx = ShellContext(console=console, settings=settings, parser=parser)
    if prompt is None:
        prompt = _build_prompt(ctx)
    _print_banner(ctx)
    while True:
        try:
            line = prompt()
        except KeyboardInterrupt:
            continue
        except EOFError:
            ui.goodbye(console)
            return 0
        handle_line(ctx, line)
        if ctx.should_exit:
            ui.goodbye(console)
            return 0


def handle_line(ctx: ShellContext, line: str) -> None:
    try:
        parsed = parse_line(line)
    except ValueError as error:
        ui.error_line(ctx.console, str(error))
        return
    if parsed.kind == "empty":
        return
    if parsed.kind == "meta":
        meta = find_meta(parsed.name)
        if meta is None:
            available = " ".join(f"/{name}" for name in meta_names())
            ui.hint(ctx.console, f"unknown command /{parsed.name} · available: {available}")
            return
        meta.handler(ctx)
        return
    started = time.monotonic()
    exit_code = _execute(ctx, parsed)
    ui.footer(ctx.console, label=" ".join(parsed.args), exit_code=exit_code, seconds=time.monotonic() - started)


def _execute(ctx: ShellContext, parsed: ParsedLine) -> int:
    try:
        args = ctx.parser.parse_args(parsed.args)
    except SystemExit as exit_:
        return int(exit_.code or 0)
    if args.version or args.command == "version":
        print_version()
        return 0
    if args.command is None:
        return 0
    if args.command == "shell":
        ui.hint(ctx.console, "already in the shell")
        return 0
    try:
        return dispatch(args, ctx.settings, parsed.exec_cmd)
    except KeyboardInterrupt:
        return 130
    except DevctlError as error:
        ui.error_line(ctx.console, str(error))
        return error.code


def _print_banner(ctx: ShellContext) -> None:
    try:
        project_count = len(Registry(ctx.settings).names())
    except Exception:
        project_count = 0
    ui.banner(ctx.console, version=get_version(), workspace_root=ctx.settings.workspace_root, project_count=project_count)


def _toolbar_text(ctx: ShellContext) -> str:
    try:
        services = Registry(ctx.settings).services()
        running = sum(1 for service in services if service.status == "running")
        counts = f"running: {running}/{len(services)}"
    except Exception:
        counts = "registry: not initialized"
    return f" {ctx.settings.workspace_root.name} · {counts} · /help · /exit "


def _build_prompt(ctx: ShellContext) -> PromptFn:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.history import FileHistory

    from .completion import build_completer

    history_path = ctx.settings.state_dir / "shell_history"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    session: PromptSession = PromptSession(
        message=[(f"fg:{ui.ACCENT} bold", f"{ui.PROMPT_GLYPH} ")],
        history=FileHistory(str(history_path)),
        auto_suggest=AutoSuggestFromHistory(),
        completer=build_completer(ctx.parser, ctx.settings),
    )

    def prompt() -> str:
        return session.prompt(bottom_toolbar=_toolbar_text(ctx))

    return prompt
