from collections.abc import Iterable

from .errors import DevctlError
from .net import is_port_free
from .registry import Registry
from .settings import Settings


def allocate_ports(
    settings: Settings,
    registry: Registry,
    count: int,
    preferred: list[int],
    *,
    sticky: Iterable[int | None] | None = None,
    reclaimable: Iterable[int] | None = None,
    exclude_name: str | None = None,
) -> list[int]:
    used = set(registry.active_ports(exclude=exclude_name))
    owned = set(reclaimable or ())
    remembered = list(sticky or [])
    taken: set[int] = set()

    def claim(port: int) -> bool:
        if port in taken:
            return False
        if port in owned:
            taken.add(port)
            return True
        if port in used:
            return False
        if not is_port_free(settings, port):
            return False
        taken.add(port)
        return True

    slots: list[int | None] = [None] * count

    for index in range(min(count, len(preferred))):
        if claim(preferred[index]):
            slots[index] = preferred[index]

    for index in range(min(count, len(remembered))):
        port = remembered[index]
        if slots[index] is None and port is not None and claim(port):
            slots[index] = port

    fallback = iter(range(settings.port_start, settings.port_end + 1))
    for index in range(count):
        if slots[index] is not None:
            continue
        slots[index] = next((port for port in fallback if claim(port)), None)
        if slots[index] is None:
            raise DevctlError(f"could not allocate {count} free port(s) in range {settings.port_start}-{settings.port_end}", 4)

    return [port for port in slots if port is not None]
