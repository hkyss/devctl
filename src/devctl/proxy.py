from .registry import Registry
from .runtime import reload_proxy
from .settings import Settings
from .timeutil import now_iso


class CaddyfileWriter:
    def __init__(self, settings: Settings, registry: Registry):
        self.settings = settings
        self.registry = registry

    def write(self) -> None:
        self.registry.ensure()
        routes = self.registry.routes()
        lines = [
            "{",
            "    auto_https off",
            "}",
            "",
            ":80 {",
            '    respond "devctl: no route for {host}. Start it with: devctl up <project>" 502',
            "}",
            "",
        ]

        if not routes:
            lines.extend(
                [
                    "# No active devctl services.",
                    f"# Generated at {now_iso()}",
                    "",
                ]
            )

        for domain, host, port in routes:
            lines.extend(
                [
                    f"http://{domain} {{",
                    f"    reverse_proxy {host}:{port}",
                    "}",
                    "",
                ]
            )

        self.settings.caddyfile_path.write_text("\n".join(lines), encoding="utf-8")
        reload_proxy(self.settings)
