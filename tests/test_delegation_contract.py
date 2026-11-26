"""C-01-Lite 合同：decide status 必须给出最小委托投影。

契约：ai输出/ovo-C01-Lite-最小委托契约-v1-20261115.md
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CLI = REPO / "skills" / "askovo" / "scripts" / "askovo.py"
sys.path.insert(0, str(CLI.parent))
STATES = {"NEEDS_INPUT", "READY", "NEEDS_REVIEW", "BLOCKED", "PARTIAL", "DELIVERED"}
CODES = {"INPUT_REQUIRED", "AUTH_REQUIRED", "REVIEW_REQUIRED", "UNSUPPORTED_SCOPE",
         "POLICY_DENIED", "RATE_LIMITED", "STALE_SOURCE",
         "INDETERMINATE_EXTERNAL_ACTION", "ARTIFACT_PARTIAL", "INTERNAL_ERROR"}


def run_cli(*args):
    return subprocess.run([sys.executable, str(CLI), *args],
                          capture_output=True, text=True, timeout=120,
                          env=dict(os.environ, ASKOVO_AUTHOR_SKIP_SALT="1"))


class DelegationContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name) / "ws"
        task = {"schema": "askovo.decision-task/1", "task_id": "T-1",
                "question": "下一版先修哪些问题？",
                "product": {"kind": "github_repository", "repo": "owner/repo"},
                "decision_type": "prioritize_features",
                "source_scope": {"issues": True},
                "authorization": {"approved_by": None,
                                  "allowed_sources": ["github"], "max_records": 5}}
        self.task_path = Path(self.tmp.name) / "task.json"
        self.task_path.write_text(json.dumps(task), encoding="utf-8")
        started = run_cli("decide", "start", "--workspace", str(self.ws),
                          "--input", str(self.task_path))
        self.assertEqual(0, started.returncode, started.stderr + started.stdout)
        self.task_id = json.loads(started.stdout)["task_id"]

    def _status(self):
        out = run_cli("decide", "status", self.task_id, "--workspace", str(self.ws))
        self.assertEqual(0, out.returncode, out.stderr + out.stdout)
        return json.loads(out.stdout)

    def test_delegation_block_is_complete(self):
        payload = self._status()
        self.assertIn("delegation", payload)
        block = payload["delegation"]
        for key in ("task_id", "task_state", "next_actor", "next_required_action",
                    "blocked_reason_code", "result_ref", "authorization_scope",
                    "recovery_entry", "delegation_boundary"):
            self.assertIn(key, block, f"{key} missing from the delegation block")
        self.assertEqual(self.task_id, block["task_id"])
        self.assertIn(block["task_state"], STATES)
        self.assertTrue(block["next_required_action"])
        self.assertIn(block["next_actor"], ("human", "agent", "system"))
        self.assertTrue(block["delegation_boundary"])

    def test_blocked_state_names_a_human_and_a_recovery_entry(self):
        block = self._status()["delegation"]
        # 没有授权人 → NEEDS_INPUT/BLOCKED，下一责任人必须是人，且给恢复入口
        self.assertIn(block["task_state"], ("NEEDS_INPUT", "BLOCKED"))
        self.assertEqual("human", block["next_actor"])
        self.assertTrue(block["recovery_entry"])
        self.assertIn(block["blocked_reason_code"], CODES)

    def test_scope_is_reported_not_invented(self):
        block = self._status()["delegation"]
        self.assertEqual(["github"], block["authorization_scope"]["allowed_sources"])
        self.assertEqual(5, block["authorization_scope"]["max_records"])
        self.assertIsNone(block["authorization_scope"]["approved_by"])

    def test_task_result_waits_for_external_input_without_requesting_a_decision(self):
        payload = self._status()
        self.assertIn("task_result", payload)
        result = payload["task_result"]
        self.assertEqual("ovo.task-result/1", result["schema"])
        self.assertEqual("askovo", result["product"])
        self.assertEqual(self.task_id, result["task_id"])
        self.assertEqual("waiting_external", result["status"])
        self.assertFalse(result["user_decision_required"])
        self.assertEqual(self.task_id, result["resume_ref"])
        self.assertTrue(result["missing_conditions"])
        self.assertTrue(result["next_actions"])
        self.assertTrue(result["next_actions"][0]["requires_user"])

    def test_review_state_maps_to_needs_decision(self):
        import decide
        self.assertTrue(hasattr(decide, "task_result_view"))
        result = decide.task_result_view(
            {"task_id": "T-review", "state": "review_required"},
            {"next_actor": "human_reviewer", "next_required_action": "review candidates",
             "blocked_reason_code": "REVIEW_REQUIRED"}, [])
        self.assertEqual("needs_decision", result["status"])
        self.assertTrue(result["user_decision_required"])

    def test_blocked_state_maps_to_unable_to_complete_with_recovery(self):
        import decide
        self.assertTrue(hasattr(decide, "task_result_view"))
        result = decide.task_result_view(
            {"task_id": "T-blocked", "state": "blocked"},
            {"next_actor": "human_operator", "next_required_action": "repair the source",
             "blocked_reason_code": "INTERNAL_ERROR"}, [])
        self.assertEqual("unable_to_complete", result["status"])
        self.assertFalse(result["user_decision_required"])
        self.assertTrue(result["next_actions"])

    def test_open_research_gaps_with_results_map_to_partial_result(self):
        import decide
        result = decide.task_result_view(
            {"task_id": "T-partial", "state": "collecting"},
            {"next_actor": "askovo", "next_required_action": "continue research"},
            ["study/04-findings/research-loop.json"], {"unresolved": 2})
        self.assertEqual("partial_result", result["status"])
        self.assertFalse(result["user_decision_required"])
        self.assertEqual("research_evidence", result["missing_conditions"][0]["scope"])
        self.assertFalse(result["missing_conditions"][0]["blocking"])


if __name__ == "__main__":
    unittest.main()
