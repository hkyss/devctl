import json
from contextlib import redirect_stdout
from io import StringIO

from devctl.commands import recipes_list, recipes_show
from devctl.errors import DevctlError

from .helpers import TempDirTestCase, make_settings


class RecipesListTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.settings = make_settings(self.tmp_path)
        profiles_dir = self.settings.repo_root / "examples" / "profiles"
        profiles_dir.mkdir(parents=True)
        (profiles_dir / "vite.devctl.json").write_text(
            json.dumps({"name": "example-web", "adapter": "docker-compose"}) + "\n",
            encoding="utf-8",
        )

    def test_recipes_list_text_output(self) -> None:
        stdout = StringIO()
        with redirect_stdout(stdout):
            recipes_list(self.settings, as_json=False)
        output = stdout.getvalue()
        self.assertIn("vite", output)
        self.assertIn("Node or Vite frontend", output)

    def test_recipes_list_json_output(self) -> None:
        stdout = StringIO()
        with redirect_stdout(stdout):
            recipes_list(self.settings, as_json=True)
        payload = json.loads(stdout.getvalue())
        self.assertIsInstance(payload, list)
        names = [entry["name"] for entry in payload]
        self.assertIn("vite", names)
        self.assertEqual(sorted(names), names)
        vite_entry = next(entry for entry in payload if entry["name"] == "vite")
        self.assertEqual("Node or Vite frontend", vite_entry["description"])


class RecipesShowTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.settings = make_settings(self.tmp_path)
        profiles_dir = self.settings.repo_root / "examples" / "profiles"
        profiles_dir.mkdir(parents=True)
        (profiles_dir / "vite.devctl.json").write_text(
            json.dumps(
                {
                    "name": "example-web",
                    "adapter": "docker-compose",
                    "compose_file": "docker-compose.yml",
                    "http_port_env": "PORT_HTTP",
                    "preferred_ports": [5173],
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def test_recipes_show_text_output(self) -> None:
        stdout = StringIO()
        with redirect_stdout(stdout):
            recipes_show(self.settings, "vite", as_json=False)
        payload = json.loads(stdout.getvalue())
        self.assertEqual("example-web", payload["name"])
        self.assertEqual([5173], payload["preferred_ports"])

    def test_recipes_show_json_output(self) -> None:
        stdout = StringIO()
        with redirect_stdout(stdout):
            recipes_show(self.settings, "vite", as_json=True)
        payload = json.loads(stdout.getvalue())
        self.assertEqual("example-web", payload["name"])

    def test_recipes_show_unknown_recipe_raises(self) -> None:
        with self.assertRaises(DevctlError) as ctx:
            recipes_show(self.settings, "does-not-exist", as_json=False)
        self.assertIn("unknown recipe", str(ctx.exception))
        self.assertEqual(3, ctx.exception.code)
