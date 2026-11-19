#!/usr/bin/env python3
"""Owner adoption is a separate business event, never inferred from delivery."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/askovo/scripts/askovo.py"
SAMPLE = ROOT / "examples/sample-study"


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(CLI), *args],
                          capture_output=True, text=True, timeout=180)


class DecisionAdoptionTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.study = Path(tmp.name) / "study"
        shutil.copytree(SAMPLE, self.study)
        self.reasoning_path = self.study / "04-findings/product-reasoning.json"

    def record(self) -> str:
        completed = run_cli("decision", "record", str(self.study),
                            "--chain", "PR01", "--by", "Decision owner")
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        return json.loads(completed.stdout)["record"]["record_id"]

    def test_record_and_brief_do_not_imply_adoption(self) -> None:
        record_id = self.record()
        brief = run_cli("brief", str(self.study), "--format", "json")
        self.assertEqual(0, brief.returncode, brief.stdout + brief.stderr)
        document = json.loads(brief.stdout)
        lifecycle = document["decision_lifecycle"]
        self.assertEqual(record_id, lifecycle["decision_record_id"])
        self.assertEqual("recorded", lifecycle["record_state"])
        self.assertEqual("not_observed", lifecycle["adoption_state"])
        self.assertEqual("not_approved", document["decision_state"])

    def test_adoption_requires_owner_scope_record_and_receipt(self) -> None:
        record_id = self.record()
        before = self.reasoning_path.read_bytes()
        for extra in (
            ("--by", "Owner", "--scope", "Bounded pilot"),
            ("--by", "Owner", "--adoption-evidence", "owner-receipt-01"),
            ("--record-id", record_id, "--scope", "Bounded pilot",
             "--adoption-evidence", "owner-receipt-01"),
        ):
            completed = run_cli("decision", "adopt", str(self.study), *extra)
            self.assertEqual(2, completed.returncode, completed.stdout + completed.stderr)
            self.assertEqual(before, self.reasoning_path.read_bytes())

    def test_named_owner_adoption_is_append_only_and_visible_in_brief(self) -> None:
        record_id = self.record()
        adopted = run_cli(
            "decision", "adopt", str(self.study), "--record-id", record_id,
            "--by", "Test accountable owner", "--scope", "Synthetic bounded pilot only",
            "--adoption-evidence", "synthetic-owner-receipt-01",
        )
        self.assertEqual(0, adopted.returncode, adopted.stdout + adopted.stderr)
        result = json.loads(adopted.stdout)
        self.assertEqual("adopted", result["status"])
        self.assertFalse(result["chain_changed"])
        receipt = result["adoption"]
        self.assertEqual(record_id, receipt["decision_record_id"])
        self.assertEqual("declaration_only", receipt["identity_basis"])
        reasoning = json.loads(self.reasoning_path.read_text(encoding="utf-8"))
        self.assertEqual(1, len(reasoning["decision_adoptions"]))

        reviewed = run_cli("review", str(self.study), "--json")
        self.assertIn(reviewed.returncode, (0, 1), reviewed.stdout + reviewed.stderr)
        brief = run_cli("brief", str(self.study), "--format", "json")
        self.assertEqual(0, brief.returncode, brief.stdout + brief.stderr)
        document = json.loads(brief.stdout)
        self.assertEqual("adopted", document["decision_lifecycle"]["adoption_state"])
        self.assertEqual("adopted", document["decision_state"])
        self.assertEqual("not_claimed", document["causality_state"])
        markdown = (self.study / "06-report/decision-brief.md").read_text(encoding="utf-8")
        self.assertIn("负责人采用", markdown)
        duplicate = run_cli(
            "decision", "adopt", str(self.study), "--record-id", record_id,
            "--by", "Test accountable owner", "--scope", "Synthetic bounded pilot only",
            "--adoption-evidence", "duplicate-receipt",
        )
        self.assertEqual(2, duplicate.returncode)
        self.assertEqual(1, len(json.loads(self.reasoning_path.read_text(encoding="utf-8"))["decision_adoptions"]))

    def test_superseded_decision_cannot_be_adopted_as_current(self) -> None:
        old_id = self.record()
        new_id = self.record()
        self.assertNotEqual(old_id, new_id)
        completed = run_cli(
            "decision", "adopt", str(self.study), "--record-id", old_id,
            "--by", "Owner", "--scope", "Old decision", "--adoption-evidence", "receipt",
        )
        self.assertEqual(2, completed.returncode)
        self.assertIn("superseded", json.loads(completed.stdout)["reason"])
        self.assertNotIn("decision_adoptions", json.loads(self.reasoning_path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
