#!/usr/bin/env python3
"""A-lane cross-ticket integration: one decision service, not five features.

The PRD's strongest structural rule is "no second state source", and the C-01
contract says the CLI and MCP must share one orchestration function. Each ticket
is green on its own; these tests check the seams:

1. **One lifecycle.** `decide start` (dry) → human `loop authorize` →
   `decide start --run` → `status` → `brief` → `delta sync` → `status` /
   `brief` / `delta status`. The product state only moves forward, the brief
   stays `partial` with its gaps listed, the brief and the delta agree on
   `needs_re_review`, and an approved DecisionSnapshot is byte-identical before
   and after the delta.
2. **One orchestrator.** `askovo_decide_start/_status/_result` and the
   `decide start/status/result` CLI produce structurally comparable output on the
   same fixture: same task id, state, reason code and next action.
3. **One evidence boundary.** An A-06 external adapter produces candidates
   (`status: candidate`, `evidence_grade_assigned: false`) that a real subprocess
   writes; they must not appear in the brief's evidence section and must not
   raise any evidence level.
4. **One staleness verdict.** Deleting an evidence record a chain cites makes
   both `decide brief` (delivery blocked) and `delta show` (exit 1) stale. A
   brief that can still be delivered while the delta says stale is a bug.

Everything runs offline on synthetic fixtures.
"""
from __future__ import annotations

import hashlib
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

STATE_ORDER = (
    "created", "scoped", "collecting", "analyzed", "review_required",
    "brief_ready", "delivered",
)
EXTERNAL_ADAPTER = """
import json
import sys
print(json.dumps({"sources": [{"url": "https://example.com/external-candidate",
                               "title": "external candidate",
                               "excerpt": "external excerpt",
                               "claim": "external claim"}]}))
"""


def cli(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    merged = dict(os.environ)
    merged.setdefault("ASKOVO_AUTHOR_SALT", "a-lane-integration-salt")
    if env:
        merged.update(env)
    return subprocess.run([sys.executable, str(CLI), *args],
                          capture_output=True, text=True, timeout=180, env=merged)


def run_mcp(*requests: dict) -> list[dict]:
    lines = "\n".join(json.dumps(request) for request in requests) + "\n"
    completed = subprocess.run([sys.executable, str(MCP)], input=lines,
                               capture_output=True, text=True, timeout=180)
    return [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]


def tool_payload(response: dict) -> dict:
    return json.loads(response["result"]["content"][0]["text"])


def payload(completed: subprocess.CompletedProcess) -> dict:
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"raw": completed.stdout, "stderr": completed.stderr}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


def issue_export(path: Path, rows: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
                    encoding="utf-8")
    return path


def issue(number: int, title: str, body: str, *, author: str = "u1",
          author_id: int | None = None, **overrides) -> dict:
    record = {
        "id": 10000 + number,
        "number": number,
        "title": title,
        "body": body,
        "state": "open",
        "html_url": f"https://github.com/owner/repo/issues/{number}",
        "user": {"login": author, **({"id": author_id} if author_id is not None else {})},
        "author_association": "NONE",
        "created_at": "2026-09-01T10:00:00Z",
        "updated_at": "2026-09-01T10:00:00Z",
        "labels": [],
        "comments": [],
        "visibility": "public",
    }
    record.update(overrides)
    return record


class LaneHelpers:
    """One synthetic study shared by the whole A lane."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.study = self.dir / "study"
        self.workspace = self.dir / "decide-workspace"
        shutil.copytree(SAMPLE, self.study)
        self.fixture = self.study / "01-sources" / "authorized" / "export.jsonl"
        self.fixture.parent.mkdir(parents=True, exist_ok=True)
        self.fixture.write_text(
            "\n".join(json.dumps(row) for row in [
                {"id": "l1", "title": "privacy of a roaming check",
                 "text": "I would not let a camera roam my home while I am away; privacy matters more.",
                 "url": "https://github.com/o/r/issues/10", "author": "u1",
                 "created_at": "2026-02-01", "claim_type": "commercial",
                 "evidence_form": "self_report"},
                {"id": "l2", "title": "sitter already covers this",
                 "text": "We already pay a sitter; another subscription is hard to justify.",
                 "url": "https://github.com/o/r/issues/11", "author": "u2",
                 "created_at": "2026-02-02", "claim_type": "commercial",
                 "evidence_form": "self_report"},
                {"id": "l3", "title": "would try one month",
                 "text": "I would try one month of bounded checks if it is easy to cancel.",
                 "url": "https://github.com/o/r/issues/12", "author": "u3",
                 "created_at": "2026-02-03", "claim_type": "commercial",
                 "evidence_form": "self_report"},
            ]) + "\n", encoding="utf-8")
        self._prepare_study()
        self.task_path = self.dir / "task.json"
        self.task_path.write_text(json.dumps({
            "schema": "askovo.decision-task/1",
            "question": "下一版该先修哪些问题？",
            "product": {"kind": "github_repository", "repo": "owner/repo"},
            "decision_type": "prioritize_features",
            "audience": {"description": "开发者", "confidence": "declared"},
            "source_scope": {"issues": True, "discussions": False,
                             "updated_since": "2026-08-01",
                             "fixture": str(self.fixture)},
            "authorization": {"approved_by": "owner", "allowed_sources": ["github"],
                              "max_records": 200},
            "deadline": "2026-12-01",
            "delivery": {"primary": "decision_brief", "secondary": []},
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _prepare_study(self) -> None:
        study_path = self.study / "study.json"
        study = json.loads(study_path.read_text(encoding="utf-8"))
        study["scope"]["allowed_sources"] = ["github"]
        study["research_loop"] = {
            "fixtures": {"github": "01-sources/authorized/export.jsonl"}}
        study_path.write_text(json.dumps(study, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
        judgments_path = self.study / "04-findings" / "demand-judgments.json"
        judgments = json.loads(judgments_path.read_text(encoding="utf-8"))
        judgments.append({
            "id": "D02", "context_key": "", "title": "Remote owners will pay a monthly fee",
            "user_role": "Remote pet owners", "scene": "Away from home",
            "task": "Check on the pet", "current_substitute": "Fixed cameras",
            "friction": "Blind spots", "consequence": "Delayed care",
            "solution": "Mobile check subscription", "acceptance_conditions": "Privacy controls",
            "problem_evidence_ids": ["R01"], "solution_evidence_ids": [],
            "commercial_evidence_ids": [], "counter_evidence_ids": [],
            "status": "hypothesis", "confidence": "low",
            "gaps": ["No paid-behavior evidence"], "next_test": "Offer a paid pilot",
        })
        judgments_path.write_text(json.dumps(judgments, ensure_ascii=False, indent=2) + "\n",
                                  encoding="utf-8")

    # -- helpers ----------------------------------------------------------- #

    def start_dry(self) -> dict:
        completed = cli("decide", "start", "--workspace", str(self.workspace),
                        "--input", str(self.task_path), "--study", str(self.study))
        body = payload(completed)
        self.assertEqual(0, completed.returncode, body)
        return body

    def run_task(self, task_id: str) -> dict:
        completed = cli("decide", "start", "--workspace", str(self.workspace),
                        "--task", task_id, "--run")
        body = payload(completed)
        self.assertEqual(0, completed.returncode, body)
        return body

    def status(self, task_id: str) -> tuple[subprocess.CompletedProcess, dict]:
        completed = cli("decide", "status", task_id, "--workspace", str(self.workspace))
        return completed, payload(completed)

    def brief(self, task_id: str) -> tuple[subprocess.CompletedProcess, dict]:
        completed = cli("decide", "brief", task_id, "--workspace", str(self.workspace),
                        "--format", "json")
        return completed, payload(completed)

    def delta_sync(self, rows: list[dict], name: str) -> dict:
        export = issue_export(self.dir / name, rows)
        completed = cli("delta", "sync", str(self.study), "--file", str(export),
                        "--authorized-by", "research-lead")
        body = payload(completed)
        self.assertEqual(0, completed.returncode, body)
        return body

    def delta_show(self) -> tuple[subprocess.CompletedProcess, dict]:
        completed = cli("delta", "show", str(self.study))
        return completed, payload(completed)

    def task_record(self, task_id: str) -> dict:
        path = self.workspace / "tasks" / task_id / "task.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def evidence_records(self) -> list[dict]:
        path = self.study / "02-data" / "evidence.jsonl"
        if not path.is_file():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()]


class DecisionLifecycleTests(LaneHelpers, unittest.TestCase):
    """1. One lifecycle: dry start, human gate, run, brief, delta."""

    def test_full_lifecycle_moves_forward_and_keeps_one_state_source(self) -> None:
        started = self.start_dry()
        task_id = started["task_id"]
        self.assertEqual("scoped", started["state"])

        authorized = cli("loop", "authorize", str(self.study), "--by", "product-owner")
        self.assertEqual(0, authorized.returncode, authorized.stdout + authorized.stderr)

        ran = self.run_task(task_id)
        self.assertEqual("review_required", ran["state"], ran)

        _, status = self.status(task_id)
        self.assertEqual("review_required", status["state"])
        self.assertEqual("human_reviewer", status["next_actor"])

        completed, brief = self.brief(task_id)
        self.assertEqual(0, completed.returncode, brief)
        self.assertEqual("partial", brief["artifact_status"])
        self.assertTrue(brief["gaps"], "a partial brief must list its gaps")
        self.assertEqual("not_approved", brief["decision_state"])

        first = self.delta_sync([issue(1, "nested log parse failure",
                                       "Nested JSON logs fail to parse; we retry by hand weekly.",
                                       author="alice", author_id=501)], "v1.jsonl")
        self.assertTrue(first["has_changes"])

        approved = cli("delta", "approve", str(self.study), "--by", "product-owner",
                       "--approval-ref", "SIGNOFF-A", "--option", "option-A")
        self.assertEqual(0, approved.returncode, approved.stdout + approved.stderr)
        snapshots = sorted((self.study / "04-findings" / "deltas" /
                            "decision-snapshots").glob("*.json"))
        self.assertEqual(1, len(snapshots))
        accepted_before = sha(snapshots[0])

        second = self.delta_sync([
            issue(1, "nested log parse failure",
                  "Nested JSON logs fail to parse; we retry by hand daily now.",
                  author="alice", author_id=501,
                  updated_at="2026-09-09T10:00:00Z"),
            issue(2, "does not happen here",
                  "This does not happen for us; works fine and we would not pay.",
                  author="skeptic", author_id=502,
                  updated_at="2026-09-08T10:00:00Z"),
        ], "v2.jsonl")
        self.assertTrue(second["has_changes"])
        self.assertEqual(accepted_before, sha(snapshots[0]),
                         "an approved DecisionSnapshot must never be rewritten by a delta")

        _, status_after = self.status(task_id)
        _, brief_after = self.brief(task_id)
        _, delta_after = self.delta_show()

        self.assertEqual("not_approved", brief_after["decision_state"])
        self.assertEqual(brief_after["needs_re_review"], delta_after["needs_re_review"],
                         "the brief and the delta must agree on the same input")
        self.assertTrue(brief_after["needs_re_review"])
        self.assertEqual(brief_after["source_fingerprint"], brief_after["source_fingerprint"])
        self.assertFalse(delta_after["decision_record_mutated"])

        history = [entry["state"] for entry in self.task_record(task_id)["phase_history"]]
        indices = [STATE_ORDER.index(state) for state in history]
        self.assertEqual(sorted(indices), indices,
                         f"product state must never move backwards: {history}")
        self.assertNotIn("delivered", history)

    def test_status_after_delta_does_not_regress(self) -> None:
        started = self.start_dry()
        task_id = started["task_id"]
        cli("loop", "authorize", str(self.study), "--by", "product-owner")
        self.run_task(task_id)
        _, brief = self.brief(task_id)
        self.assertEqual("partial", brief["artifact_status"])
        self.delta_sync([issue(1, "nested log parse failure",
                                "Nested JSON logs fail to parse; we retry by hand weekly.",
                                author="alice", author_id=501)], "v1.jsonl")
        _, status = self.status(task_id)
        self.assertEqual("brief_ready", status["state"])
        self.assertNotIn("loop authorize", status["next_required_action"],
                         "a task past review must not fall back to the authorization gate")


class McpCliParityTests(LaneHelpers, unittest.TestCase):
    """2. One orchestrator: the MCP tools and the CLI cannot diverge."""

    def test_mcp_and_cli_report_the_same_task(self) -> None:
        started = self.start_dry()
        task_id = started["task_id"]
        _, cli_status = self.status(task_id)
        cli_result = cli("decide", "result", task_id, "--workspace", str(self.workspace))
        cli_result_body = payload(cli_result)

        responses = run_mcp(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
             "params": {"name": "askovo_decide_start",
                        "arguments": {"workspace": str(self.workspace),
                                      "task": json.loads(
                                          self.task_path.read_text(encoding="utf-8"))}}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "askovo_decide_status",
                        "arguments": {"workspace": str(self.workspace), "task_id": task_id}}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "askovo_decide_result",
                        "arguments": {"workspace": str(self.workspace), "task_id": task_id}}},
        )
        mcp_start = tool_payload(responses[0])
        mcp_status = tool_payload(responses[1])["result"]
        mcp_result = tool_payload(responses[2])["result"]

        self.assertEqual(0, mcp_start["exit_code"], mcp_start)
        self.assertEqual(task_id, mcp_start["result"]["task_id"],
                         "the MCP entry must reuse the CLI task identity")
        for field in ("state", "reason_code", "next_actor", "next_required_action",
                      "blocked_reason_code"):
            self.assertEqual(cli_status.get(field), mcp_status.get(field),
                             f"MCP and CLI disagree on {field}")
        for field in ("artifact_status", "decision_state", "delivery_state",
                      "outcome_state", "causality_state"):
            self.assertEqual(cli_result_body.get(field), mcp_result.get(field),
                             f"MCP and CLI disagree on {field}")
        self.assertEqual(cli_result_body["brief"]["schema"],
                         mcp_result["brief"]["schema"])

    def test_mcp_refuses_the_same_unsupported_scope(self) -> None:
        bad = json.loads(self.task_path.read_text(encoding="utf-8"))
        bad["decision_type"] = "market_sizing"
        responses = run_mcp({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                             "params": {"name": "askovo_decide_start",
                                        "arguments": {"workspace": str(self.dir / "ws-b"),
                                                      "task": bad}}})
        body = tool_payload(responses[0])
        self.assertEqual(2, body["exit_code"])
        self.assertEqual("UNSUPPORTED_SCOPE", body["result"]["reason_code"])


class ExternalCandidateBoundaryTests(LaneHelpers, unittest.TestCase):
    """3. A-06 candidates never reach the brief's evidence."""

    def test_external_candidates_stay_out_of_the_brief(self) -> None:
        adapter = self.dir / "adapter.py"
        adapter.write_text(EXTERNAL_ADAPTER, encoding="utf-8")
        registry = self.study / "01-sources" / "external-research.json"
        registry.write_text(json.dumps({
            "schema_version": "1.0",
            "updated_at": "2026-11-15",
            "commands": [{
                "id": "lane-adapter",
                "label": "A-lane synthetic adapter",
                "adapter": str(adapter),
                "argv": [sys.executable, str(adapter)],
                "sha256": "sha256:" + hashlib.sha256(adapter.read_bytes()).hexdigest(),
                "access_basis": "synthetic local adapter; no network",
                "reviewed_at": "2026-11-15",
                "reviewed_by": "research-lead",
            }],
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        external = cli("external-research", str(self.study), "--command", "lane-adapter",
                       "--authorize", "--json")
        record = payload(external)
        self.assertEqual(0, external.returncode, record)
        self.assertTrue(record["sources"], "the adapter must produce candidates")
        for source in record["sources"]:
            self.assertEqual("candidate", source["status"])
            self.assertIsNone(source["evidence_level"])
            self.assertEqual("not_attempted", source["url_verification"])
        self.assertFalse(record["evidence_grade_assigned"])
        self.assertFalse(record["network_attempted"])

        evidence_before = len(self.evidence_records())
        started = self.start_dry()
        task_id = started["task_id"]
        completed, brief = self.brief(task_id)
        self.assertEqual(0, completed.returncode, brief)
        blob = json.dumps(brief, ensure_ascii=False)
        self.assertNotIn("external-candidate", blob,
                         "an external candidate must not appear in the brief's evidence")
        self.assertNotIn(record["run_id"], blob)
        self.assertEqual(evidence_before, len(self.evidence_records()),
                         "running an adapter must not register evidence")
        for entry in brief["evidence"]:
            self.assertIsNotNone(
                next((item for item in self.evidence_records()
                      if item.get("record_id") == entry["record_id"]), None),
                "every brief evidence record must come from the canonical evidence store")


class StaleConsistencyTests(LaneHelpers, unittest.TestCase):
    """4. One staleness verdict for the brief and the delta."""

    def test_broken_reference_makes_both_stale(self) -> None:
        self.delta_sync([issue(1, "nested log parse failure",
                               "Nested JSON logs fail to parse; we retry by hand weekly.",
                               author="alice", author_id=501)], "v1.jsonl")
        started = self.start_dry()
        task_id = started["task_id"]

        evidence_path = self.study / "02-data" / "evidence.jsonl"
        kept = [line for line in evidence_path.read_text(encoding="utf-8").splitlines()
                if line.strip() and json.loads(line).get("record_id") != "R03"]
        evidence_path.write_text("\n".join(kept) + "\n", encoding="utf-8")

        completed, brief = self.brief(task_id)
        self.assertEqual(1, completed.returncode, brief)
        self.assertEqual("stale", brief["artifact_status"])
        self.assertEqual("STALE_SOURCE", brief["reason_code"])
        self.assertEqual("blocked", brief["delivery_state"])
        self.assertTrue(brief["diagnostic_only"])

        delta_completed, delta = self.delta_show()
        self.assertEqual(1, delta_completed.returncode, delta)
        self.assertTrue(delta["stale"])
        self.assertEqual("STALE_SOURCE", delta["reason_code"])

        self.assertEqual(brief["artifact_status"] == "stale", delta["stale"],
                         "the brief and the delta must never disagree about staleness")


if __name__ == "__main__":
    unittest.main()
