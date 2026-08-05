from pathlib import Path

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

ACCENT = "#d77757"
DIM = "grey62"
OK_GLYPH = "✔"
FAIL_GLYPH = "✘"
PROMPT_GLYPH = "❯"
BANNER_GLYPH = "✳"
HINT_LINE = "commands as in CLI · /help · Tab to complete"


def make_console() -> Console:
    return Console(highlight=False)


def banner(console: Console, *, version: str, workspace_root: Path, project_count: int) -> None:
    body = Text()
    body.append(f"{BANNER_GLYPH} devctl v{version}\n\n", style=f"bold {ACCENT}")
    body.append(f"Workspace: {workspace_root} · {project_count} project(s)\n")
    body.append(HINT_LINE, style=DIM)
    console.print(Panel(body, box=box.ROUNDED, border_style=ACCENT, padding=(0, 2), expand=False))


def footer(console: Console, *, label: str, exit_code: int, seconds: float) -> None:
    if exit_code == 0:
        console.print(f"[green]{OK_GLYPH}[/green] [{DIM}]{label} · {seconds:.1f}s[/{DIM}]")
    else:
        console.print(f"[red]{FAIL_GLYPH}[/red] [{DIM}]{label} · exit {exit_code} · {seconds:.1f}s[/{DIM}]")


def error_line(console: Console, message: str) -> None:
    console.print(f"[red]error: {message}[/red]")


def hint(console: Console, message: str) -> None:
    console.print(f"[{DIM}]{message}[/{DIM}]")


def goodbye(console: Console) -> None:
    console.print(f"[{DIM}]bye[/{DIM}]")


def help_table(console: Console, command_rows: list[tuple[str, str]], meta_rows: list[tuple[str, str]]) -> None:
    table = Table(box=box.SIMPLE, show_header=True, header_style=f"bold {ACCENT}")
    table.add_column("Command")
    table.add_column("Description")
    for name, description in command_rows:
        table.add_row(name, description)
    for name, description in meta_rows:
        table.add_row(f"[{DIM}]{name}[/{DIM}]", f"[{DIM}]{description}[/{DIM}]")
    console.print(table)
