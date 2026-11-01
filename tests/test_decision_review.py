#!/usr/bin/env python3
"""Decision review: mechanical quality items over one study's decision state."""
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
MCP_SERVER = ROOT / "skills/askovo/scripts/askovo_mcp.py"
SAMPLE = ROOT / "examples/sample-study"


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(CLI), *args],
                          capture_output=True, text=True, timeout=180)


class DecisionReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.study = self.dir / "study"
        shutil.copytree(SAMPLE, self.study)

    def test_review_writes_json_and_markdown(self) -> None:
        completed = run_cli("review", str(self.study), "--json")
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual("askovo.decision-review", payload["kind"])
        self.assertIn(payload["status"], {"pass", "needs_work", "fail"})
        self.assertEqual(set(payload["dimensions"]), {"audit", "evidence", "decision",
                                                      "falsifiability", "bias", "deliverables"})
        self.assertTrue(Path(payload["json_path"]).is_file())
        markdown = Path(payload["markdown_path"]).read_text(encoding="utf-8")
        self.assertIn("## 边界", markdown)
        self.assertIn("不通过", markdown)

    def test_review_needs_work_without_deliverables(self) -> None:
        completed = run_cli("review", str(self.study), "--json")
        payload = json.loads(completed.stdout)
        deliverable_items = payload["dimensions"]["deliverables"]
        self.assertTrue(any(item["id"] == "reports" and item["status"] == "warn"
                            for item in deliverable_items))

    def test_review_passes_after_decision_package(self) -> None:
        delivered = run_cli("deliver", str(self.study), "--kind", "decision")
        self.assertEqual(0, delivered.returncode, delivered.stdout + delivered.stderr)
        completed = run_cli("review", str(self.study), "--json")
        self.assertEqual(0, completed.returncode, completed.stdout)
        payload = json.loads(completed.stdout)
        report_items = [item for item in payload["dimensions"]["deliverables"]
                        if item["id"].startswith("report:")]
        self.assertTrue(report_items)
        self.assertTrue(all(item["status"] == "pass" for item in report_items),
                        json.dumps(report_items, ensure_ascii=False))

    def test_review_fails_on_an_overclaim(self) -> None:
        judgments_path = self.study / "04-findings" / "demand-judgments.json"
        judgments = json.loads(judgments_path.read_text(encoding="utf-8"))
        judgments.append({
            "id": "D02",
            "context_key": "synthetic-mobile-check",
            "title": "Owners will pay for continuous monitoring",
            "user_role": "Remote pet owners",
            "scene": "Away from home",
            "task": "Watch the pet",
            "current_substitute": "Fixed cameras",
            "friction": "Blind spots",
            "consequence": "Missed events",
            "solution": "Continuous monitoring",
            "acceptance_conditions": "Always on",
            "problem_evidence_ids": ["R01"],
            "solution_evidence_ids": [],
            "commercial_evidence_ids": [],
            "counter_evidence_ids": [],
            "status": "validated",
            "confidence": "high",
            "gaps": [],
            "next_test": "None",
        })
        judgments_path.write_text(json.dumps(judgments, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        completed = run_cli("review", str(self.study), "--json")
        self.assertEqual(1, completed.returncode, completed.stdout)
        payload = json.loads(completed.stdout)
        self.assertEqual("fail", payload["status"])
        claim_items = [item for item in payload["dimensions"]["evidence"]
                       if item["id"] == "claim:D02"]
        self.assertEqual("fail", claim_items[0]["status"])

    def test_analysis_adds_segments_and_time_coverage(self) -> None:
        analyzed = run_cli("analyze", str(self.study))
        self.assertEqual(0, analyzed.returncode, analyzed.stdout + analyzed.stderr)
        analysis = json.loads((self.study / "04-findings" / "analysis.json").read_text(encoding="utf-8"))
        self.assertIn("segments", analysis)
        self.assertIn("corpus_role", analysis["segments"])
        self.assertIn("time_coverage", analysis)
        self.assertIn("window", analysis["time_coverage"])
        self.assertIn("by_evidence_level", analysis)
        markdown = (self.study / "04-findings" / "analysis.md").read_text(encoding="utf-8")
        self.assertIn("## 分段（描述性）", markdown)
        self.assertIn("## 时间覆盖", markdown)

    def test_mcp_exposes_review(self) -> None:
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                        "clientInfo": {"name": "test", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "askovo_review",
                        "arguments": {"study_dir": str(self.study), "json": True}}},
        ]
        lines = "\n".join(json.dumps(request) for request in requests) + "\n"
        completed = subprocess.run([sys.executable, str(MCP_SERVER)], input=lines,
                                   check=False, capture_output=True, text=True, timeout=180)
        responses = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
        by_id = {response.get("id"): response for response in responses}
        names = {tool["name"] for tool in by_id[2]["result"]["tools"]}
        self.assertIn("askovo_review", names)
        payload = json.loads(by_id[3]["result"]["content"][0]["text"])
        self.assertEqual(0, payload["exit_code"])
        self.assertEqual("askovo.decision-review", payload["result"]["kind"])


if __name__ == "__main__":
    unittest.main()
