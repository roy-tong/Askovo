from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from skills.askovo.scripts import askovo_mcp, research_watch, research_watch_resolution

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "examples/sample-study"
CLI = ROOT / "skills/askovo/scripts/askovo.py"


class ResearchWatchResolutionTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.study = Path(tmp.name) / "study"
        shutil.copytree(SAMPLE, self.study)
        research_watch.create(
            self.study, question="Track demand changes", interval_hours=24,
            owner="research-owner", now="2026-11-25T00:00:00+00:00")

    def test_missing_first_review_requests_local_review_data(self) -> None:
        result = research_watch_resolution.build(self.study, "W001")
        self.assertEqual("ovo.problem-resolution/1", result["schema"])
        self.assertEqual("data_needed", result["requested_resolution"])
        self.assertEqual("local-decision-review", result["data"]["source"])
        self.assertFalse(result["data"]["automatic_fetch_attempted"])
        self.assertEqual("none", result["observation"]["external_effect_status"])

    def test_review_gaps_become_business_decision_not_evidence_mutation(self) -> None:
        research_watch.run_due(self.study, now="2026-11-25T00:00:00+00:00")
        result = research_watch_resolution.build(self.study, "W001")
        self.assertEqual("business_decision", result["requested_resolution"])
        self.assertGreaterEqual(len(result["decision"]["options"]), 2)
        self.assertNotIn("decision_mutated", result)
        self.assertTrue(result["decision"]["evidence_refs"])

    def test_cli_exports_shared_contract(self) -> None:
        result = subprocess.run([
            sys.executable, str(CLI), "watch", "resolution", str(self.study), "W001",
        ], text=True, capture_output=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("data_needed", json.loads(result.stdout)["requested_resolution"])

    def test_mcp_exports_same_contract(self) -> None:
        result = askovo_mcp._run_tool("askovo_research_watch", {
            "action": "resolution", "study_dir": str(self.study), "watch_id": "W001",
        })
        self.assertEqual(0, result["exit_code"], result)
        self.assertEqual("data_needed", result["result"]["requested_resolution"])


if __name__ == "__main__":
    unittest.main()
