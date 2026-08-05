import argparse
from collections.abc import Callable, Iterable

from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document

from ..settings import Settings


class DevctlCompleter(Completer):
    def __init__(
        self,
        command_names: Iterable[str],
        meta_names: Iterable[str],
        project_provider: Callable[[], list[str]],
    ) -> None:
        self._commands = sorted(command_names)
        self._metas = sorted(meta_names)
        self._projects = project_provider

    def get_completions(self, document: Document, complete_event: CompleteEvent):
        text = document.text_before_cursor
        word = document.get_word_before_cursor(WORD=True)
        is_first_word = not text[: len(text) - len(word)].strip()
        if is_first_word:
            candidates = [*self._commands, *(f"/{name}" for name in self._metas)]
        elif word.startswith("-"):
            candidates = []
        else:
            try:
                candidates = self._projects()
            except Exception:
                candidates = []
        for candidate in candidates:
            if candidate.startswith(word):
                yield Completion(candidate, start_position=-len(word))


def build_completer(parser: argparse.ArgumentParser, settings: Settings) -> DevctlCompleter:
    from ..cli import subcommand_help
    from ..registry import Registry
    from .meta import meta_names

    command_names = [name for name in subcommand_help(parser) if name != "shell"]
    registry = Registry(settings)
    return DevctlCompleter(command_names, meta_names(), lambda: registry.names())
