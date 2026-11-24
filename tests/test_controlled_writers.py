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


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(CLI), *args], text=True, capture_output=True)


class ControlledWriterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.study = Path(self.tmp.name) / "study"
        shutil.copytree(SAMPLE, self.study)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def reasoning(self):
        return json.loads((self.study / "04-findings/product-reasoning.json").read_text(encoding="utf-8"))

    def test_chain_set_updates_chain_level_fields(self) -> None:
        result = run_cli("chain", str(self.study), "set", "--chain", "PR01", "--field", "context_key", "--value-json", '"after_sales_saas"')
        self.assertEqual(0, result.returncode, result.stderr)
        chain = self.reasoning()["chains"][0]
        self.assertEqual("after_sales_saas", chain["context_key"])
        self.assertEqual({f"PR01.{node}" for node in ("scene", "user", "pain", "need", "feature", "product", "business")}, set(chain["change_log"][-1]["affected_refs"]))

    def test_business_node_accepts_commercial_fields(self) -> None:
        result = run_cli("chain-node", str(self.study), "set", "--node", "business", "--field", "pricing_hypothesis", "--value-json", '{"seat_price":1800,"premium":0.2}')
        self.assertEqual(0, result.returncode, result.stderr)
        business = self.reasoning()["chains"][0]["nodes"]["business"]
        self.assertEqual({"seat_price": 1800, "premium": 0.2}, business["pricing_hypothesis"])

    def test_demand_judgment_create(self) -> None:
        args = (
            "demand-judgment", str(self.study), "create", "--id", "DJ99", "--title", "售后自动分派验证",
            "--user-role", "售后主管", "--scene", "人工录单积压", "--task", "决定是否试点自动分派",
            "--current-substitute", "人工分派", "--friction", "录单慢且易错", "--consequence", "客户等待与返工",
            "--solution", "低摩擦试点", "--acceptance-conditions", "录单率达到70%且续费不下降",
            "--problem-evidence", "R01", "--solution-evidence", "R02", "--counter-evidence", "R03",
            "--context-key", "after_sales_saas", "--next-test", "3家客户4周试点",
        )
        result = run_cli(*args)
        self.assertEqual(0, result.returncode, result.stderr)
        judgments = json.loads((self.study / "04-findings/demand-judgments.json").read_text(encoding="utf-8"))
        created = next(row for row in judgments if row["id"] == "DJ99")
        self.assertEqual(["R01"], created["problem_evidence_ids"])
        self.assertEqual(["R02"], created["solution_evidence_ids"])
        self.assertEqual(["R03"], created["counter_evidence_ids"])
        self.assertEqual("after_sales_saas", created["context_key"])
        duplicate = run_cli(*args)
        self.assertNotEqual(0, duplicate.returncode)

    def test_evidence_set_corrects_form_and_level(self) -> None:
        concept = self.study / "concept-test.json"
        concept.write_text(json.dumps({"stimulus": "自动分派演示", "sample_size": 5, "response_metric": "愿试率", "result": "4/5愿意试点"}), encoding="utf-8")
        result = run_cli("evidence", str(self.study), "set", "R01", "--field", "evidence_form", "--value-json", '"behavior_log"', "--evidence-level", "E3", "--concept-test", str(concept), "--note", "纠正导入默认值")
        self.assertEqual(0, result.returncode, result.stderr)
        rows = [json.loads(line) for line in (self.study / "02-data/evidence.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        first = next(row for row in rows if row["record_id"] == "R01")
        self.assertEqual("behavior_log", first["evidence_form"])
        self.assertEqual("E3", first["evidence_level"])

    def test_study_set_updates_decision_contract(self) -> None:
        result = run_cli("study", str(self.study), "set", "--field", "decision.owner", "--value-json", '"周航"')
        self.assertEqual(0, result.returncode, result.stderr)
        study = json.loads((self.study / "study.json").read_text(encoding="utf-8"))
        self.assertEqual("周航", study["decision"]["owner"])

    def test_e3_requires_concept_test(self) -> None:
        result = run_cli("evidence", str(self.study), "set", "R01", "--field", "evidence_form", "--value-json", '"behavior_log"', "--evidence-level", "E3")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("concept-test", result.stderr)

    def test_demand_judgment_rejects_unknown_evidence(self) -> None:
        result = run_cli(
            "demand-judgment", str(self.study), "create", "--id", "DJ-unknown", "--title", "test",
            "--user-role", "PM", "--scene", "test", "--task", "test", "--current-substitute", "manual",
            "--friction", "slow", "--consequence", "rework", "--solution", "pilot",
            "--acceptance-conditions", "pass", "--problem-evidence", "R999", "--next-test", "retest",
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("R999", result.stderr)

    def test_chain_set_rejects_unknown_field(self) -> None:
        result = run_cli("chain", str(self.study), "set", "--field", "unknown_field", "--value-json", '"x"')
        self.assertNotEqual(0, result.returncode)
        self.assertIn("unknown_field", result.stderr)

    def test_role_workplan_owner_timebox_and_sop_status(self) -> None:
        scaffold = run_cli("roles", "scaffold", str(self.study), "--role", "R09")
        self.assertEqual(0, scaffold.returncode, scaffold.stderr)
        result = run_cli("roles", "workplan-set", str(self.study), "--role", "R09", "--owner", "王珂", "--timebox", "下周", "--start", "2026-11-23", "--end", "2026-11-29", "--step", "R09-S01", "--status", "in_progress")
        self.assertEqual(0, result.returncode, result.stderr)
        plan = json.loads((self.study / "01-sources/role-workbench/workplan.json").read_text(encoding="utf-8"))
        assignment = plan["roles"][0]
        self.assertEqual("王珂", assignment["owner"])
        self.assertEqual({"label": "下周", "start": "2026-11-23", "end": "2026-11-29"}, assignment["timebox"])
        self.assertEqual("in_progress", assignment["sop_status"][0]["work_status"])
        markdown = (self.study / "01-sources/role-workbench/workplan.md").read_text(encoding="utf-8")
        self.assertIn("时间盒：下周", markdown)
        lifecycle = run_cli("deliver", str(self.study), "--kind", "lifecycle")
        self.assertEqual(0, lifecycle.returncode, lifecycle.stderr)

    def test_decision_record_is_projected_into_brd(self) -> None:
        record = run_cli(
            "decision", "record", str(self.study), "--chain", "PR01", "--by", "周航",
            "--decision", "先在3家客户试点4周", "--hypothesis", "H1",
            "--observation", "现有材料支持先做小范围验证", "--evidence", "R01",
            "--revision", "根据当前证据作出的业务判断", "--next-action", "录单率达标后再决定扩量",
        )
        self.assertEqual(0, record.returncode, record.stderr)
        delivered = run_cli("deliver", str(self.study), "--kind", "brd")
        self.assertEqual(0, delivered.returncode, delivered.stderr)
        brd = (self.study / "06-report/brd.md").read_text(encoding="utf-8")
        self.assertIn("DR-PR01-001", brd)
        self.assertIn("周航", brd)
        self.assertIn("录单率达标后再决定扩量", brd)


if __name__ == "__main__":
    unittest.main()
