import http.client
import socket
import time
from collections.abc import Callable

from .settings import DEFAULT_HOST, Settings


def port_accepts_connections(host: str, port: int, timeout: float = 0.5) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        try:
            sock.connect((host, port))
            return True
        except OSError:
            return False


def is_port_free(settings: Settings, port: int) -> bool:
    if settings.upstream_host != DEFAULT_HOST:
        return not port_accepts_connections(settings.upstream_host, port)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((DEFAULT_HOST, port))
            return True
        except OSError:
            return False


def wait_for_port(host: str, port: int, timeout_seconds: int) -> tuple[bool, str | None]:
    deadline = time.time() + timeout_seconds
    last_error = None
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            try:
                sock.connect((host, port))
                return True, None
            except OSError as error:
                last_error = error
        time.sleep(1)
    return False, str(last_error)


def wait_for_http(
    host: str,
    port: int,
    path: str,
    expected_statuses: list[int],
    timeout_seconds: int,
    on_attempt: Callable[[str], None] | None = None,
) -> tuple[bool, str | None]:
    deadline = time.time() + timeout_seconds
    last_error = None
    last_reported = None
    last_reported_at = 0.0
    while time.time() < deadline:
        connection = http.client.HTTPConnection(host, port, timeout=2)
        try:
            connection.request("GET", path)
            response = connection.getresponse()
            body = response.read(200).decode("utf-8", errors="replace").strip()
            if response.status in expected_statuses:
                return True, None
            last_error = f"HTTP {response.status}: {body or response.reason}"
        except OSError as error:
            last_error = str(error)
        finally:
            connection.close()

        if on_attempt and last_error:
            now = time.time()
            if last_error != last_reported or now - last_reported_at >= 10:
                on_attempt(str(last_error))
                last_reported = str(last_error)
                last_reported_at = now
        time.sleep(1)
    return False, str(last_error)
