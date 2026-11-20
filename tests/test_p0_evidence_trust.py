#!/usr/bin/env python3
"""P0-A: a formal deliverable needs usable evidence, not just a study folder.

Review 2026-11-20: zero corpus, an unreadable reviewed source, or a store with
no decision-grade (E1+) record must stop formal delivery. The only honest
artifact in that state is an evidence-gap note that says it is not a
conclusion; a conclusion-shaped report must never be written.
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


class EvidenceDeliveryGateTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.study = Path(tmp.name) / "study"
        init = run_cli("init", str(self.study), "--study-id", "gate",
                       "--title", "证据门", "--decision", "是否上线")
        self.assertEqual(0, init.returncode, init.stdout + init.stderr)

    @property
    def evidence(self) -> Path:
        return self.study / "02-data" / "evidence.jsonl"

    def write_evidence(self, *records: dict) -> None:
        self.evidence.parent.mkdir(parents=True, exist_ok=True)
        self.evidence.write_text(
            "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
            encoding="utf-8")

    def deliver(self, kind: str = "report") -> tuple[subprocess.CompletedProcess, dict]:
        done = run_cli("deliver", str(self.study), "--kind", kind)
        return done, json.loads(done.stdout)

    def assert_gap_only(self, payload: dict, reason_code: str) -> None:
        self.assertEqual("blocked", payload["status"])
        self.assertEqual(reason_code, payload["reason_code"])
        gap = (self.study / "06-report" / "evidence-gap.md").read_text(encoding="utf-8")
        self.assertIn("证据缺口说明（不是结论）", gap)
        self.assertIn(reason_code, gap)
        self.assertNotIn("产品与商业推理主链", gap)
        self.assertFalse((self.study / "06-report" / "report.md").exists())

    def test_zero_corpus_blocks_formal_delivery(self) -> None:
        done, payload = self.deliver()
        self.assertEqual(1, done.returncode, done.stdout + done.stderr)
        self.assert_gap_only(payload, "EVIDENCE_EMPTY")
        self.assertEqual(0, payload["evidence_count"])
        self.assertEqual(str((self.study / "06-report" / "evidence-gap.md").resolve()),
                         str(Path(payload["gap_path"]).resolve()))

    def test_only_e0_records_block_formal_delivery(self) -> None:
        self.write_evidence(
            {"record_id": "R01", "evidence_level": "E0",
             "text": "短", "source_ref": "https://example.com/thread/1"},
            {"record_id": "R02", "evidence_level": "E0",
             "text": "另一条只有自述没有可核对来源的短句",
             "source_ref": "https://example.com/thread/2"},
        )
        done, payload = self.deliver("decision")
        self.assertEqual(1, done.returncode, done.stdout + done.stderr)
        self.assert_gap_only(payload, "EVIDENCE_UNQUALIFIED")
        self.assertEqual({"E0": 2}, payload["level_counts"])
        self.assertEqual(0, payload["gate"]["decision_grade_count"])

    def test_unreadable_reviewed_source_blocks_formal_delivery(self) -> None:
        self.write_evidence(
            {"record_id": "R01", "evidence_level": "E1",
             "text": "移动巡检能先判断再叫我起床，我愿意试用。",
             "source_ref": "01-sources/captures/missing.json"},
        )
        done, payload = self.deliver()
        self.assertEqual(1, done.returncode, done.stdout + done.stderr)
        self.assert_gap_only(payload, "EVIDENCE_SOURCE_UNREADABLE")
        self.assertEqual("R01", payload["gate"]["unreadable_sources"][0]["record_id"])
        self.assertEqual("missing", payload["gate"]["unreadable_sources"][0]["problem"])

    def test_qualified_evidence_still_delivers(self) -> None:
        self.write_evidence(
            {"record_id": "R01", "evidence_level": "E1",
             "text": "移动巡检能先判断再叫我起床，我愿意试用。",
             "source_ref": "https://example.com/thread/1"},
        )
        done, payload = self.deliver()
        self.assertEqual(0, done.returncode, done.stdout + done.stderr)
        self.assertEqual("written", payload["status"])
        self.assertTrue((self.study / "06-report" / "report.md").is_file())
        self.assertFalse((self.study / "06-report" / "evidence-gap.md").exists())


if __name__ == "__main__":
    unittest.main()
