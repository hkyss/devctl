import fcntl
from collections.abc import Iterator
from contextlib import contextmanager

from .settings import Settings


@contextmanager
def state_lock(settings: Settings) -> Iterator[None]:
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    with settings.lock_path.open("w", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
