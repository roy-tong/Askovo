from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/askovo/scripts/askovo.py"
SAMPLE = ROOT / "examples/sample-study"

sys.path.insert(0, str(ROOT / "skills/askovo/scripts"))
import sure_engine  # noqa: E402


MCP = ROOT / "skills/askovo/scripts/askovo_mcp.py"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        check=False, capture_output=True, text=True, env=env,
    )


def run_mcp(*requests: dict) -> list[dict]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, str(MCP)],
        input="\n".join(json.dumps(request) for request in requests) + "\n",
        check=False, capture_output=True, text=True, timeout=120, env=env,
    )
    return [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]


class OptimizationRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="askovo-opt-"))
        self.study = self.tmp / "study"
        shutil.copytree(SAMPLE, self.study)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _two_chain_reasoning(self) -> None:
        path = self.study / "04-findings/product-reasoning.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        first = data["chains"][0]
        first["status"] = "needs-validation"
        second = json.loads(json.dumps(first))
        second["id"] = "PR02"
        second["title"] = "Second candidate chain"
        second["context_key"] = "synthetic-second"
        second["demand_judgment_id"] = "D02"
        second["nodes"]["business"]["statement"] = "Second chain business conclusion"
        second["prioritization"] = {"rationale": "Second priority rationale"}
        second["next_test"] = "Second chain next test"
        second["failure_condition"] = "Second chain failure line"
        data["chains"] = [first, second]
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def test_plan_renders_every_chain_conclusion_once(self) -> None:
        self._two_chain_reasoning()
        result = run_cli("deliver", str(self.study), "--kind", "plan")
        self.assertEqual(0, result.returncode, result.stderr)
        text = (self.study / "06-report/plan.md").read_text(encoding="utf-8")
        self.assertIn("## 0. 多链结论与推进建议", text)
        self.assertIn("### 结论 · PR01", text)
        self.assertIn("### 结论 · PR02", text)
        self.assertIn("Second priority rationale", text)
        # Detailed node sections are rendered once, not once per chain.
        self.assertEqual(1, text.count("## 2. 目标场景"))

    def test_report_decision_section_is_not_placeholder(self) -> None:
        self._two_chain_reasoning()
        result = run_cli("deliver", str(self.study), "--kind", "report")
        self.assertEqual(0, result.returncode, result.stderr)
        text = (self.study / "06-report/report.md").read_text(encoding="utf-8")
        self.assertNotIn("- 建议（做/不做/调整哪个节点", text)
        self.assertIn("没有任何链达到 `decided`", text)
        self.assertIn("Second priority rationale", text)
        self.assertIn("**替代解释**", text)
        self.assertNotIn("- 缺口（按推理节点和推导关系列）", text)

    def test_analyze_uses_text_excerpt_and_derives_claim_type(self) -> None:
        path = self.study / "02-data/evidence.jsonl"
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        records[0]["text_excerpt"] = "The invoice does not match the usage export at all, so finance cannot close the month."
        path.write_text(
            "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
            encoding="utf-8",
        )
        result = run_cli("analyze", str(self.study), "--question", "invoice usage")
        self.assertEqual(0, result.returncode, result.stderr)
        text = (self.study / "04-findings/analysis.md").read_text(encoding="utf-8")
        self.assertNotIn("平均文本长度：0", text)
        self.assertIn("invoice", text.lower())
        self.assertNotIn("结论类型：{\"未标注\": 7}", text)

    def test_analysis_uses_collection_summary_funnel(self) -> None:
        (self.study / "01-sources/collection-summary.json").write_text(
            json.dumps({"raw_records": 987654, "screened_records": 4321}, ensure_ascii=False),
            encoding="utf-8",
        )
        result = run_cli("deliver", str(self.study), "--kind", "analysis")
        self.assertEqual(0, result.returncode, result.stderr)
        text = (self.study / "06-report/analysis.md").read_text(encoding="utf-8")
        self.assertIn("987654", text)
        self.assertIn("4321", text)

    def test_plan_force_writes_proposal_without_overwriting(self) -> None:
        study_before = (self.study / "study.json").read_bytes()
        plan_before = (self.study / "01-sources/source-plan.csv").read_bytes()
        result = run_cli(
            "plan", str(self.study), "--goal", "Synthetic retrofit", "--region", "overseas",
            "--sample-size", "100000", "--platform-types", "forum,social", "--force",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"status": "proposed"', result.stdout)
        self.assertEqual(study_before, (self.study / "study.json").read_bytes())
        self.assertEqual(plan_before, (self.study / "01-sources/source-plan.csv").read_bytes())
        proposal = self.study / "01-sources/plan-proposal/plan-proposal.json"
        self.assertTrue(proposal.is_file())
        self.assertTrue((self.study / "01-sources/plan-proposal/source-plan.proposed.csv").is_file())
        self.assertTrue((self.study / "01-sources/plan-proposal/tasks.proposed.md").is_file())

    def test_plan_refuses_existing_without_force(self) -> None:
        result = run_cli(
            "plan", str(self.study), "--goal", "x", "--region", "overseas",
            "--sample-size", "1000", "--platform-types", "forum",
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("refusing to overwrite non-empty directory", result.stderr)

    def test_plan_force_requires_study_json(self) -> None:
        other = self.tmp / "plain-dir"
        other.mkdir()
        (other / "notes.txt").write_text("not a study", encoding="utf-8")
        result = run_cli(
            "plan", str(other), "--goal", "x", "--region", "overseas",
            "--sample-size", "1000", "--platform-types", "forum", "--force",
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("requires an existing study.json", result.stderr)

    def test_mcp_plan_force_parity(self) -> None:
        study_before = (self.study / "study.json").read_bytes()
        responses = run_mcp({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "askovo_plan", "arguments": {
                "study_dir": str(self.study), "goal": "Synthetic retrofit",
                "region": "overseas", "sample_size": 100000,
                "platform_types": "forum,social", "force": True,
            }},
        })
        payload = json.loads(responses[0]["result"]["content"][0]["text"])
        self.assertEqual(0, payload["exit_code"], json.dumps(payload, ensure_ascii=False))
        self.assertEqual("proposed", payload["result"]["status"])
        self.assertEqual(study_before, (self.study / "study.json").read_bytes())

    def test_mcp_plan_and_report_multi_chain(self) -> None:
        self._two_chain_reasoning()
        deliver = run_mcp({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "askovo_deliver", "arguments": {"study_dir": str(self.study), "kind": "plan"}},
        }, {
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "askovo_deliver", "arguments": {"study_dir": str(self.study), "kind": "report"}},
        })
        self.assertEqual(2, len(deliver))
        plan = (self.study / "06-report/plan.md").read_text(encoding="utf-8")
        self.assertIn("### 结论 · PR02", plan)
        report = (self.study / "06-report/report.md").read_text(encoding="utf-8")
        self.assertIn("没有任何链达到 `decided`", report)
        self.assertIn("**替代解释**", report)

    def test_economics_projection_keeps_boundary(self) -> None:
        result = run_cli("economics", str(self.study))
        self.assertEqual(0, result.returncode, result.stderr)
        text = (self.study / "06-report/unit-economics.md").read_text(encoding="utf-8")
        self.assertIn("## 边界", text)
        self.assertIn("null 表示未知", text)

    def test_source_duplicate_gate_fails(self) -> None:
        path = self.study / "02-data/evidence.jsonl"
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        records[0]["source_url"] = "https://example.test/source"
        records[1]["source_url"] = "https://example.test/source"
        path.write_text(
            "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
            encoding="utf-8",
        )
        result = run_cli("check", str(self.study), "--stage", "full")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("source duplicate rate", result.stdout + result.stderr)

    def test_chain_markdown_keeps_boundary(self) -> None:
        result = run_cli("chain", str(self.study))
        self.assertEqual(0, result.returncode, result.stderr)
        text = (self.study / "06-report/product-reasoning.md").read_text(encoding="utf-8")
        self.assertIn("## 边界", text)
        self.assertIn("不证明", text)

    def test_business_strength_ignores_counter_evidence(self) -> None:
        counter = [
            {"evidence_level": "E2", "source_family": "reddit"},
            {"evidence_level": "E1", "source_family": "hn"},
        ]
        marker, label, _ = sure_engine._plan_strength(counter, "business")
        self.assertEqual("○", marker)
        self.assertIn("商业门未验证", label)
        commercial = [{"evidence_level": "E4+", "source_family": "reddit"}]
        marker, _, _ = sure_engine._plan_strength(commercial, "business")
        self.assertEqual("◐", marker)

    def test_feature_strength_requires_acceptance(self) -> None:
        complaints = [
            {"evidence_level": "E2", "source_family": "reddit"},
            {"evidence_level": "E1", "source_family": "hn"},
        ]
        marker, _, _ = sure_engine._plan_strength(complaints, "feature")
        self.assertEqual("○", marker)
        acceptance = [
            {"evidence_level": "E3", "source_family": "reddit"},
            {"evidence_level": "E3", "source_family": "hn"},
        ]
        marker, _, _ = sure_engine._plan_strength(acceptance, "feature")
        self.assertEqual("●", marker)


if __name__ == "__main__":
    unittest.main()
