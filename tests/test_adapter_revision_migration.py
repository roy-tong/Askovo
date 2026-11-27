"""CDP adapter revision migration through `askovo study set`.

Historical studies record the engine version that stamped their CDP manifests.
After an engine upgrade those runs must be re-audited, and the only CLI-safe
route is an explicit field write: the check refuses a stale revision, and
`study set` previously had no way to update `source_adapters.*`. These tests pin
the migration contract: only CDP visible-page adapters may follow the engine
version, API/historical connector pins never do, and a no-op stays a no-op.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/askovo/scripts/askovo.py"
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        check=False, capture_output=True, text=True, env=env, timeout=120)


def cdp_adapter(revision: str) -> dict:
    return {
        "enabled": True,
        "connector_id": "cdp-authorized-visible-page",
        "connector_revision": revision,
        "collection_mode": "authorized_visible_page",
        "access_basis": "cdp_authorized_visible_page",
    }


def api_adapter(revision: str) -> dict:
    return {
        "enabled": True,
        "connector_id": "reddit-arctic-shift-historical",
        "connector_revision": revision,
        "collection_mode": "historical_search",
        "access_basis": "historical_archive",
    }


class AdapterRevisionMigrationTests(unittest.TestCase):
    def make_study(self, adapters: dict | None = None) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        study = Path(directory.name) / "study"
        study.mkdir(parents=True)
        payload = {"title": "adapter migration fixture", "decision": {"question": "q"}}
        if adapters is not None:
            payload["source_adapters"] = adapters
        (study / "study.json").write_text(json.dumps(payload), encoding="utf-8")
        return study

    def read(self, study: Path) -> dict:
        return json.loads((study / "study.json").read_text(encoding="utf-8"))

    def test_one_cdp_adapter_migrates_to_the_current_engine_version(self) -> None:
        study = self.make_study({"discord": cdp_adapter("2.22.0"),
                                 "reddit": api_adapter("9f04bcc")})
        completed = run_cli("study", str(study), "set",
                            "--field", "source_adapters.discord.connector_revision",
                            "--value-json", '"current"')
        self.assertEqual(0, completed.returncode, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual("updated", payload["status"])
        self.assertEqual(VERSION, payload["connector_revision"])
        data = self.read(study)
        self.assertEqual(VERSION, data["source_adapters"]["discord"]["connector_revision"])
        self.assertEqual("9f04bcc", data["source_adapters"]["reddit"]["connector_revision"])

    def test_wildcard_touches_only_cdp_adapters(self) -> None:
        study = self.make_study({
            "discord": cdp_adapter("2.22.0"),
            "instagram": cdp_adapter("2.21.0"),
            "reddit": api_adapter("9f04bcc"),
        })
        completed = run_cli("study", str(study), "set",
                            "--field", "source_adapters.*.connector_revision",
                            "--value-json", '"current"')
        self.assertEqual(0, completed.returncode, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(["discord", "instagram"], sorted(payload["adapters"]))
        data = self.read(study)
        self.assertEqual(VERSION, data["source_adapters"]["discord"]["connector_revision"])
        self.assertEqual(VERSION, data["source_adapters"]["instagram"]["connector_revision"])
        self.assertEqual("9f04bcc", data["source_adapters"]["reddit"]["connector_revision"])

    def test_api_connector_pins_cannot_be_replaced_by_the_engine_version(self) -> None:
        study = self.make_study({"reddit": api_adapter("9f04bcc")})
        completed = run_cli("study", str(study), "set",
                            "--field", "source_adapters.reddit.connector_revision",
                            "--value-json", '"current"')
        self.assertEqual(2, completed.returncode)
        self.assertIn("不是 CDP 可见页适配器", completed.stderr)
        self.assertEqual("9f04bcc",
                         self.read(study)["source_adapters"]["reddit"]["connector_revision"])

    def test_unknown_platform_is_named_back(self) -> None:
        study = self.make_study({"discord": cdp_adapter("2.22.0")})
        completed = run_cli("study", str(study), "set",
                            "--field", "source_adapters.x.connector_revision",
                            "--value-json", '"current"')
        self.assertEqual(2, completed.returncode)
        self.assertIn("discord", completed.stderr)

    def test_missing_source_adapters_is_an_explicit_refusal(self) -> None:
        study = self.make_study(None)
        completed = run_cli("study", str(study), "set",
                            "--field", "source_adapters.*.connector_revision",
                            "--value-json", '"current"')
        self.assertEqual(2, completed.returncode)
        self.assertIn("source_adapters", completed.stderr)

    def test_repeating_the_same_revision_is_unchanged(self) -> None:
        study = self.make_study({"discord": cdp_adapter(VERSION)})
        completed = run_cli("study", str(study), "set",
                            "--field", "source_adapters.discord.connector_revision",
                            "--value-json", '"current"')
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("unchanged", json.loads(completed.stdout)["status"])

    def test_explicit_version_string_is_accepted(self) -> None:
        study = self.make_study({"discord": cdp_adapter("2.22.0")})
        completed = run_cli("study", str(study), "set",
                            "--field", "source_adapters.discord.connector_revision",
                            "--value-json", '"2.24.0"')
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("2.24.0",
                         self.read(study)["source_adapters"]["discord"]["connector_revision"])


if __name__ == "__main__":
    unittest.main()
