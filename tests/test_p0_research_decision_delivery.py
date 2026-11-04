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
MCP = ROOT / "skills/askovo/scripts/askovo_mcp.py"
SAMPLE = ROOT / "examples/sample-study"
sys.path.insert(0, str(ROOT / "skills/askovo/scripts"))
import delivery_projection  # noqa: E402
import research_loop  # noqa: E402
import sure_engine  # noqa: E402


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        check=False, capture_output=True, text=True, timeout=120, env=env,
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


def tool_payload(response: dict) -> dict:
    return json.loads(response["result"]["content"][0]["text"])


class StudyCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="askovo-p0-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.study = self.tmp / "study"
        shutil.copytree(SAMPLE, self.study)

    @property
    def reasoning_path(self) -> Path:
        return self.study / "04-findings/product-reasoning.json"

    def read_reasoning(self) -> dict:
        return json.loads(self.reasoning_path.read_text(encoding="utf-8"))

    def write_reasoning(self, data: dict) -> None:
        self.reasoning_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class ResearchActionTests(StudyCase):
    def test_unwritten_gap_compares_five_candidates_without_becoming_executable(self) -> None:
        study = json.loads((self.study / "study.json").read_text(encoding="utf-8"))
        gap = {
            "key": "node:PR01.need:write",
            "kind": "unwritten_node",
            "intent": "problem",
            "actionable": False,
            "detail": "Need is still a placeholder",
        }
        candidates = research_loop.research_action_candidates(
            gap, study, [{"platform": "reddit", "mode": "fixture"}]
        )
        self.assertEqual(set(research_loop.RESEARCH_ACTION_KINDS), {item["action"] for item in candidates})
        self.assertEqual("analyze", candidates[0]["action"])
        self.assertTrue(all(item["candidate_only"] for item in candidates))
        self.assertFalse(next(item for item in candidates if item["action"] == "collect")["executable_by_existing_loop"])
        self.assertTrue(all(item["validated_status_changed"] is False for item in candidates))
        self.assertFalse(gap["actionable"])

    def test_stop_uses_independent_gate_and_does_not_stop_for_its_own_sake(self) -> None:
        study = json.loads((self.study / "study.json").read_text(encoding="utf-8"))
        gap = {"key": "claim:D01:decision", "kind": "claim_needs_decision",
               "intent": "problem", "actionable": False, "detail": "Decision remains"}
        candidates = research_loop.research_action_candidates(gap, study, [])
        stop = next(item for item in candidates if item["action"] == "stop")
        self.assertEqual("stop", candidates[-1]["action"])
        self.assertIsNone(stop["priority_score"])
        self.assertFalse(stop["stop_decision"]["should_stop"])
        self.assertEqual("independent_gate_not_a_positive_utility_score",
                         stop["stop_decision"]["scoring"])
        self.assertTrue(stop["stop_decision"]["blocking_reasons"])

    def test_stop_wins_when_all_three_declared_criteria_are_met(self) -> None:
        study = json.loads((self.study / "study.json").read_text(encoding="utf-8"))
        study["decision"]["stop_decision"] = {
            "criteria": {
                "evidence_sufficient_for_decision": True,
                "remaining_unknowns_can_change_decision": False,
                "continued_research_marginal_value_not_worth_cost_or_risk": True,
            },
            "basis": {
                "evidence_sufficient_for_decision": {"rationale": "Declared decision minimum is present"},
                "remaining_unknowns_can_change_decision": {"rationale": "Remaining items are post-decision metrics"},
                "continued_research_marginal_value_not_worth_cost_or_risk": {
                    "rationale": "No remaining decision-changing question justifies more research cost",
                    "restart_condition": "A new decision-critical contradiction arrives",
                },
            },
        }
        gap = {"key": "claim:D01:decision", "kind": "claim_needs_decision",
               "intent": "problem", "actionable": False, "detail": "Decision remains"}
        candidates = research_loop.research_action_candidates(gap, study, [])
        self.assertEqual("stop", candidates[0]["action"])
        decision = candidates[0]["stop_decision"]
        self.assertTrue(decision["should_stop"])
        self.assertEqual("highest", decision["priority"])
        self.assertIsNone(candidates[0]["priority_score"])
        self.assertIn("new decision-critical contradiction",
                      decision["criteria"]["continued_research_marginal_value_not_worth_cost_or_risk"]["restart_condition"])

    def test_public_commercial_gap_prefers_real_offer_experiment_over_collection(self) -> None:
        study = json.loads((self.study / "study.json").read_text(encoding="utf-8"))
        gap = {
            "key": "node:PR01.business:commercial",
            "kind": "node_without_evidence",
            "intent": "commercial",
            "actionable": True,
            "query_seed": "remote pet check real pricing and payment",
        }
        candidates = research_loop.research_action_candidates(
            gap, study, [{"platform": "reddit", "mode": "fixture"}]
        )
        self.assertEqual("experiment", candidates[0]["action"])
        experiment = candidates[0]
        collect = next(item for item in candidates if item["action"] == "collect")
        self.assertGreater(experiment["priority_score"], collect["priority_score"])
        method = experiment["method_selection"]["applicable_methods"][0]
        self.assertTrue(method["selection_bias_record_required"])
        self.assertIn("paid_count", method["selection_bias_fields"])
        self.assertIn("delivered_count", method["selection_bias_fields"])
        boundaries = " ".join(experiment["method_selection"]["conclusion_boundaries"])
        self.assertIn("公开评论", boundaries)
        self.assertIn("不能证明本品真实付费", boundaries)
        self.assertEqual(
            study["decision"]["question"], experiment["decision_it_can_change"]
        )

    def test_method_selection_binds_sample_mechanism_to_claim_boundaries(self) -> None:
        route = sure_engine.route_request(
            "公开社区评论与访谈能否推总体发生率和市场规模？如何用真实报价实验验证付费？",
            domain="software", stage="pricing",
        )
        choice = route["method_selection"]
        self.assertEqual(route["query"], choice["research_question"])
        self.assertTrue(choice["sample_formation_mechanisms"])
        self.assertTrue(choice["applicable_methods"])
        boundaries = " ".join(choice["conclusion_boundaries"])
        self.assertIn("不能推总体发生率", boundaries)
        self.assertIn("访谈", boundaries)
        self.assertIn("不能推市场规模", boundaries)
        self.assertIn("公开评论", boundaries)
        experiments = [
            method for method in choice["applicable_methods"]
            if method["selection_bias_record_required"]
        ]
        self.assertTrue(experiments)
        self.assertIn("recruitment_frame", experiments[0]["selection_bias_fields"])

    def test_loop_plan_surfaces_unwritten_node_next_action_without_changing_truth(self) -> None:
        data = self.read_reasoning()
        before_status = data["chains"][0]["status"]
        need = data["chains"][0]["nodes"]["need"]
        need["statement"] = "待填写"
        need["status"] = "hypothesis"
        need["evidence_ids"] = []
        self.write_reasoning(data)
        judgments_before = (self.study / "04-findings/demand-judgments.json").read_bytes()
        completed = run_cli("loop", "plan", str(self.study))
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        payload = json.loads(completed.stdout)
        item = next(
            value for value in payload["next_best_actions"]
            if value["gap_key"] == "node:PR01.need:write"
        )
        self.assertFalse(item["actionable_for_collection"])
        self.assertEqual("analyze", item["candidate"]["action"])
        self.assertEqual(set(research_loop.RESEARCH_ACTION_KINDS), set(item["compared_actions"]))
        state = json.loads((self.study / "04-findings/research-loop.json").read_text(encoding="utf-8"))
        gap = next(value for value in state["gaps"] if value["key"] == "node:PR01.need:write")
        self.assertFalse(gap["actionable"])
        self.assertEqual(5, len(gap["research_action_candidates"]))
        self.assertEqual(before_status, self.read_reasoning()["chains"][0]["status"])
        self.assertEqual(judgments_before, (self.study / "04-findings/demand-judgments.json").read_bytes())

    def test_loop_executes_offline_analysis_for_existing_local_data(self) -> None:
        data = self.read_reasoning()
        need = data["chains"][0]["nodes"]["need"]
        need["statement"] = "待填写"
        need["status"] = "hypothesis"
        need["evidence_ids"] = []
        self.write_reasoning(data)
        chain_before = self.reasoning_path.read_bytes()
        judgments_before = (self.study / "04-findings/demand-judgments.json").read_bytes()
        planned = run_cli("loop", "plan", str(self.study))
        self.assertEqual(0, planned.returncode, planned.stdout + planned.stderr)
        state = json.loads((self.study / "04-findings/research-loop.json").read_text(encoding="utf-8"))
        gap = next(item for item in state["gaps"] if item["key"] == "node:PR01.need:write")
        analyze = next(item for item in gap["research_action_candidates"] if item["action"] == "analyze")
        self.assertTrue(analyze["executable_by_existing_loop"])
        self.assertEqual("none", analyze["execution_constraints"]["network"])
        self.assertEqual("analyze", gap["next_best_action"]["action"])
        self.assertEqual(0, run_cli("loop", "authorize", str(self.study), "--by", "tester").returncode)
        completed = run_cli("loop", "run", str(self.study))
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual("awaiting_semantic_review", payload["stop_reason"])
        self.assertEqual(1, payload["executions"])
        self.assertEqual(0, payload["candidates"])
        state = json.loads((self.study / "04-findings/research-loop.json").read_text(encoding="utf-8"))
        actions = [action for round_ in state["rounds"] for action in round_["actions"]]
        self.assertEqual(["analyze"], [action["kind"] for action in actions])
        result = actions[0]["result"]
        self.assertEqual("existing_study_data", actions[0]["analysis_scope"])
        self.assertEqual("none", result["network_access"])
        self.assertEqual("analyzed", result["follow_up_revision"]["after"])
        self.assertFalse(result["follow_up_revision"]["candidate_validated"])
        executions = json.loads((self.study / "04-findings/loop-executions.json").read_text(encoding="utf-8"))
        self.assertEqual(result["execution_id"], executions["executions"][0]["execution_id"])
        self.assertTrue((self.study / executions["executions"][0]["result"]["analysis_ref"]).is_file())
        self.assertEqual(chain_before, self.reasoning_path.read_bytes())
        self.assertEqual(judgments_before, (self.study / "04-findings/demand-judgments.json").read_bytes())

    def test_mcp_loop_uses_same_offline_analysis_execution(self) -> None:
        data = self.read_reasoning()
        need = data["chains"][0]["nodes"]["need"]
        need["statement"] = "待填写"
        need["status"] = "hypothesis"
        need["evidence_ids"] = []
        self.write_reasoning(data)
        self.assertEqual(0, run_cli("loop", "plan", str(self.study)).returncode)
        self.assertEqual(0, run_cli("loop", "authorize", str(self.study), "--by", "tester").returncode)
        responses = run_mcp({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "askovo_research_loop", "arguments": {"study_dir": str(self.study), "action": "run"},
        }})
        result = tool_payload(responses[0])
        self.assertEqual(0, result["exit_code"], json.dumps(result, ensure_ascii=False))
        self.assertEqual(1, result["result"]["executions"])
        self.assertEqual("awaiting_semantic_review", result["result"]["stop_reason"])

    def test_source_family_diversity_is_not_called_independent(self) -> None:
        marker, _, detail = sure_engine._plan_strength([
            {"evidence_level": "E3", "source_family": "reddit"},
            {"evidence_level": "E3", "source_family": "interview"},
        ], "feature")
        self.assertEqual("●", marker)
        self.assertIn("多个来源族", detail)
        self.assertIn("相关性未证明独立", detail)
        self.assertNotIn("多来源独立观察", detail)


class DecisionRecordTests(StudyCase):
    def test_versioned_record_replays_original_hypothesis_and_current_drift(self) -> None:
        original = self.read_reasoning()
        judgments = self.study / "04-findings/demand-judgments.json"
        judgments_before = judgments.read_bytes()
        first = run_cli(
            "decision", "record", str(self.study), "--chain", "PR01", "--by", "Owner",
            "--hypothesis", "H1", "--observation", "Two invited participants received the paid pilot",
            "--evidence", "R04", "--revision", "Initial pilot decision",
        )
        self.assertEqual(0, first.returncode, first.stdout + first.stderr)
        first_record = json.loads(first.stdout)["record"]
        changed = self.read_reasoning()
        changed["chains"][0]["next_test"] = "Run a real quote and delivery experiment with denominators"
        self.write_reasoning(changed)
        second = run_cli(
            "decision", "record", str(self.study), "--chain", "PR01", "--by", "Owner",
            "--revision", "Revise next action after observed delivery",
        )
        self.assertEqual(0, second.returncode, second.stdout + second.stderr)
        second_record = json.loads(second.stdout)["record"]
        self.assertEqual((1, 2), (first_record["version"], second_record["version"]))
        self.assertEqual(first_record["original_hypothesis"], second_record["original_hypothesis"])
        self.assertEqual("H1", second_record["original_hypothesis"][0]["id"])
        self.assertTrue(second_record["candidate_actions"])
        self.assertTrue(second_record["basis"]["node_refs"])
        self.assertEqual("decided", self.read_reasoning()["chains"][0]["status"])
        self.assertEqual(original["chains"][0]["nodes"], self.read_reasoning()["chains"][0]["nodes"])
        self.assertEqual(judgments_before, judgments.read_bytes())

        replayed = run_cli("decision", "replay", str(self.study), "--chain", "PR01", "--json")
        self.assertEqual(0, replayed.returncode, replayed.stdout + replayed.stderr)
        replay = json.loads(replayed.stdout)
        self.assertEqual(2, replay["count"])
        self.assertEqual([], replay["timeline"][1]["changes_from_previous"]["node_changes"])
        self.assertEqual(original["chains"][0]["next_test"], replay["timeline"][1]["changes_from_previous"]["next_action_before"])
        self.assertIn("下一动作", replay["markdown"])
        old = run_cli(
            "decision", "replay", str(self.study), "--record-id", first_record["record_id"], "--json"
        )
        old_replay = json.loads(old.stdout)
        self.assertTrue(old_replay["current_drift"][0]["changed_since_record"])
        self.assertEqual(original["chains"][0]["next_test"], old_replay["timeline"][0]["next_action"])

    def test_new_mapped_contradiction_auto_holds_without_replacement_recommendation(self) -> None:
        first = run_cli(
            "decision", "record", str(self.study), "--chain", "PR01", "--by", "Owner",
            "--decision", "Support the bounded mobile product opportunity",
            "--hypothesis", "H1", "--revision", "Initial supporting decision",
        )
        self.assertEqual(0, first.returncode, first.stdout + first.stderr)
        first_record = json.loads(first.stdout)["record"]
        before_product = first_record["chain_snapshot"]["nodes"]["product"]["statement"]
        judgments_before = (self.study / "04-findings/demand-judgments.json").read_bytes()
        supporting_before = json.dumps(first_record["chain_snapshot"]["supporting_states"], sort_keys=True)

        evidence_path = self.study / "02-data/evidence.jsonl"
        contradiction = {
            "record_id": "R08", "context_key": "synthetic-mobile-check",
            "user_role": "Remote pet owner", "scene_trigger": "Uses the bounded mobile check at home",
            "task_outcome": "Keep private rooms unrecorded", "current_substitute": "Fixed cameras",
            "friction_cost": "Session boundary failed in the reviewed evidence",
            "consequence": "Reviewer rejects proceeding on the prior recommendation",
            "evidence_level": "E4-", "evidence_basis": "Registered reviewed rejection of the current product boundary",
            "corpus_role": "substitute_rejector", "source_family": "interview",
            "source_ref": "synthetic-adversarial-01", "normalized_text_hash": "sha256:r08",
        }
        with evidence_path.open("a", encoding="utf-8") as out:
            out.write(json.dumps(contradiction, ensure_ascii=False) + "\n")
        (self.study / "04-findings/loop-mappings.json").write_text(json.dumps({
            "mappings": [{
                "id": "M01", "record_id": "R08", "hypothesis_id": "H1",
                "stance": "contradicts", "quote": "Reviewer rejects proceeding on the prior recommendation",
                "level": "host_supplied_mapping",
            }],
        }), encoding="utf-8")
        second = run_cli(
            "decision", "record", str(self.study), "--chain", "PR01", "--by", "Owner",
            "--contradiction", "R08", "--revision", "Trusted contradiction requires safe hold",
        )
        self.assertEqual(0, second.returncode, second.stdout + second.stderr)
        result = json.loads(second.stdout)
        record = result["record"]
        revision = record["adversarial_revision"]
        self.assertEqual(2, record["version"])
        self.assertEqual("deterministic_safe_hold", revision["recommendation_origin"])
        self.assertEqual("hold", revision["recommendation_code"])
        self.assertEqual("low", revision["before"]["confidence"])
        self.assertEqual("very-low", revision["after"]["confidence"])
        self.assertEqual(before_product, revision["before"]["product_recommendation"])
        self.assertNotEqual(before_product, revision["after"]["product_recommendation"])
        self.assertIn("loop-mappings", revision["evidence"][0]["contradiction_sources"][0])
        chain = self.read_reasoning()["chains"][0]
        self.assertEqual("needs-validation", chain["status"])
        self.assertEqual("very-low", chain["confidence"])
        self.assertEqual("needs-validation", chain["nodes"]["product"]["status"])
        self.assertEqual("needs-validation", chain["nodes"]["business"]["status"])
        self.assertEqual("hold", chain["nodes"]["business"]["gate"]["decision"])
        self.assertNotIn("R08", chain["nodes"]["product"]["evidence_ids"])
        self.assertNotIn("R08", chain["counter_evidence_ids"])
        self.assertEqual(judgments_before, (self.study / "04-findings/demand-judgments.json").read_bytes())
        self.assertEqual(supporting_before, json.dumps(chain["supporting_states"], sort_keys=True))
        self.assertFalse(revision["candidate_evidence_promoted"])
        self.assertFalse(revision["causal_status_changed"])

        replayed = run_cli("decision", "replay", str(self.study), "--chain", "PR01", "--json")
        self.assertEqual(0, replayed.returncode, replayed.stdout + replayed.stderr)
        replay = json.loads(replayed.stdout)
        self.assertEqual(2, replay["count"])
        changes = replay["timeline"][1]["changes_from_previous"]
        self.assertEqual("low", changes["confidence_before"])
        self.assertEqual("very-low", changes["confidence_after"])
        self.assertEqual(before_product, changes["product_recommendation_before"])
        self.assertNotEqual(before_product, changes["product_recommendation_after"])
        self.assertEqual({"product", "business"}, {item["node"] for item in changes["node_changes"]})
        self.assertIn("改前", replay["markdown"])
        self.assertIn("改后", replay["markdown"])
        checked = run_cli("check", str(self.study), "--stage", "full")
        self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)

    def test_optional_human_recommendation_overrides_safe_hold(self) -> None:
        first = run_cli("decision", "record", str(self.study), "--chain", "PR01", "--by", "Owner")
        self.assertEqual(0, first.returncode, first.stdout + first.stderr)
        replacement = "Keep the existing fixed-camera setup pending accountable product review"
        second = run_cli(
            "decision", "record", str(self.study), "--chain", "PR01", "--by", "Owner",
            "--contradiction", "R05", "--recommendation", replacement,
        )
        self.assertEqual(0, second.returncode, second.stdout + second.stderr)
        record = json.loads(second.stdout)["record"]
        self.assertEqual("decision_maker_override", record["adversarial_revision"]["recommendation_origin"])
        self.assertEqual(replacement, record["decision"])
        chain = self.read_reasoning()["chains"][0]
        self.assertEqual(replacement, chain["nodes"]["product"]["statement"])
        self.assertEqual(replacement, chain["nodes"]["business"]["gate"]["decision"])
        self.assertEqual("not-claimed", chain["supporting_states"]["causal"]["status"])

    def test_contradiction_id_without_recorded_counter_mapping_is_rejected(self) -> None:
        first = run_cli("decision", "record", str(self.study), "--chain", "PR01", "--by", "Owner")
        self.assertEqual(0, first.returncode, first.stdout + first.stderr)
        before = self.reasoning_path.read_bytes()
        rejected = run_cli(
            "decision", "record", str(self.study), "--chain", "PR01", "--by", "Owner",
            "--contradiction", "R04",
        )
        self.assertEqual(2, rejected.returncode, rejected.stdout + rejected.stderr)
        self.assertIn("no recorded contradicts", json.loads(rejected.stdout)["reason"])
        self.assertEqual(before, self.reasoning_path.read_bytes())

    def test_mcp_contradiction_uses_same_safe_hold_rule(self) -> None:
        first = run_cli("decision", "record", str(self.study), "--chain", "PR01", "--by", "Owner")
        self.assertEqual(0, first.returncode, first.stdout + first.stderr)
        responses = run_mcp({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "askovo_decision", "arguments": {
                "study_dir": str(self.study), "action": "record", "chain": "PR01", "by": "Owner",
                "contradiction": ["R05"],
            },
        }})
        payload = tool_payload(responses[0])
        self.assertEqual(0, payload["exit_code"], json.dumps(payload, ensure_ascii=False))
        self.assertEqual("hold", payload["result"]["record"]["decision"])
        self.assertEqual("deterministic_safe_hold",
                         payload["result"]["record"]["adversarial_revision"]["recommendation_origin"])

    def test_record_rejects_unregistered_observation_evidence(self) -> None:
        completed = run_cli(
            "decision", "record", str(self.study), "--chain", "PR01", "--by", "Owner",
            "--observation", "Unsupported observation", "--evidence", "R404",
        )
        self.assertEqual(2, completed.returncode)
        self.assertIn("not registered", json.loads(completed.stdout)["reason"])
        self.assertNotIn("decision_records", self.read_reasoning())

    def test_mcp_decision_record_and_readable_replay(self) -> None:
        responses = run_mcp(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                "name": "askovo_decision", "arguments": {
                    "study_dir": str(self.study), "action": "record", "chain": "PR01", "by": "Owner",
                    "observation": ["Observed delivery"], "evidence": ["R04"],
                },
            }},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
                "name": "askovo_decision", "arguments": {
                    "study_dir": str(self.study), "action": "replay", "chain": "PR01",
                },
            }},
        )
        by_id = {item.get("id"): item for item in responses}
        self.assertIn("askovo_decision", {item["name"] for item in by_id[1]["result"]["tools"]})
        self.assertEqual(1, tool_payload(by_id[2])["result"]["record"]["version"])
        replay_response = by_id[3]["result"]
        self.assertEqual(1, tool_payload(by_id[3])["result"]["count"])
        self.assertGreaterEqual(len(replay_response["content"]), 2)
        self.assertIn("原假设", replay_response["content"][1]["text"])
        self.assertIn("候选动作", replay_response["content"][1]["text"])


class DeliverySummaryTests(StudyCase):
    def test_cli_delivery_projects_all_summary_fields_from_fresh_inputs(self) -> None:
        completed = run_cli("deliver", str(self.study), "--kind", "plan")
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        result = json.loads(completed.stdout)
        summary = result["chat_summary"]
        for key in (
            "decision", "basis", "actions", "costs_and_boundaries", "unknowns",
            "input_fingerprint", "freshness", "reproduce_command", "text",
        ):
            self.assertIn(key, summary)
        self.assertEqual("fresh", summary["freshness"]["status"])
        self.assertEqual("pass", summary["audit_status"])
        self.assertTrue(summary["input_fingerprint"].startswith("sha256:"))
        self.assertIn("askovo deliver", summary["reproduce_command"])
        for heading in ("## 决定", "## 依据", "## 行动", "## 成本与边界", "## Unknowns"):
            self.assertIn(heading, summary["text"])
        self.assertRegex(summary["artifact"]["sha256"], r"^sha256:[0-9a-f]{64}$")
        self.assertTrue(Path(summary["artifact"]["path"]).is_file())

    def test_mcp_delivery_preserves_json_and_adds_readable_text(self) -> None:
        response = run_mcp({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
                "name": "askovo_deliver", "arguments": {"study_dir": str(self.study), "kind": "plan"},
            },
        })[0]["result"]
        payload = tool_payload({"result": response})
        self.assertEqual(0, payload["exit_code"])
        self.assertGreaterEqual(len(response["content"]), 2)
        self.assertEqual(payload["result"]["chat_summary"]["text"], response["content"][1]["text"])
        self.assertIn("## 决定", response["content"][1]["text"])
        self.assertIn("input_fingerprint", response["content"][1]["text"])

    def test_audit_failure_is_not_presented_as_audited_recommendation(self) -> None:
        data = self.read_reasoning()
        data["chains"][0]["nodes"]["need"]["evidence_ids"] = ["R02"]
        self.write_reasoning(data)
        completed = run_cli("deliver", str(self.study), "--kind", "plan")
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        summary = json.loads(completed.stdout)["chat_summary"]
        self.assertEqual("audit_failed", summary["status"])
        self.assertEqual("fail", summary["audit_status"])
        self.assertTrue(summary["audit_failures"])
        self.assertFalse(summary["decision"][0]["audited_recommendation"])
        self.assertIn("不是已审核推荐", summary["text"])

    def test_missing_study_returns_readable_no_artifact_error(self) -> None:
        missing = self.tmp / "missing"
        completed = run_cli("deliver", str(missing), "--kind", "plan")
        self.assertEqual(2, completed.returncode, completed.stdout + completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual("error", result["status"])
        summary = result["chat_summary"]
        self.assertEqual("no_artifact", summary["status"])
        self.assertEqual("no_artifact", summary["freshness"]["status"])
        self.assertFalse(summary["artifact"]["exists"])
        self.assertIn("无可用产物", summary["text"])
        self.assertTrue(summary["unknowns"])

    def test_stale_artifact_is_explicit_and_has_regeneration_action(self) -> None:
        report = self.study / "06-report/plan.md"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("# old plan\n", encoding="utf-8")
        os.utime(report, (100, 100))
        study = json.loads((self.study / "study.json").read_text(encoding="utf-8"))
        reasoning = self.read_reasoning()
        summary = delivery_projection.build_chat_summary(
            self.study, "plan", {"status": "written", "path": "06-report/plan.md"},
            study=study, reasoning=reasoning,
            evidence={"records": []}, audit_info={"status": "pass", "checks": []},
        )
        self.assertEqual("stale", summary["status"])
        self.assertEqual("stale", summary["freshness"]["status"])
        self.assertIn("study.json", summary["freshness"]["stale_inputs"])
        self.assertEqual("regenerate", summary["actions"][0]["type"])
        self.assertIn("不能当作当前结论", summary["text"])


if __name__ == "__main__":
    unittest.main()
