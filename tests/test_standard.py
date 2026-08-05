import json
import unittest
from pathlib import Path

from devctl.standard import KNOWN_PROFILE_KEYS

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "devctl.profile.schema.json"


class KnownProfileKeysSyncTests(unittest.TestCase):
    def test_known_profile_keys_matches_schema_properties(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        schema_keys = frozenset(schema["properties"].keys())

        self.assertEqual(
            KNOWN_PROFILE_KEYS,
            schema_keys,
            "KNOWN_PROFILE_KEYS in src/devctl/standard.py is out of sync with "
            "schemas/devctl.profile.schema.json properties; update both together",
        )
