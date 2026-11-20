#!/usr/bin/env python3
"""P0-B: a CSV row cannot award itself an evidence level.

Review 2026-11-20: `askovo import` validated and capped the command-level
`--evidence-level`, but a row-level `evidence_level` column went straight into
evidence.jsonl. A pasted self-report could therefore claim E5 and satisfy a
gate that is supposed to need transaction records. The rule now matches the
command-level one: the declared level is capped by the evidence form (the
stricter of the row form and the command form), and an unknown level rejects
the file instead of being stored verbatim.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/askovo/scripts/askovo.py"


def run_cli(*args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run([sys.executable, str(CLI), *args],
                          check=False, capture_output=True, text=True,
                          timeout=180, env=env)


class ImportLevelDerivationTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.study = self.root / "study"
        init = run_cli("init", str(self.study), "--study-id", "levels",
                       "--title", "等级推导", "--decision", "是否采购")
        self.assertEqual(0, init.returncode, init.stdout + init.stderr)

    @property
    def evidence(self) -> Path:
        return self.study / "02-data" / "evidence.jsonl"

    def import_csv(self, body: str, *extra: str) -> subprocess.CompletedProcess:
        path = self.root / "rows.csv"
        path.write_text(body, encoding="utf-8")
        return run_cli("import", str(self.study), str(path),
                       "--source-family", "interview", "--claim-type", "need",
                       "--method-id", "discovery-interview",
                       "--context-key", "procurement", *extra)

    def rows(self) -> list[dict]:
        if not self.evidence.is_file():
            return []
        return [json.loads(line) for line in
                self.evidence.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_unknown_level_rejects_the_whole_file(self) -> None:
        done = self.import_csv("record_id,text,evidence_level\nX1,边角清洁不到位,E9\n")
        self.assertEqual(1, done.returncode, done.stdout + done.stderr)
        payload = json.loads(done.stdout)
        self.assertEqual("error", payload["status"])
        self.assertEqual("INVALID_INPUT", payload["reason_code"])
        self.assertIn("E4+", payload["suggestion"])
        self.assertEqual([], self.rows())

    def test_declared_high_level_is_capped_by_the_form(self) -> None:
        done = self.import_csv(
            "record_id,text,evidence_level\nX1,已经续费三次,E5\n")
        self.assertEqual(0, done.returncode, done.stdout + done.stderr)
        row = self.rows()[0]
        self.assertEqual("E2", row["evidence_level"])
        self.assertEqual("E5", row["level_declared"])
        self.assertIn("capped", row["level_basis"])

    def test_row_form_cannot_raise_the_command_cap(self) -> None:
        done = self.import_csv(
            "record_id,text,evidence_level,evidence_form\nX1,口头说会买,E5,transaction\n")
        self.assertEqual(0, done.returncode, done.stdout + done.stderr)
        row = self.rows()[0]
        self.assertEqual("E2", row["evidence_level"])
        self.assertIn("cap=E2", row["level_basis"])

    def test_transaction_form_allows_e5(self) -> None:
        done = self.import_csv(
            "record_id,text,evidence_level,counterparty,occurred_at,amount,"
            "source_ref,evidence_ref\n"
            "X1,发票号 2026-0031,E5,Acme Cloud,2026-11-03,3980.00,"
            "erp-export-202611,INV-2026-0031\n",
            "--evidence-form", "transaction")
        self.assertEqual(0, done.returncode, done.stdout + done.stderr)
        row = self.rows()[0]
        self.assertEqual("E5", row["evidence_level"])
        self.assertEqual("E5", row["level_declared"])
        self.assertEqual("E5", row["requested_evidence_level"])
        self.assertEqual("askovo-import-derivation/2", row["level_derivation_version"])

    def test_transaction_form_without_structure_is_held_at_e2(self) -> None:
        """Declaring --evidence-form transaction does not make text a transaction."""
        done = self.import_csv(
            "record_id,text,evidence_level\nX1,发票号 2026-0031,E5\n",
            "--evidence-form", "transaction")
        self.assertEqual(0, done.returncode, done.stdout + done.stderr)
        row = self.rows()[0]
        self.assertEqual("E2", row["evidence_level"])
        self.assertEqual("E5", row["level_declared"])
        self.assertIn("transaction structure incomplete", row["level_basis"])
        for field in ("counterparty", "occurred_at", "amount", "source_ref",
                      "evidence_ref"):
            self.assertIn(field, row["level_basis"])

    def test_plain_text_cannot_claim_e5_by_form_alone(self) -> None:
        done = self.import_csv(
            "record_id,text,evidence_level\nX1,发票号 2026-0031,E5\n",
            "--evidence-form", "transaction", "--evidence-level", "E5")
        self.assertEqual(0, done.returncode, done.stdout + done.stderr)
        payload = json.loads(done.stdout)
        self.assertEqual(1, payload["review"]["structure_downgrades"])
        self.assertEqual("E2", payload["review"]["evidence_level"])
        self.assertEqual("E5", payload["review"]["requested_level"])
        self.assertEqual("E2", self.rows()[0]["evidence_level"])

    def test_each_missing_transaction_field_downgrades(self) -> None:
        done = self.import_csv(
            "record_id,text,evidence_level,counterparty,occurred_at,amount\n"
            "X1,发票号 2026-0031,E5,Acme Cloud,2026-11-03,3980.00\n",
            "--evidence-form", "transaction")
        self.assertEqual(0, done.returncode, done.stdout + done.stderr)
        row = self.rows()[0]
        self.assertEqual("E2", row["evidence_level"])
        self.assertIn("source_ref, evidence_ref", row["level_basis"])
        self.assertNotIn("counterparty", row["level_basis"])

    def test_mixed_rows_keep_per_row_levels(self) -> None:
        done = self.import_csv(
            "record_id,text,evidence_level,counterparty,occurred_at,amount,"
            "source_ref,evidence_ref\n"
            "X1,发票号 2026-0031,E5,Acme Cloud,2026-11-03,3980.00,"
            "erp-export-202611,INV-2026-0031\n"
            "X2,供应商口头说会开票,E5,,,,,\n",
            "--evidence-form", "transaction")
        self.assertEqual(0, done.returncode, done.stdout + done.stderr)
        rows = {row["record_id"]: row for row in self.rows()}
        self.assertEqual("E5", rows["X1"]["evidence_level"])
        self.assertEqual("E2", rows["X2"]["evidence_level"])
        payload = json.loads(done.stdout)
        self.assertEqual("E5", payload["review"]["evidence_level"])
        self.assertEqual(1, payload["review"]["structure_downgrades"])


if __name__ == "__main__":
    unittest.main()
