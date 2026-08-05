import os
from unittest.mock import patch

from devctl.console import color, supports_color
from devctl.routing import domain_for, url_for

from .helpers import TempDirTestCase, make_profile, make_settings


class FakeStream:
    def __init__(self, tty: bool):
        self.tty = tty

    def isatty(self) -> bool:
        return self.tty


class RoutingConsoleTests(TempDirTestCase):
    def test_domain_for_localhost_uses_plain_project_domain(self) -> None:
        settings = make_settings(self.tmp_path)

        self.assertEqual("app.localhost", domain_for(settings, make_profile(name="app")))

    def test_domain_for_custom_suffix_includes_user(self) -> None:
        settings = make_settings(self.tmp_path)
        settings = settings.__class__(**{**settings.__dict__, "dns_suffix": "dev.test"})

        with patch.dict(os.environ, {"USER": "alice"}, clear=False):
            self.assertEqual("app.alice.dev.test", domain_for(settings, make_profile(name="app")))

    def test_domain_override_replaces_user_placeholder(self) -> None:
        settings = make_settings(self.tmp_path)

        with patch.dict(os.environ, {"USER": "alice"}, clear=False):
            self.assertEqual("app-alice.localhost", domain_for(settings, make_profile(domain="app-${USER}.localhost")))

    def test_url_for_uses_settings_scheme(self) -> None:
        settings = make_settings(self.tmp_path)
        settings = settings.__class__(**{**settings.__dict__, "url_scheme": "https"})

        self.assertEqual("https://app.localhost", url_for(settings, make_profile()))

    def test_color_is_disabled_for_non_tty(self) -> None:
        self.assertEqual("hello", color("hello", "green", stream=FakeStream(False)))

    def test_color_is_disabled_by_no_color(self) -> None:
        with patch.dict(os.environ, {"NO_COLOR": "1"}):
            self.assertFalse(supports_color(FakeStream(True)))
            self.assertEqual("hello", color("hello", "green", stream=FakeStream(True)))

    def test_color_wraps_known_color_for_tty(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual("\033[32mhello\033[0m", color("hello", "green", stream=FakeStream(True)))

    def test_unknown_color_returns_plain_text(self) -> None:
        self.assertEqual("hello", color("hello", "unknown", stream=FakeStream(True)))
