from __future__ import annotations

import csv
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
MCP_SERVER = ROOT / "skills/askovo/scripts/askovo_mcp.py"
SAMPLE = ROOT / "examples/sample-study"
REASONING_RELATIVE = Path("04-findings/product-reasoning.json")
FLOW = ["scene", "user", "pain", "need", "feature", "product", "business"]


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def run_mcp(*requests: dict) -> list[dict]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, str(MCP_SERVER)],
        input="\n".join(json.dumps(request) for request in requests) + "\n",
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    return [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]


def valid_product_reasoning() -> dict:
    def node(
        statement: str,
        rationale: str,
        evidence_ids: list[str],
        **details: object,
    ) -> dict:
        return {
            "statement": statement,
            "rationale": rationale,
            "status": "validated",
            "evidence_ids": evidence_ids,
            "assumptions": ["Synthetic fixture assumption"],
            **details,
        }

    return {
        "schema_version": "2.0",
        "flow": list(FLOW),
        "chains": [
            {
                "id": "PR01",
                "title": "Supervised mobile verification for fixed-camera blind spots",
                "context_key": "synthetic-mobile-check",
                "demand_judgment_id": "D01",
                "status": "decided",
                "confidence": "low",
                "nodes": {
                    "scene": node(
                        "An alert or prolonged absence creates a need to check another room",
                        "The observed alerts define the decision context",
                        ["R01", "R02"],
                        trigger="An unusual-noise alert or two hours without a camera sighting",
                        environment="The owner is away from home",
                        task_context="Inspect the relevant space before deciding whether intervention is needed",
                    ),
                    "user": node(
                        "Remote pet owners whose current cameras leave important blind spots",
                        "The scene records identify the affected user role and state",
                        ["R01", "R02"],
                        role="Remote pet owner",
                        state="Away from home with an unresolved blind spot",
                        decision_role="Pilot user and purchaser",
                    ),
                    "pain": node(
                        "Fixed-camera blind spots delay a safe intervention decision",
                        "Substitute failures and their consequences are directly observed",
                        ["R01", "R02"],
                        current_substitute="Fixed cameras or asking a neighbor",
                        friction_cost="Blind spots, additional installation, or a slow and socially costly neighbor request",
                        consequence="Delayed or unnecessary return home",
                    ),
                    "need": node(
                        "Verify a blind spot without returning home or expanding always-on recording",
                        "The desired outcome follows from the observed pain, not from a feature request",
                        ["R01", "R02"],
                        desired_outcome="Decide whether intervention is needed without an unnecessary return home",
                        constraints=["Session-bounded access", "Explicit privacy controls"],
                        measure="The owner can inspect the blind spot and make an intervention decision",
                    ),
                    "feature": node(
                        "Session-bounded mobile check with explicit privacy controls",
                        "This capability addresses the need while bounding the privacy objection",
                        ["R03"],
                        capability="A supervised mobile inspection with shutter, room, and session controls",
                        acceptance_conditions=["Physical shutter", "Room boundaries", "Visible recording state"],
                        alternatives_considered=["Multiple fixed cameras", "Ask a neighbor"],
                    ),
                    "product": node(
                        "A bounded mobile home-check pilot",
                        "Packaging the accepted capability as a bounded pilot tests realized use without claiming market demand",
                        ["R03", "R04", "R06"],
                        form="Two-week supervised mobile home-check pilot",
                        scope="Synthetic bounded pilot only",
                        non_goals=["Always-on autonomous surveillance", "Market-size estimation"],
                        acceptance_criteria=["Predeclared privacy rejection threshold", "Predeclared retained-use threshold"],
                    ),
                    "business": node(
                        "Run a bounded paid pilot before any subscription or launch decision",
                        "A bounded pilot is the smallest business test of payment and retained use",
                        ["R04", "R06"],
                        market_definition="Synthetic remote pet-owner pilot market",
                        geographies=["Synthetic sample only"],
                        time_window="Synthetic 2026 pilot",
                        included_markets=["Remote pet checking"],
                        excluded_markets=["Professional security"],
                        target_segment="Owners with an important blind spot",
                        segments=[
                            {
                                "id": "SEG01",
                                "criteria": "Owners with a blind spot and no satisfactory neighbor alternative",
                                "user_refs": ["PR01.user"],
                                "payer": "Remote pet owner",
                                "evidence_ids": ["R01", "R02"],
                            }
                        ],
                        payer="Remote pet owner",
                        positioning="Privacy-bounded alternative to fixed cameras",
                        revenue_model="Refundable pilot deposit only",
                        pricing_hypothesis="Final price and elasticity unknown",
                        pricing=[
                            {
                                "model": "refundable_pilot_deposit",
                                "amount": None,
                                "currency": "not_asserted",
                                "unit": "pilot",
                                "term": "two weeks",
                                "evidence_type": "paid",
                                "evidence_ids": ["R04"],
                            }
                        ],
                        channels=["Synthetic direct recruitment"],
                        competitive_alternatives=["Fixed cameras", "Neighbor", "Do nothing"],
                        cost_drivers=["Device", "Support"],
                        market_estimates=[
                            {
                                "metric": "TAM",
                                "population_definition": "Not estimated from synthetic records",
                                "time_window": "Synthetic 2026",
                                "unit": "not_estimated",
                                "method": "No market-size claim",
                                "formula": "",
                                "assumptions": ["No market-size claim"],
                                "value": None,
                                "source_ref": "",
                            }
                        ],
                        unit_economics_inputs=[
                            {
                                "metric": "Device and support cost",
                                "value": None,
                                "unit": "unknown",
                                "source_ref": "",
                                "status": "missing",
                            }
                        ],
                        success_metrics=[
                            {
                                "metric_id": "pilot_retention",
                                "definition": "Eligible participants still using the pilot",
                                "numerator": "Active participants",
                                "denominator": "Enrolled participants",
                                "window": "Two weeks",
                                "guardrail": "Privacy rejection threshold",
                            }
                        ],
                        non_goals=["Subscription launch", "Market-size claim"],
                        gate={
                            "stage": "G0",
                            "decision": "Run bounded pilot",
                            "owner": "Synthetic product owner",
                            "resource_commitment": "Synthetic only",
                            "revisit_trigger": "Privacy or retention threshold fails",
                        },
                    ),
                },
                "prioritization": {
                    "method": "Synthetic gate prioritization",
                    "factors": {"consequence": "privacy rejection"},
                    "owner": "Synthetic product owner",
                    "decided_at": "Synthetic date",
                    "rationale": "Test the reversible pilot first",
                },
                "change_log": [
                    {
                        "id": "CHG01",
                        "base_version": "v0",
                        "new_version": "v1",
                        "reason_evidence_ids": ["R05"],
                        "affected_refs": ["PR01.feature"],
                        "impact": "Added privacy control",
                        "decision": "Keep privacy gate",
                        "owner": "Synthetic product owner",
                        "decided_at": "Synthetic date",
                        "projection_sync": "synthetic_only",
                    }
                ],
                "counter_evidence_ids": ["R05", "R07"],
                "alternative_explanations": [
                    "Adequate fixed-camera coverage explains non-adoption (R07)",
                    "Privacy rejection rather than an absent verification need explains refusal (R05)",
                ],
                "gaps": ["Synthetic fixture only", "Privacy controls are not tested in real homes"],
                "next_test": "Run a real two-week bounded pilot with predeclared privacy and retained-use thresholds",
            }
        ],
    }


class ProductReasoningTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.target = Path(self._tmp.name) / "sample"
        shutil.copytree(SAMPLE, self.target)

    @property
    def reasoning_path(self) -> Path:
        return self.target / REASONING_RELATIVE

    def write_reasoning(self, data: dict | None = None) -> None:
        self.reasoning_path.parent.mkdir(parents=True, exist_ok=True)
        self.reasoning_path.write_text(
            json.dumps(data or valid_product_reasoning(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def read_study(self) -> dict:
        return json.loads((self.target / "study.json").read_text(encoding="utf-8"))

    def write_study(self, study: dict) -> None:
        (self.target / "study.json").write_text(
            json.dumps(study, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def read_judgments(self) -> list[dict]:
        return json.loads(
            (self.target / "04-findings/demand-judgments.json").read_text(encoding="utf-8")
        )

    def write_judgments(self, judgments: list[dict]) -> None:
        (self.target / "04-findings/demand-judgments.json").write_text(
            json.dumps(judgments, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def assert_product_check(self, payload: dict, expected: str) -> dict:
        check = next(item for item in payload["checks"] if item["id"] == "product_reasoning")
        self.assertEqual(expected, check["status"], json.dumps(payload, ensure_ascii=False))
        return check

    def test_valid_chain_passes_full_check(self) -> None:
        self.write_reasoning()
        completed = run_cli("check", str(self.target), "--stage", "full")
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        payload = json.loads(completed.stdout)
        self.assert_product_check(payload, "pass")
        self.assertEqual(1, payload["metrics"]["product_reasoning"]["chains"])
        self.assertEqual(1, payload["metrics"]["product_reasoning"]["decided"])

    def test_valid_evidence_backed_chain_also_passes_design_check(self) -> None:
        self.write_reasoning()
        completed = run_cli("check", str(self.target), "--stage", "design")
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assert_product_check(json.loads(completed.stdout), "pass")

    def test_legacy_study_without_contract_or_file_remains_compatible(self) -> None:
        study = self.read_study()
        study.pop("product_reasoning", None)
        study.pop("product_reasoning_version", None)
        self.write_study(study)
        if self.reasoning_path.exists():
            self.reasoning_path.unlink()

        completed = run_cli("check", str(self.target), "--stage", "full")
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        check = self.assert_product_check(json.loads(completed.stdout), "pass")
        self.assertIn("legacy study", check["detail"])

    def test_configured_study_requires_reasoning_file(self) -> None:
        if self.reasoning_path.exists():
            self.reasoning_path.unlink()
        completed = run_cli("check", str(self.target), "--stage", "full")
        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        check = self.assert_product_check(json.loads(completed.stdout), "fail")
        self.assertIn("missing 04-findings/product-reasoning.json", check["detail"])

    def test_configured_study_requires_a_chain_for_every_judgment(self) -> None:
        data = valid_product_reasoning()
        chain = data["chains"][0]
        chain["demand_judgment_id"] = ""
        chain["context_key"] = ""
        chain["status"] = "draft"
        chain["counter_evidence_ids"] = []
        for node in chain["nodes"].values():
            node["status"] = "hypothesis"
            node["evidence_ids"] = []
        self.write_reasoning(data)

        completed = run_cli("check", str(self.target), "--stage", "full")
        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        check = self.assert_product_check(json.loads(completed.stdout), "fail")
        self.assertIn("demand judgments missing a product chain: D01", check["detail"])

    def test_missing_rationale_fails_even_with_valid_evidence(self) -> None:
        data = valid_product_reasoning()
        data["chains"][0]["nodes"]["need"]["rationale"] = ""
        self.write_reasoning(data)

        completed = run_cli("check", str(self.target), "--stage", "full")
        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        check = self.assert_product_check(json.loads(completed.stdout), "fail")
        self.assertIn("PR01.need missing rationale", check["detail"])

    def test_orphan_chain_cannot_cite_evidence(self) -> None:
        data = valid_product_reasoning()
        data["chains"][0]["demand_judgment_id"] = "D404"
        self.write_reasoning(data)

        completed = run_cli("check", str(self.target), "--stage", "full")
        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        check = self.assert_product_check(json.loads(completed.stdout), "fail")
        self.assertIn("must link an existing demand_judgment_id", check["detail"])

    def test_unknown_evidence_id_fails(self) -> None:
        data = valid_product_reasoning()
        data["chains"][0]["nodes"]["user"]["evidence_ids"].append("R404")
        self.write_reasoning(data)

        completed = run_cli("check", str(self.target), "--stage", "full")
        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        check = self.assert_product_check(json.loads(completed.stdout), "fail")
        self.assertIn("references unknown evidence: R404", check["detail"])

    def test_node_evidence_must_be_registered_for_that_node_in_linked_judgment(self) -> None:
        data = valid_product_reasoning()
        data["chains"][0]["nodes"]["feature"]["evidence_ids"] = ["R01", "R03"]
        self.write_reasoning(data)

        completed = run_cli("check", str(self.target), "--stage", "full")
        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        check = self.assert_product_check(json.loads(completed.stdout), "fail")
        self.assertIn("PR01.feature evidence is not registered", check["detail"])
        self.assertIn("R01", check["detail"])

    def test_decided_chain_cannot_bypass_commercial_evidence_gate(self) -> None:
        self.write_reasoning()
        judgments = self.read_judgments()
        judgments[0]["commercial_evidence_ids"] = []
        self.write_judgments(judgments)

        checked = run_cli("check", str(self.target), "--stage", "full")
        self.assertEqual(1, checked.returncode, checked.stdout + checked.stderr)
        self.assertIn("lacks commercial evidence", checked.stdout)

        audited = run_cli("audit", str(self.target), "--json")
        self.assertEqual(1, audited.returncode, audited.stdout + audited.stderr)
        payload = json.loads(audited.stdout)
        self.assertEqual("exceeds_evidence", payload["claims"][0]["verdict"])
        self.assertTrue(any("commercial" in reason for reason in payload["claims"][0]["reasons"]))

    def test_decided_requires_all_validated_nodes_and_counter_evidence(self) -> None:
        cases = ("non_validated_node", "missing_counter", "missing_alternative")
        for case in cases:
            with self.subTest(case=case):
                data = valid_product_reasoning()
                if case == "non_validated_node":
                    data["chains"][0]["nodes"]["feature"]["status"] = "needs-validation"
                    expected = "decided has non-validated nodes: feature"
                elif case == "missing_counter":
                    data["chains"][0]["counter_evidence_ids"] = []
                    expected = "decided lacks counter-evidence"
                else:
                    data["chains"][0]["alternative_explanations"] = []
                    expected = "decided requires at least one alternative explanation"
                self.write_reasoning(data)
                completed = run_cli("check", str(self.target), "--stage", "full")
                self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
                check = self.assert_product_check(json.loads(completed.stdout), "fail")
                self.assertIn(expected, check["detail"])

    def test_chain_and_prd_render_the_seven_node_spine(self) -> None:
        self.write_reasoning()
        chained = run_cli("chain", str(self.target))
        self.assertEqual(0, chained.returncode, chained.stdout + chained.stderr)
        chain_payload = json.loads(chained.stdout)
        self.assertEqual("exists", chain_payload["status"])
        self.assertEqual(FLOW, chain_payload["flow"])

        chain_report = (self.target / "06-report/product-reasoning.md").read_text(encoding="utf-8")
        markers = [f"| **{label}** |" for label in ("场景", "用户", "痛点", "需求", "特性", "产品", "商业")]
        positions = [chain_report.index(marker) for marker in markers]
        self.assertEqual(sorted(positions), positions)
        self.assertIn("PR01", chain_report)
        self.assertIn("D01", chain_report)
        self.assertIn("R01", chain_report)
        self.assertIn("R05", chain_report)
        self.assertIn("not from a feature request", chain_report)

        delivered = run_cli("deliver", str(self.target), "--kind", "prd")
        self.assertEqual(0, delivered.returncode, delivered.stdout + delivered.stderr)
        prd = (self.target / "06-report/prd.md").read_text(encoding="utf-8")
        self.assertIn("## 1. 产品与商业推理主链", prd)
        self.assertIn("PR01", prd)
        self.assertIn("产品非目标", prd)
        self.assertIn("产品验收", prd)
        prd_positions = [prd.index(marker) for marker in markers]
        self.assertEqual(sorted(prd_positions), prd_positions)

    def test_mcp_chain_uses_the_same_renderer_contract(self) -> None:
        self.write_reasoning()
        responses = run_mcp(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "askovo_chain",
                    "arguments": {"study_dir": str(self.target)},
                },
            }
        )
        content = responses[0]["result"]["content"]
        payload = json.loads(content[0]["text"])
        self.assertEqual(0, payload["exit_code"], json.dumps(payload, ensure_ascii=False))
        self.assertEqual(FLOW, payload["result"]["flow"])
        self.assertEqual(1, payload["result"]["summary"]["chains"])
        self.assertTrue((self.target / "06-report/product-reasoning.md").is_file())

    def test_import_preserves_context_key_without_inventing_one(self) -> None:
        source = Path(self._tmp.name) / "context-import.jsonl"
        source.write_text(
            json.dumps({"record_id": "IMP01", "context_key": "imported-context", "text": "synthetic one"})
            + "\n"
            + json.dumps({"record_id": "IMP02", "text": "synthetic two"})
            + "\n",
            encoding="utf-8",
        )
        completed = run_cli(
            "import",
            str(self.target),
            str(source),
            "--source-family",
            "interview",
        )
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        records = [
            json.loads(line)
            for line in (self.target / "02-data/evidence.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ]
        by_id = {record["record_id"]: record for record in records}
        self.assertEqual("imported-context", by_id["IMP01"]["context_key"])
        self.assertEqual("", by_id["IMP02"]["context_key"])
        self.assertNotEqual(self.read_study()["study_id"], by_id["IMP02"]["context_key"])

    def test_supporting_states_require_their_own_references(self) -> None:
        cases = (
            ("delivery", "release-ready", "release_plan_ref"),
            ("outcome", "positive-observed", "metric_refs"),
            ("causal", "supported", "experiment_refs"),
        )
        for state_name, status, reference_field in cases:
            with self.subTest(state=state_name):
                data = json.loads(self.reasoning_path.read_text(encoding="utf-8"))
                states = data["chains"][0]["supporting_states"][state_name]
                states["status"] = status
                states[reference_field] = [] if reference_field.endswith("_refs") else ""
                self.write_reasoning(data)
                completed = run_cli("check", str(self.target), "--stage", "full")
                self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
                check = self.assert_product_check(json.loads(completed.stdout), "fail")
                self.assertIn(reference_field, check["detail"])

    def test_supporting_states_are_exposed_without_becoming_demand_proof(self) -> None:
        audited = run_cli("audit", str(self.target), "--json")
        self.assertEqual(0, audited.returncode, audited.stdout + audited.stderr)
        payload = json.loads(audited.stdout)
        states = payload["product_reasoning"]["supporting_states"]
        self.assertEqual({"unplanned": 1}, states["delivery"])
        self.assertEqual({"observing": 1}, states["outcome"])
        self.assertEqual({"not-claimed": 1}, states["causal"])
        self.assertEqual(1, payload["summary"]["decided_product_chains"])

    def test_ops_and_tracker_use_the_same_chain_and_generate_rows(self) -> None:
        ops = run_cli("deliver", str(self.target), "--kind", "ops")
        self.assertEqual(0, ops.returncode, ops.stdout + ops.stderr)
        ops_text = (self.target / "06-report/user-ops.md").read_text(encoding="utf-8")
        self.assertIn("用户运营投影", ops_text)
        self.assertIn("PR01", ops_text)
        self.assertIn("反馈进入同一", ops_text)
        self.assertIn("不能用评论记录数代替", ops_text)

        tracked = run_cli("deliver", str(self.target), "--kind", "tracker")
        self.assertEqual(0, tracked.returncode, tracked.stdout + tracked.stderr)
        with (self.target / "06-report/postlaunch-tracker.csv").open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertGreater(len(rows), 1)
        self.assertEqual({"PR01"}, {row["chain_id"] for row in rows})
        self.assertEqual({"decided"}, {row["status"] for row in rows})
        self.assertEqual({"unplanned"}, {row["delivery_status"] for row in rows})
        self.assertEqual({"observing"}, {row["outcome_status"] for row in rows})
        self.assertEqual({"not-claimed"}, {row["causal_status"] for row in rows})
        self.assertIn("business", {row["node_id"] for row in rows})
        business_rows = [row for row in rows if row["node_id"] == "business"]
        self.assertEqual({"pilot_retained_use"}, {row["metric"] for row in business_rows})
        self.assertTrue(all(row["metric"] and row["next_action"] for row in rows))

    def test_product_and_research_reports_have_distinct_writers(self) -> None:
        product = run_cli("deliver", str(self.target), "--kind", "report")
        self.assertEqual(0, product.returncode, product.stdout + product.stderr)
        research = run_cli("report", str(self.target))
        self.assertEqual(0, research.returncode, research.stdout + research.stderr)
        product_text = (self.target / "06-report/report.md").read_text(encoding="utf-8")
        research_text = (self.target / "06-report/research-status.md").read_text(encoding="utf-8")
        self.assertIn("产品推理报告", product_text)
        self.assertIn("PR01", product_text)
        self.assertIn("调研报告", research_text)
        self.assertIn("产品与商业推理主链", research_text)
        self.assertNotEqual(product_text, research_text)

    def test_business_node_cannot_be_validated_without_commercial_evidence(self) -> None:
        data = json.loads(self.reasoning_path.read_text(encoding="utf-8"))
        data["chains"][0]["nodes"]["business"]["evidence_ids"] = []
        self.write_reasoning(data)
        completed = run_cli("check", str(self.target), "--stage", "full")
        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        check = self.assert_product_check(json.loads(completed.stdout), "fail")
        self.assertIn("PR01.business validated lacks direct evidence at E4+, E5", check["detail"])

    def test_business_gate_requires_market_scope_and_segments(self) -> None:
        data = json.loads(self.reasoning_path.read_text(encoding="utf-8"))
        business = data["chains"][0]["nodes"]["business"]
        business["geographies"] = []
        business["segments"] = []
        business["pricing"] = []
        self.write_reasoning(data)
        completed = run_cli("check", str(self.target), "--stage", "full")
        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        detail = self.assert_product_check(json.loads(completed.stdout), "fail")["detail"]
        for field in ("geographies", "segments", "pricing"):
            self.assertIn(field, detail)

    def test_market_estimate_with_a_value_needs_denominator_and_source(self) -> None:
        data = json.loads(self.reasoning_path.read_text(encoding="utf-8"))
        estimate = data["chains"][0]["nodes"]["business"]["market_estimates"][0]
        estimate["value"] = 100
        estimate["source_ref"] = ""
        estimate["formula"] = ""
        self.write_reasoning(data)
        completed = run_cli("check", str(self.target), "--stage", "full")
        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        detail = self.assert_product_check(json.loads(completed.stdout), "fail")["detail"]
        self.assertIn("with a value requires source_ref", detail)
        self.assertIn("with a value requires formula", detail)

    def test_mrd_brd_are_projections_of_the_same_business_node(self) -> None:
        mrd = run_cli("deliver", str(self.target), "--kind", "mrd")
        brd = run_cli("deliver", str(self.target), "--kind", "brd")
        self.assertEqual(0, mrd.returncode, mrd.stdout + mrd.stderr)
        self.assertEqual(0, brd.returncode, brd.stdout + brd.stderr)
        mrd_text = (self.target / "06-report/mrd.md").read_text(encoding="utf-8")
        brd_text = (self.target / "06-report/brd.md").read_text(encoding="utf-8")
        self.assertIn("# MRD 市场需求文档", mrd_text)
        self.assertIn("## 2. MRD 市场研究与分析", mrd_text)
        self.assertIn("市场定义", mrd_text)
        self.assertIn("市场估计口径", mrd_text)
        self.assertIn("不证明用户需求", mrd_text)
        self.assertIn("# BRD 商业需求文档", brd_text)
        self.assertIn("## 2. BRD 商业决策", brd_text)
        self.assertIn("G0", brd_text)
        self.assertIn("Run a bounded pilot", brd_text)
        self.assertIn("市场规模必须有独立抽样框", brd_text)
        self.assertNotEqual(mrd_text, brd_text)

    def test_legacy_six_node_chain_remains_readable(self) -> None:
        data = json.loads(self.reasoning_path.read_text(encoding="utf-8"))
        data["schema_version"] = "1.0"
        data["flow"] = ["scene", "user", "pain", "need", "feature", "product"]
        data["chains"][0]["nodes"].pop("business")
        data["chains"][0].pop("prioritization", None)
        data["chains"][0].pop("change_log", None)
        self.write_reasoning(data)
        study = self.read_study()
        study["product_reasoning_version"] = "1.0"
        study["product_reasoning"]["flow"] = data["flow"]
        self.write_study(study)
        completed = run_cli("check", str(self.target), "--stage", "full")
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assert_product_check(json.loads(completed.stdout), "pass")

    def test_bundled_sample_contains_and_passes_the_canonical_chain(self) -> None:
        sample_reasoning = SAMPLE / REASONING_RELATIVE
        self.assertTrue(
            sample_reasoning.is_file(),
            "examples/sample-study/04-findings/product-reasoning.json has not been added yet",
        )
        data = json.loads(sample_reasoning.read_text(encoding="utf-8"))
        self.assertEqual(FLOW, data["flow"])
        self.assertEqual(1, len(data["chains"]))
        chain = data["chains"][0]
        self.assertEqual("PR01", chain["id"])
        self.assertEqual("D01", chain["demand_judgment_id"])
        cited = set(chain["counter_evidence_ids"])
        for node in chain["nodes"].values():
            cited.update(node["evidence_ids"])
        self.assertEqual({f"R{index:02d}" for index in range(1, 8)}, cited)

        completed = run_cli("check", str(self.target), "--stage", "full")
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assert_product_check(json.loads(completed.stdout), "pass")


if __name__ == "__main__":
    unittest.main()
