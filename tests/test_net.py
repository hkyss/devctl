import socket
from unittest.mock import Mock, patch

from devctl.net import is_port_free, port_accepts_connections, wait_for_http

from .helpers import TempDirTestCase, make_settings


class NetTests(TempDirTestCase):
    def test_port_accepts_connections_returns_true_for_open_socket(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            port = server.getsockname()[1]

            self.assertTrue(port_accepts_connections("127.0.0.1", port))

    def test_is_port_free_uses_bind_for_default_host(self) -> None:
        settings = make_settings(self.tmp_path)

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.bind(("127.0.0.1", 0))
            port = server.getsockname()[1]
            self.assertFalse(is_port_free(settings, port))

    def test_wait_for_http_returns_success_for_expected_status(self) -> None:
        response = Mock(status=204, reason="No Content")
        response.read.return_value = b""
        connection = Mock()
        connection.getresponse.return_value = response

        with patch("devctl.net.http.client.HTTPConnection", return_value=connection):
            ok, error = wait_for_http("example.local", 80, "/health", [200, 204], 1)

        self.assertTrue(ok)
        self.assertIsNone(error)
        connection.request.assert_called_once_with("GET", "/health")
        connection.close.assert_called_once()

    def test_wait_for_http_reports_status_body_and_throttles_repeated_messages(self) -> None:
        response = Mock(status=500, reason="Server Error")
        response.read.return_value = b"Error"
        connection = Mock()
        connection.getresponse.return_value = response
        attempts: list[str] = []

        with (
            patch("devctl.net.http.client.HTTPConnection", return_value=connection),
            patch("devctl.net.time.time", side_effect=[0, 0, 1, 1, 2, 2]),
            patch("devctl.net.time.sleep"),
        ):
            ok, error = wait_for_http("example.local", 80, "/", [200], 2, attempts.append)

        self.assertFalse(ok)
        self.assertEqual("HTTP 500: Error", error)
        self.assertEqual(["HTTP 500: Error"], attempts)

    def test_wait_for_http_reports_changed_errors(self) -> None:
        responses = []
        for status, body in [(503, b"Starting"), (500, b"Error")]:
            response = Mock(status=status, reason="Error")
            response.read.return_value = body
            responses.append(response)
        connection = Mock()
        connection.getresponse.side_effect = responses
        attempts: list[str] = []

        with (
            patch("devctl.net.http.client.HTTPConnection", return_value=connection),
            patch("devctl.net.time.time", side_effect=[0, 0, 1, 1, 2, 2]),
            patch("devctl.net.time.sleep"),
        ):
            ok, error = wait_for_http("example.local", 80, "/", [200], 2, attempts.append)

        self.assertFalse(ok)
        self.assertEqual("HTTP 500: Error", error)
        self.assertEqual(["HTTP 503: Starting", "HTTP 500: Error"], attempts)
