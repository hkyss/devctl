import json
from pathlib import Path
from typing import Any

from .errors import DevctlError
from .settings import Settings

RECIPES: dict[str, str] = {
    "backend": "API with database and Redis",
    "laravel": "Laravel or PHP application",
    "publish": "Full publish spec variable",
    "python": "Python API",
    "rails": "Rails application",
    "vite": "Node or Vite frontend",
}


def recipe_names() -> list[str]:
    return sorted(RECIPES)


def recipe_path(settings: Settings, name: str) -> Path:
    if name not in RECIPES:
        expected = ", ".join(recipe_names())
        raise DevctlError(f"unknown recipe '{name}'. Expected one of: {expected}", 3)
    return settings.repo_root / "examples" / "profiles" / f"{name}.devctl.json"


def load_recipe(settings: Settings, name: str) -> dict[str, Any]:
    path = recipe_path(settings, name)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise DevctlError(f"recipe file does not exist: {path}", 3) from error
    if not isinstance(payload, dict):
        raise DevctlError(f"invalid recipe {path}: expected a JSON object", 3)
    return payload
