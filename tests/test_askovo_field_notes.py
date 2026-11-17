"""Platform field notes: the campaign experience is data, not prose.

Covers the registry contract (required fields, verification legend, artifact
and helper references, catalog/cdp consistency), the engine surface
(`askovo platforms --field-notes`, `--platform`, JSON) and the doctor gate.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/askovo/scripts/askovo.py"
ASSETS = ROOT / "skills/askovo/assets"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(CLI), *args], check=False, capture_output=True, text=True)


def load_registry() -> dict:
    return json.loads((ASSETS / "platform-field-notes.json").read_text(encoding="utf-8"))


class FieldNotesRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = load_registry()
        self.catalog = json.loads((ASSETS / "platform-catalog.json").read_text(encoding="utf-8"))
        self.catalog_ids = {str(item["id"]) for item in self.catalog["platforms"]}
        self.legend = set(self.registry["verification_legend"])

    def test_registry_is_versioned_and_dated(self) -> None:
        self.assertEqual("1.0", self.registry["schema_version"])
        self.assertRegex(self.registry["generated_at"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertTrue(self.registry["source"]["method_doc"].endswith("cdp-collection-playbook.md"))

    def test_every_note_has_required_fields(self) -> None:
        required = (
            "id", "platform", "channel", "restriction", "symptom", "solution",
            "artifact", "verification", "cdp",
        )
        ids: set[str] = set()
        for note in self.registry["notes"]:
            with self.subTest(note=note.get("id")):
                for key in required:
                    self.assertNotIn(note.get(key), (None, "", []), f"{note.get('id')} missing {key}")
                self.assertNotIn(note["id"], ids, "duplicate note id")
                ids.add(note["id"])

    def test_verification_status_comes_from_the_legend(self) -> None:
        for note in self.registry["notes"]:
            with self.subTest(note=note["id"]):
                self.assertIn(note["verification"]["status"], self.legend)
                self.assertRegex(note["verification"]["date"], r"^\d{4}-\d{2}-\d{2}$")
                self.assertTrue(note["verification"]["evidence"])

    def test_platform_values_are_catalog_ids_or_declared_source_types(self) -> None:
        allowed = self.catalog_ids | set(self.registry["source_types"]) | {"*"}
        for note in self.registry["notes"]:
            with self.subTest(note=note["id"]):
                self.assertIn(note["platform"], allowed)

    def test_cdp_flag_matches_the_platform_catalog(self) -> None:
        catalog = {str(item["id"]): item for item in self.catalog["platforms"]}
        for note in self.registry["notes"]:
            if note["platform"] == "*" or note["platform"] not in catalog:
                continue
            with self.subTest(note=note["id"]):
                self.assertEqual(
                    bool(catalog[note["platform"]].get("cdp")), bool(note["cdp"]),
                    f"{note['id']} disagrees with platform-catalog cdp flag",
                )

    def test_every_campaign_platform_has_at_least_one_note(self) -> None:
        """The campaign's own channels must not lose their experience."""
        noted = {note["platform"] for note in self.registry["notes"]}
        for platform in self.registry["source"]["campaign_platforms"]:
            with self.subTest(platform=platform):
                self.assertIn(platform, noted)
        self.assertIn("coverage_boundary", self.registry["source"])

    def test_artifacts_and_helpers_resolve(self) -> None:
        for note in self.registry["notes"]:
            with self.subTest(note=note["id"]):
                self.assertTrue((ROOT / note["artifact"]).is_file(), note["artifact"])
                helper = note.get("helper")
                if helper:
                    module_name, _, attr = helper.rpartition(".")
                    module_path = ROOT / "skills/askovo/scripts" / (module_name.replace(".", "/") + ".py")
                    self.assertTrue(module_path.is_file(), helper)
                    self.assertIn(attr, module_path.read_text(encoding="utf-8"))

    def test_cross_platform_notes_are_marked_generic(self) -> None:
        generic = [note for note in self.registry["notes"] if note["platform"] == "*"]
        self.assertGreaterEqual(len(generic), 3)
        for note in generic:
            self.assertTrue(note["channel"])


class FieldNotesEngineTests(unittest.TestCase):
    def test_doctor_reports_a_consistent_registry(self) -> None:
        completed = run_cli("doctor")
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("platform-field-notes", completed.stdout)
        self.assertRegex(completed.stdout, r"\[ok\] platform-field-notes \d+ notes")

    def test_platforms_json_carries_notes_for_ranked_platforms(self) -> None:
        completed = run_cli("platforms", "Discord 社区和 Kickstarter 众筹评论里的用户抱怨", "--json")
        self.assertEqual(0, completed.returncode, completed.stderr)
        data = json.loads(completed.stdout)
        self.assertTrue(data["field_notes"])
        by_id = {item["id"]: item for item in data["recommended"]}
        self.assertIn("discord", by_id)
        note_ids = {note["id"] for note in by_id["discord"]["field_notes"]}
        self.assertIn("discord-programmatic-scroll-ignored", note_ids)
        # cross-platform practice travels with every ranked platform
        self.assertIn("generic-single-writer-state", note_ids)

    def test_platforms_field_notes_view_renders_the_method_table(self) -> None:
        completed = run_cli("platforms", "Kickstarter 众筹评论", "--field-notes")
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("平台实战笔记", completed.stdout)
        self.assertIn("load more", completed.stdout)
        self.assertIn("kickstarter", completed.stdout)
        self.assertIn("不是访问许可", completed.stdout)

    def test_platform_filter_narrows_the_radar(self) -> None:
        completed = run_cli("platforms", "Discord 社区抱怨", "--platform", "discord", "--json")
        self.assertEqual(0, completed.returncode, completed.stderr)
        data = json.loads(completed.stdout)
        self.assertEqual(["discord"], [item["id"] for item in data["recommended"]])
        self.assertEqual("discord", data["platform_filter"])
        self.assertTrue(all(note["platform"] in {"discord", "*"} for note in data["field_notes"]))

    def test_unknown_platform_filter_exits_2(self) -> None:
        completed = run_cli("platforms", "Discord 社区抱怨", "--platform", "no-such-platform")
        self.assertEqual(2, completed.returncode)
        self.assertIn("unknown platform", completed.stderr)

    def test_default_radar_markdown_surfaces_field_notes(self) -> None:
        completed = run_cli("platforms", "Discord 社区抱怨")
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("已知平台限制与解法", completed.stdout)


if __name__ == "__main__":
    unittest.main()
