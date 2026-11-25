from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from skills.askovo.scripts import askovo_mcp, diary_study

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/askovo/scripts/askovo.py"


class DiaryStudyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "diary"

    def spec(self):
        return {
            "schema": "askovo.diary-study/1", "study_id": "diary-demo",
            "objective": "Observe repeated daily experiences",
            "prompt": "What happened today?", "consent_notice": "Synthetic local diary only",
            "registered_by": "research-owner", "registered_at": "2026-11-24T00:00:00Z",
            "window": {"start": "2026-11-24T00:00:00Z", "end": "2026-11-30T00:00:00Z"},
            "schedule": ["2026-11-25", "2026-11-26", "2026-11-27"],
            "participants": [
                {"participant_ref": "p1", "screening_ref": "screening:p1"},
                {"participant_ref": "p2", "screening_ref": "screening:p2"},
            ],
        }

    def entry(self, **changes):
        row = {
            "entry_id": "entry-p1-25", "participant_ref": "p1",
            "scheduled_date": "2026-11-25", "submitted_at": "2026-11-25T20:00:00Z",
            "response": "A detailed daily experience", "source_ref": "local:entry-p1-25",
            "consent_ref": "consent:p1", "consent_state": "accepted",
        }
        row.update(changes)
        return row

    def test_multiday_entries_dedupe_late_arrival_and_due_cells(self):
        diary_study.create(self.spec(), self.root)
        late = self.entry(entry_id="entry-p1-26", scheduled_date="2026-11-26",
                          submitted_at="2026-11-27T09:00:00Z")
        first = diary_study.import_entries(self.root, [self.entry(), late], imported_by="owner")
        second = diary_study.import_entries(self.root, [late], imported_by="owner")
        self.assertEqual(2, first["added"])
        self.assertEqual(1, second["duplicates"])
        report = diary_study.status(self.root, now="2026-11-26T12:00:00Z")
        self.assertEqual(6, report["totals"]["registered_cells"])
        self.assertEqual(2, report["totals"]["accepted_entries"])
        self.assertEqual(1, report["totals"]["late_entries"])
        self.assertEqual(2, len(report["due_cells"]))
        exported = diary_study.export_aggregate(self.root)
        self.assertNotIn("p1", json.dumps(exported))
        self.assertNotIn("A detailed daily experience", json.dumps(exported))
        self.assertEqual(2, exported["totals"]["accepted_entries"])

    def test_requires_registered_participant_schedule_and_accepted_consent(self):
        diary_study.create(self.spec(), self.root)
        invalid = [
            self.entry(participant_ref="unknown"),
            self.entry(scheduled_date="2026-11-28"),
            self.entry(consent_state="pending"),
            self.entry(consent_ref=""),
        ]
        for row in invalid:
            with self.subTest(row=row):
                with self.assertRaises(ValueError):
                    diary_study.import_entries(self.root, [row], imported_by="owner")
        self.assertEqual(0, diary_study.status(self.root)["totals"]["accepted_entries"])

    def test_withdrawal_excludes_response_and_blocks_later_entries(self):
        diary_study.create(self.spec(), self.root)
        withdrawn = self.entry(entry_id="withdraw-p1", scheduled_date="2026-11-26",
                               submitted_at="2026-11-26T12:00:00Z", response="",
                               consent_state="withdrawn")
        diary_study.import_entries(self.root, [self.entry(), withdrawn], imported_by="owner")
        report = diary_study.status(self.root)
        self.assertEqual(1, report["totals"]["accepted_entries"])
        self.assertEqual(1, report["totals"]["withdrawals"])
        with self.assertRaisesRegex(ValueError, "withdrawn"):
            diary_study.import_entries(self.root, [
                self.entry(entry_id="entry-p1-27", scheduled_date="2026-11-27",
                           submitted_at="2026-11-27T20:00:00Z")
            ], imported_by="owner")
        self.assertNotIn("A detailed daily experience",
                         json.dumps(diary_study.export_aggregate(self.root)))

    def test_withdrawal_rejects_new_backdated_entry(self):
        diary_study.create(self.spec(), self.root)
        withdrawn = self.entry(entry_id="withdraw-p1", scheduled_date="2026-11-26",
                               submitted_at="2026-11-26T12:00:00Z", response="",
                               consent_state="withdrawn")
        diary_study.import_entries(self.root, [withdrawn], imported_by="owner")
        with self.assertRaisesRegex(ValueError, "withdrawn"):
            diary_study.import_entries(self.root, [self.entry()], imported_by="owner")
        self.assertEqual(0, diary_study.status(self.root)["totals"]["accepted_entries"])

    def test_exact_duplicate_remains_idempotent_after_withdrawal(self):
        diary_study.create(self.spec(), self.root)
        diary_study.import_entries(self.root, [self.entry()], imported_by="owner")
        withdrawn = self.entry(entry_id="withdraw-p1", scheduled_date="2026-11-26",
                               submitted_at="2026-11-26T12:00:00Z", response="",
                               consent_state="withdrawn")
        diary_study.import_entries(self.root, [withdrawn], imported_by="owner")
        repeated = diary_study.import_entries(self.root, [self.entry()], imported_by="owner")
        self.assertEqual(1, repeated["duplicates"])
        self.assertEqual(0, repeated["added"])

    def test_registered_spec_drift_is_rejected(self):
        diary_study.create(self.spec(), self.root)
        path = self.root / diary_study.SPEC_NAME
        changed = json.loads(path.read_text(encoding="utf-8"))
        changed["schedule"] = ["2026-11-25"]
        path.write_text(json.dumps(changed), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "fingerprint mismatch"):
            diary_study.status(self.root)

    def test_cli_create_import_status_and_aggregate_export(self):
        spec = Path(self.tmp.name) / "diary.json"
        entries = Path(self.tmp.name) / "entries.jsonl"
        out = Path(self.tmp.name) / "aggregate.json"
        spec.write_text(json.dumps(self.spec()), encoding="utf-8")
        entries.write_text(json.dumps(self.entry()) + "\n", encoding="utf-8")
        commands = [
            ["create", "--spec", str(spec), "--out", str(self.root)],
            ["import", "--dir", str(self.root), "--file", str(entries), "--by", "owner"],
            ["status", "--dir", str(self.root), "--at", "2026-11-26T12:00:00Z"],
            ["export", "--dir", str(self.root), "--out", str(out)],
        ]
        for action in commands:
            result = subprocess.run([
                sys.executable, str(CLI), "experiment", "diary", action[0], *action[1:],
            ], text=True, capture_output=True)
            self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        self.assertEqual("askovo.diary-study-aggregate/1", json.loads(out.read_text())["schema"])

    def test_mcp_uses_the_same_local_diary_runtime(self):
        spec = Path(self.tmp.name) / "diary.json"
        entries = Path(self.tmp.name) / "entries.jsonl"
        out = Path(self.tmp.name) / "aggregate.json"
        spec.write_text(json.dumps(self.spec()), encoding="utf-8")
        entries.write_text(json.dumps(self.entry()) + "\n", encoding="utf-8")
        created = askovo_mcp._run_tool("askovo_primary_research", {
            "action": "diary_create", "spec": str(spec), "out": str(self.root),
        })
        self.assertEqual(0, created["exit_code"], created)
        imported = askovo_mcp._run_tool("askovo_primary_research", {
            "action": "diary_import", "dir": str(self.root), "file": str(entries), "by": "owner",
        })
        self.assertEqual(0, imported["exit_code"], imported)
        status = askovo_mcp._run_tool("askovo_primary_research", {
            "action": "diary_status", "dir": str(self.root), "at": "2026-11-26T12:00:00Z",
        })
        self.assertEqual(1, status["result"]["totals"]["accepted_entries"])
        exported = askovo_mcp._run_tool("askovo_primary_research", {
            "action": "diary_export", "dir": str(self.root), "out": str(out),
        })
        self.assertEqual(0, exported["exit_code"], exported)
        self.assertEqual("askovo.diary-study-aggregate/1", json.loads(out.read_text())["schema"])


if __name__ == "__main__":
    unittest.main()
