#!/usr/bin/env python3
"""A-02 one-question decide executor: entry semantics, state machine and limits.

Frozen acceptance tests for the `askovo decide` orchestrator (PRD 01-Askovo
§2.2/§2.4/§3 A-02, AC A6-A12) and the C-01 delegation contract mapping
(reason codes, status fields, correct refusal). Everything runs offline on
synthetic fixtures; the orchestrator must reuse the Research Loop and never
bypass `loop authorize` or human `loop assess`.
"""
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
MCP_SERVER = ROOT / "skills/askovo/scripts/askovo_mcp.py"
SAMPLE = ROOT / "examples/sample-study"

DECISION_TYPES = ("prioritize_features", "validate_hypothesis")


def run_cli(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    merged = dict(os.environ)
    if env:
        merged.update(env)
    return subprocess.run([sys.executable, str(CLI), "decide", *args],
                          capture_output=True, text=True, timeout=180, env=merged)


def run_raw(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(CLI), *args],
                          capture_output=True, text=True, timeout=180)


def run_mcp(*requests: dict) -> list[dict]:
    lines = "\n".join(json.dumps(request) for request in requests) + "\n"
    completed = subprocess.run([sys.executable, str(MCP_SERVER)], input=lines,
                               check=False, capture_output=True, text=True, timeout=180)
    return [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]


def tool_payload(response: dict) -> dict:
    return json.loads(response["result"]["content"][0]["text"])


def decision_task(tmp: Path, **overrides) -> dict:
    """Build an askovo.decision-task/1 input bound to an offline fixture."""
    fixture = tmp / "export.jsonl"
    rows = [
        {"id": "d1", "title": "cannot parse nested json logs",
         "text": "Nested JSON logs fail to parse; we retry by hand every week.",
         "url": "https://github.com/o/r/issues/1", "author": "u1",
         "created_at": "2026-09-01", "claim_type": "problem", "evidence_form": "self_report"},
        {"id": "d2", "title": "multiline stack traces",
         "text": "Multiline stack traces are split into wrong events and break alerts.",
         "url": "https://github.com/o/r/issues/2", "author": "u2",
         "created_at": "2026-09-02", "claim_type": "problem", "evidence_form": "self_report"},
        {"id": "d3", "title": "timestamp format guess",
         "text": "The parser guesses timestamps wrong and we lose a third of events.",
         "url": "https://github.com/o/r/issues/3", "author": "u3",
         "created_at": "2026-09-03", "claim_type": "problem", "evidence_form": "self_report"},
    ]
    fixture.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    task = {
        "schema": "askovo.decision-task/1",
        "question": "下一版应该优先处理哪些日志解析问题？",
        "product": {"kind": "github_repository", "repo": "owner/repo"},
        "decision_type": "prioritize_features",
        "audience": {"description": "使用该 CLI 的开发者", "confidence": "declared"},
        "source_scope": {"issues": True, "discussions": False, "updated_since": "2026-08-01"},
        "authorization": {"approved_by": "owner", "allowed_sources": ["github"],
                          "max_records": 200},
        "deadline": "2026-12-01",
        "delivery": {"primary": "decision_brief", "secondary": ["evidence_index"]},
    }
    task["source_scope"]["fixture"] = str(fixture)
    for key, value in overrides.items():
        if key == "no_fixture":
            task["source_scope"].pop("fixture", None)
        else:
            task[key] = value
    return task


class DecideHelpers:
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.workspace = self.dir / "decide-workspace"
        self.study = self.dir / "study"
        shutil.copytree(SAMPLE, self.study)
        self._prepare_bound_study()

    def _prepare_bound_study(self) -> None:
        """Give the sample study a collectible gap plus an offline fixture."""
        fixture = self.study / "01-sources" / "authorized" / "export.jsonl"
        fixture.parent.mkdir(parents=True, exist_ok=True)
        rows = [
            {"id": "l1", "title": "privacy of a roaming check",
             "text": "I would not let a camera roam my home while I am away; privacy matters more.",
             "url": "https://github.com/o/r/issues/10", "author": "u1",
             "created_at": "2026-02-01", "claim_type": "commercial", "evidence_form": "self_report"},
            {"id": "l2", "title": "sitter already covers this",
             "text": "We already pay a sitter; another subscription is hard to justify.",
             "url": "https://github.com/o/r/issues/11", "author": "u2",
             "created_at": "2026-02-02", "claim_type": "commercial", "evidence_form": "self_report"},
            {"id": "l3", "title": "would try one month",
             "text": "I would try one month of bounded checks if it is easy to cancel.",
             "url": "https://github.com/o/r/issues/12", "author": "u3",
             "created_at": "2026-02-03", "claim_type": "commercial", "evidence_form": "self_report"},
        ]
        fixture.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        study_json = self.study / "study.json"
        data = json.loads(study_json.read_text(encoding="utf-8"))
        data["scope"]["allowed_sources"] = ["github"]
        data["research_loop"] = {"fixtures": {"github": "01-sources/authorized/export.jsonl"}}
        study_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        judgments_path = self.study / "04-findings" / "demand-judgments.json"
        judgments = json.loads(judgments_path.read_text(encoding="utf-8"))
        judgments.append({
            "id": "D02",
            "context_key": "",
            "title": "Remote owners will pay a monthly fee for bounded mobile checks",
            "user_role": "Remote pet owners",
            "scene": "Away from home",
            "task": "Check on the pet",
            "current_substitute": "Fixed cameras",
            "friction": "Blind spots",
            "consequence": "Delayed care",
            "solution": "Mobile check subscription",
            "acceptance_conditions": "Privacy controls",
            "problem_evidence_ids": ["R01"],
            "solution_evidence_ids": [],
            "commercial_evidence_ids": [],
            "counter_evidence_ids": [],
            "status": "hypothesis",
            "confidence": "low",
            "gaps": ["No paid-behavior evidence"],
            "next_test": "Offer a paid pilot",
        })
        judgments_path.write_text(json.dumps(judgments, ensure_ascii=False, indent=2),
                                  encoding="utf-8")

    # -- helpers ---------------------------------------------------------- #

    def write_input(self, task: dict, name: str = "task.json") -> Path:
        path = self.dir / name
        path.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def start(self, task: dict, *extra: str, name: str = "task.json") -> tuple[subprocess.CompletedProcess, dict]:
        path = self.write_input(task, name=name)
        completed = run_cli("start", "--workspace", str(self.workspace),
                            "--input", str(path), *extra)
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            payload = {"raw": completed.stdout, "stderr": completed.stderr}
        return completed, payload

    def start_bound(self, task: dict, *extra: str, name: str = "task.json") -> tuple[subprocess.CompletedProcess, dict]:
        return self.start(task, "--study", str(self.study), *extra, name=name)

    def status(self, task_id: str) -> tuple[subprocess.CompletedProcess, dict]:
        completed = run_cli("status", task_id, "--workspace", str(self.workspace))
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            payload = {"raw": completed.stdout, "stderr": completed.stderr}
        return completed, payload

    def loop_state(self, task_id: str | None = None) -> dict:
        return json.loads((self.study / "04-findings" / "research-loop.json").read_text(encoding="utf-8"))

    def run_full(self, task: dict, name: str = "task.json") -> tuple[str, dict]:
        """start -> human loop authorize -> resume run; returns (task_id, final payload)."""
        completed, payload = self.start_bound(task, "--run", name=name)
        assert completed.returncode == 0, payload
        task_id = payload["task_id"]
        authorized = run_raw("loop", "authorize", str(self.study), "--by", "product-owner")
        assert authorized.returncode == 0, authorized.stdout + authorized.stderr
        completed, payload = self.start_bound(task, "--run", "--task", task_id, name=name)
        assert completed.returncode == 0, payload
        return task_id, payload


class DecideStartTests(DecideHelpers, unittest.TestCase):

    def test_dry_run_is_default_and_reads_nothing(self) -> None:
        completed, payload = self.start_bound(decision_task(self.dir))
        self.assertEqual(0, completed.returncode, payload)
        self.assertEqual("scoped", payload["state"])
        self.assertTrue(payload["plan"], payload)
        loop = self.loop_state()
        self.assertEqual("planned", loop["status"])
        self.assertFalse(loop.get("authorization"))
        self.assertEqual(0, loop["totals"]["records"])
        self.assertEqual([], loop.get("rounds") or [])
        self.assertFalse((self.study / "02-data" / "normalized.jsonl").exists()
                         and self._normalized_nonempty(), "dry-run must not import records")

    def _normalized_nonempty(self) -> bool:
        path = self.study / "02-data" / "normalized.jsonl"
        return path.exists() and path.read_text(encoding="utf-8").strip() != ""

    def test_unsupported_decision_type_is_refused_without_fake_task(self) -> None:
        task = decision_task(self.dir, decision_type="market_sizing")
        completed, payload = self.start_bound(task)
        self.assertEqual(2, completed.returncode)
        self.assertEqual("UNSUPPORTED_SCOPE", payload["reason_code"])
        self.assertIn("prioritize_features", payload["reason"])
        self.assertIn("validate_hypothesis", payload["reason"])
        self.assertFalse(list(self.workspace.glob("tasks/*")) if self.workspace.exists() else True)

    def test_missing_question_is_input_required(self) -> None:
        task = decision_task(self.dir)
        task["question"] = ""
        completed, payload = self.start_bound(task)
        self.assertEqual(2, completed.returncode)
        self.assertEqual("INPUT_REQUIRED", payload["reason_code"])

    def test_unsupported_source_is_refused_with_explanation(self) -> None:
        task = decision_task(self.dir)
        task["authorization"]["allowed_sources"] = ["internal_wiki"]
        completed, payload = self.start_bound(task)
        self.assertEqual(2, completed.returncode)
        self.assertEqual("UNSUPPORTED_SCOPE", payload["reason_code"])
        self.assertIn("internal_wiki", payload["reason"])

    def test_deterministic_plan_for_identical_input(self) -> None:
        task_a = decision_task(self.dir)
        task_b = decision_task(self.dir)
        completed_a, payload_a = self.start_bound(task_a, name="a.json")
        completed_b, payload_b = self.start_bound(task_b, name="b.json")
        self.assertEqual(0, completed_a.returncode, payload_a)
        self.assertEqual(0, completed_b.returncode, payload_b)
        self.assertEqual(payload_a["task_id"], payload_b["task_id"])
        self.assertEqual(payload_a["plan"]["digest"], payload_b["plan"]["digest"])
        self.assertEqual(payload_a["budget"]["max_records"], payload_b["budget"]["max_records"])


class DecideAuthorizationTests(DecideHelpers, unittest.TestCase):

    def test_missing_authorization_fails_clear_and_reads_nothing(self) -> None:
        task = decision_task(self.dir)
        task["authorization"] = {}
        completed, payload = self.start_bound(task, "--run")
        self.assertEqual(0, completed.returncode, payload)  # draft creation is a valid outcome
        self.assertEqual("needs_input", payload["state"])
        self.assertEqual("AUTH_REQUIRED", payload["blocked_reason_code"])
        self.assertTrue(payload["next_required_action"])
        self.assertFalse((self.study / "04-findings" / "research-loop.json").exists(),
                         "no planning or reading without any authorized source")

    def test_run_without_human_authorization_never_reads(self) -> None:
        task = decision_task(self.dir, no_fixture=True)
        completed, payload = self.start_bound(task, "--run")
        self.assertEqual(0, completed.returncode, payload)
        self.assertEqual("needs_input", payload["state"])
        self.assertEqual("AUTH_REQUIRED", payload["blocked_reason_code"])
        self.assertIn("loop authorize", payload["next_required_action"])
        loop = self.loop_state()
        self.assertEqual("planned", loop["status"])
        self.assertFalse(loop.get("authorization"))
        self.assertEqual(0, loop["totals"]["records"])

    def test_orchestrator_never_self_authorizes_or_assesses(self) -> None:
        task_id, payload = self.run_full(decision_task(self.dir))
        loop = self.loop_state()
        self.assertEqual("product-owner", loop["authorization"]["by"],
                         "authorization must come from the human loop command only")
        self.assertEqual([], loop.get("evaluations") or [],
                         "the orchestrator must not auto-pass human assess")
        candidates = json.loads(
            (self.study / "04-findings" / "loop-candidates.json").read_text(encoding="utf-8"))
        self.assertTrue(candidates["candidates"])
        for candidate in candidates["candidates"]:
            self.assertEqual("proposed", candidate["status"])
            self.assertIsNone(candidate["proposed_evidence_level"])


class DecideRunTests(DecideHelpers, unittest.TestCase):

    def test_state_machine_happy_path_order(self) -> None:
        task_id, payload = self.run_full(decision_task(self.dir))
        self.assertEqual("review_required", payload["state"])
        task = json.loads((self.workspace / "tasks" / task_id / "task.json")
                          .read_text(encoding="utf-8"))
        states = [entry["state"] for entry in task["phase_history"]]
        self.assertEqual(["created", "scoped", "collecting", "analyzed", "review_required"],
                         states[:5])
        self.assertNotIn("delivered", states)

    def test_record_cap_is_never_exceeded(self) -> None:
        task = decision_task(self.dir)
        task["authorization"]["max_records"] = 2
        task_id, payload = self.run_full(task)
        self.assertEqual(2, payload["budget"]["max_records"])
        loop = self.loop_state()
        self.assertEqual(2, loop["envelope"]["max_records_total"])
        self.assertLessEqual(loop["totals"]["records"], 2)
        normalized = [line for line in
                      (self.study / "02-data" / "normalized.jsonl").read_text(encoding="utf-8").splitlines()
                      if line.strip()]
        self.assertLessEqual(len(normalized), 2)
        self.assertNotEqual(3, len(normalized), "a 2-record budget must never import 3")

    def test_cancel_stops_all_further_reading(self) -> None:
        task = decision_task(self.dir)
        completed, payload = self.start_bound(task)
        task_id = payload["task_id"]
        cancelled = run_cli("cancel", task_id, "--by", "owner",
                            "--workspace", str(self.workspace))
        self.assertEqual(0, cancelled.returncode, cancelled.stdout)
        completed, payload = self.start_bound(task, "--task", task_id, "--run")
        self.assertEqual(2, completed.returncode)
        self.assertEqual("POLICY_DENIED", payload["reason_code"])
        self.assertIn("cancel", payload["reason"].lower())
        loop = self.loop_state()
        self.assertEqual("planned", loop["status"])
        self.assertEqual(0, loop["totals"]["records"])
        self.assertEqual([], loop.get("rounds") or [])

    def test_repeat_start_and_resume_do_not_duplicate_import(self) -> None:
        task = decision_task(self.dir)
        first_id, first = self.run_full(task, name="first.json")
        loop_after_first = self.loop_state()
        records_first = loop_after_first["totals"]["records"]
        rounds_first = len(loop_after_first.get("rounds") or [])
        candidates_first = len(
            json.loads((self.study / "04-findings" / "loop-candidates.json")
                       .read_text(encoding="utf-8"))["candidates"])
        # identical input submitted again: same task, no second study or plan
        completed, payload = self.start_bound(task, "--run", name="second.json")
        self.assertEqual(first_id, payload["task_id"])
        self.assertEqual(1, len(list((self.workspace / "studies").glob("*")))
                        if (self.workspace / "studies").exists() else 0)
        # resume after completion: no re-run, no duplicate candidates
        completed, payload = self.start_bound(task, "--task", first_id, "--run", name="second.json")
        self.assertEqual(0, completed.returncode, payload)
        self.assertEqual("review_required", payload["state"])
        loop_after = self.loop_state()
        self.assertEqual(records_first, loop_after["totals"]["records"])
        self.assertEqual(rounds_first, len(loop_after.get("rounds") or []))
        candidates_after = len(
            json.loads((self.study / "04-findings" / "loop-candidates.json")
                       .read_text(encoding="utf-8"))["candidates"])
        self.assertEqual(candidates_first, candidates_after)

    def test_dry_start_never_rewinds_a_completed_task(self) -> None:
        task = decision_task(self.dir)
        task_id, _ = self.run_full(task)
        state_path = self.workspace / "tasks" / task_id / "task.json"
        before = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual("review_required", before["state"])
        # A dry start is read-only: same input, same task, no phase added.
        completed, payload = self.start_bound(task)
        self.assertEqual(0, completed.returncode, payload)
        self.assertEqual("review_required", payload["state"])
        self.assertEqual("human_reviewer", payload["next_actor"])
        self.assertNotIn("loop authorize", payload["next_required_action"],
                         "a collected task must not regress to the authorization gate")
        after = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(before["state"], after["state"])
        self.assertEqual(before["phase_history"], after["phase_history"],
                         "a dry start must not append a phase")

    def test_interrupted_resume_requires_reconcile_and_recollects_nothing(self) -> None:
        task = decision_task(self.dir)
        completed, payload = self.start_bound(task, "--run")
        task_id = payload["task_id"]
        run_raw("loop", "authorize", str(self.study), "--by", "product-owner")
        # simulate an interrupted action round (crash mid-collection)
        loop = self.loop_state()
        loop["status"] = "needs_review"
        loop["stop_reason"] = "interrupted_run"
        (self.study / "04-findings" / "research-loop.json").write_text(
            json.dumps(loop, ensure_ascii=False, indent=2), encoding="utf-8")
        completed, payload = self.start_bound(task, "--task", task_id, "--run")
        self.assertEqual(0, completed.returncode, payload)
        self.assertEqual("interrupted", payload["state"])
        self.assertIn("reconcile", json.dumps(payload).lower())
        loop_after = self.loop_state()
        self.assertEqual(0, loop_after["totals"]["records"], "interrupted resume must not collect")
        self.assertEqual([], loop_after.get("rounds") or [])


class DecideStatusAndBriefTests(DecideHelpers, unittest.TestCase):

    def test_status_returns_c01_fields_at_every_gate(self) -> None:
        for stage in ("dry", "review"):
            if stage == "dry":
                _, start_payload = self.start_bound(decision_task(self.dir))
                task_id = start_payload["task_id"]
            else:
                task_id, _ = self.run_full(decision_task(self.dir))
            completed, payload = self.status(task_id)
            self.assertEqual(0, completed.returncode, payload)
            for field in ("next_actor", "next_required_action", "blocked_reason_code",
                          "last_updated_at", "has_pending_external_effect", "artifact_refs",
                          "state", "budget"):
                self.assertIn(field, payload, f"{stage} status missing {field}")
            self.assertTrue(payload["next_required_action"],
                            "a status without a concrete next step is not acceptable")
        # A fresh question on a fresh (unplanned) study: a dry start reports
        # `scoped` and the human gate. A task that already collected must not
        # rewind (see test_dry_start_never_rewinds_a_completed_task).
        study_b = self.dir / "study-b"
        shutil.copytree(self.study, study_b)
        for name in ("research-loop.json", "loop-candidates.json"):
            (study_b / "04-findings" / name).unlink(missing_ok=True)
        fresh = decision_task(self.dir, question="下一个问题：下一版先修哪些告警？")
        fresh_path = self.write_input(fresh, name="fresh.json")
        completed = run_cli("start", "--workspace", str(self.workspace),
                            "--input", str(fresh_path), "--study", str(study_b))
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        _, payload = self.status(json.loads(completed.stdout)["task_id"])
        self.assertEqual("scoped", payload["state"])
        self.assertIn("loop authorize", payload["next_required_action"])
        task_id, _ = self.run_full(decision_task(self.dir))
        _, payload = self.status(task_id)
        self.assertEqual("review_required", payload["state"])
        self.assertEqual("REVIEW_REQUIRED", payload["blocked_reason_code"])
        self.assertEqual("human_reviewer", payload["next_actor"])
        self.assertFalse(payload["has_pending_external_effect"])
        self.assertTrue(payload["gaps"]["total"] >= 1, "status must locate the remaining gaps")

    def test_brief_is_partial_and_lists_gaps_without_fabrication(self) -> None:
        task_id, _ = self.run_full(decision_task(self.dir))
        completed = run_cli("brief", task_id, "--workspace", str(self.workspace), "--format", "json")
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        brief = json.loads(completed.stdout)
        self.assertEqual("partial", brief["artifact_status"])
        self.assertEqual("ARTIFACT_PARTIAL", brief["reason_code"])
        self.assertTrue(brief["gaps"], "a partial brief must list its gaps")
        self.assertEqual("not_approved", brief["decision_state"],
                         "delivered research never means decision_approved")
        self.assertIn("boundary", brief)
        refs = json.dumps(brief["canonical_refs"])
        self.assertIn("product-reasoning.json", refs)
        task = json.loads((self.workspace / "tasks" / task_id / "task.json")
                          .read_text(encoding="utf-8"))
        self.assertEqual("brief_ready", task["state"])
        self.assertTrue((self.workspace / "tasks" / task_id / "brief.md").is_file())

    def test_review_and_delta_are_explicit_stubs(self) -> None:
        _, payload = self.start_bound(decision_task(self.dir))
        task_id = payload["task_id"]
        for action in ("review", "delta"):
            completed = run_cli(action, task_id, "--workspace", str(self.workspace),
                                "--by", "owner", "--since", "latest-accepted")
            self.assertEqual(2, completed.returncode, action)
            body = json.loads(completed.stdout)
            self.assertEqual("UNSUPPORTED_SCOPE", body["reason_code"], action)
            self.assertIn("后续工单", body["reason"])
            self.assertNotEqual("ok", body.get("status"))


class DecideMcpTests(DecideHelpers, unittest.TestCase):

    def test_mcp_start_status_and_result_share_the_orchestrator(self) -> None:
        task = decision_task(self.dir)
        task_id, _ = self.run_full(task)
        responses = run_mcp(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
             "params": {"name": "askovo_decide_status",
                        "arguments": {"workspace": str(self.workspace), "task_id": task_id}}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "askovo_decide_result",
                        "arguments": {"workspace": str(self.workspace), "task_id": task_id}}},
        )
        status_payload = tool_payload(responses[0])
        self.assertEqual(0, status_payload["exit_code"])
        self.assertEqual("review_required", status_payload["result"]["state"])
        for field in ("next_actor", "next_required_action", "blocked_reason_code",
                      "has_pending_external_effect", "artifact_refs"):
            self.assertIn(field, status_payload["result"])
        result_payload = tool_payload(responses[1])
        self.assertEqual(0, result_payload["exit_code"])
        result = result_payload["result"]
        self.assertEqual("partial", result["artifact_status"])
        for section in ("brief", "evidence_index", "validation_backlog",
                        "canonical_refs", "review_status"):
            self.assertIn(section, result)
        self.assertTrue(result["validation_backlog"])

    def test_mcp_start_creates_draft_and_refuses_unsupported_scope(self) -> None:
        good = decision_task(self.dir)
        bad = decision_task(self.dir, decision_type="market_sizing")
        workspace_b = self.dir / "decide-workspace-b"
        responses = run_mcp(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
             "params": {"name": "askovo_decide_start",
                        "arguments": {"workspace": str(workspace_b), "task": good}}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "askovo_decide_start",
                        "arguments": {"workspace": str(workspace_b), "task": bad, "run": True}}},
        )
        first = tool_payload(responses[0])
        self.assertEqual(0, first["exit_code"], first)
        self.assertIn(first["result"]["state"], {"scoped", "needs_input"})
        self.assertFalse(first["result"]["has_pending_external_effect"])
        second = tool_payload(responses[1])
        self.assertEqual(2, second["exit_code"])
        self.assertEqual("UNSUPPORTED_SCOPE", second["result"]["reason_code"])


if __name__ == "__main__":
    unittest.main()
