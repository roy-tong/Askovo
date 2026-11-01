#!/usr/bin/env python3
"""Research Loop: gap detection, authorized envelope, bounded rounds and candidates."""
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


def run_mcp(*requests: dict) -> list[dict]:
    lines = "\n".join(json.dumps(request) for request in requests) + "\n"
    completed = subprocess.run([sys.executable, str(MCP_SERVER)], input=lines,
                               check=False, capture_output=True, text=True, timeout=180)
    return [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]


def tool_payload(response: dict) -> dict:
    return json.loads(response["result"]["content"][0]["text"])


class ResearchLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.study = self.dir / "study"
        shutil.copytree(SAMPLE, self.study)

    # -- helpers ---------------------------------------------------------- #

    def write_study(self, *, allowed=("github",), gap="two", break_design=False) -> None:
        study_json = self.study / "study.json"
        data = json.loads(study_json.read_text(encoding="utf-8"))
        data["scope"]["allowed_sources"] = list(allowed)
        if "github" in allowed:
            data["research_loop"] = {"fixtures": {"github": "01-sources/authorized/export.jsonl"}}
            auth = self.study / "01-sources" / "authorized"
            auth.mkdir(parents=True, exist_ok=True)
            rows = [
                {"id": "l1", "title": "privacy of a roaming check",
                 "text": "I would not let a camera roam my home while I am away; privacy matters more.",
                 "url": "https://github.com/o/r/issues/10", "author": "u1",
                 "created_at": "2026-02-01", "claim_type": "commercial", "evidence_form": "self_report"},
                {"id": "l2", "title": "sitter already covers this",
                 "text": "We already pay a sitter; another subscription is hard to justify.",
                 "url": "https://github.com/o/r/issues/11", "author": "u2",
                 "created_at": "2026-02-02", "claim_type": "commercial", "evidence_form": "self_report"},
            ]
            (auth / "export.jsonl").write_text(
                "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        if break_design:
            data["decision"]["question"] = "待确认"
        study_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        if gap in ("one", "two"):
            judgments_path = self.study / "04-findings" / "demand-judgments.json"
            judgments = json.loads(judgments_path.read_text(encoding="utf-8"))
            entry = {
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
                "commercial_evidence_ids": ["R04", "R06"] if gap == "one" else [],
                "counter_evidence_ids": ["R05"] if gap == "one" else [],
                "status": "hypothesis",
                "confidence": "low",
                "gaps": ["No paid-behavior evidence"],
                "next_test": "Offer a paid pilot",
            }
            judgments.append(entry)
            judgments_path.write_text(json.dumps(judgments, ensure_ascii=False, indent=2),
                                      encoding="utf-8")

    def plan(self, *extra: str) -> tuple[subprocess.CompletedProcess, dict]:
        completed = run_cli("loop", "plan", str(self.study), *extra)
        return completed, json.loads(completed.stdout)

    def authorize(self, by: str = "tester") -> subprocess.CompletedProcess:
        return run_cli("loop", "authorize", str(self.study), "--by", by)

    # -- tests ------------------------------------------------------------ #

    def test_plan_reports_gaps_sources_and_envelope(self) -> None:
        self.write_study(gap="two")
        completed, payload = self.plan()
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertEqual("planned", payload["status"])
        self.assertFalse(payload["envelope"]["allowed_platforms"] == [])
        self.assertEqual(["github"], payload["envelope"]["allowed_platforms"])
        self.assertEqual("fixture", payload["envelope"]["platform_modes"]["github"])
        self.assertGreaterEqual(payload["gaps"]["actionable"], 2)
        self.assertTrue((self.study / "04-findings" / "research-loop.json").is_file())

    def test_plan_twice_requires_reset(self) -> None:
        self.write_study(gap="two")
        self.plan()
        completed, payload = self.plan()
        self.assertEqual(2, completed.returncode)
        self.assertIn("already exists", payload["reason"])
        completed, payload = self.plan("--reset")
        self.assertEqual(0, completed.returncode, completed.stdout)

    def test_run_without_authorization_is_refused(self) -> None:
        self.write_study(gap="two")
        self.plan()
        completed = run_cli("loop", "run", str(self.study))
        self.assertEqual(4, completed.returncode, completed.stdout)
        self.assertIn("not authorized", json.loads(completed.stdout)["reason"])

    def test_authorized_run_collects_candidates_and_writes_report(self) -> None:
        self.write_study(gap="two")
        self.plan()
        authorized = self.authorize()
        self.assertEqual(0, authorized.returncode, authorized.stdout + authorized.stderr)

        completed = run_cli("loop", "run", str(self.study))
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        status = json.loads(completed.stdout)
        self.assertTrue(status["authorized"])
        self.assertGreaterEqual(status["totals"]["records"], 1)
        self.assertGreaterEqual(status["candidates"], 1)
        self.assertIn(status["status"], {"completed", "blocked"})

        candidates_path = self.study / "04-findings" / "loop-candidates.json"
        self.assertTrue(candidates_path.is_file())
        candidates = json.loads(candidates_path.read_text(encoding="utf-8"))["candidates"]
        self.assertGreaterEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual("proposed", candidate["status"])
        self.assertIsNone(candidate["proposed_evidence_level"])
        self.assertTrue(candidate["record_ids"])

        report = run_cli("loop", "report", str(self.study))
        self.assertEqual(0, report.returncode, report.stdout + report.stderr)
        report_payload = json.loads(report.stdout)
        markdown = Path(report_payload["path"]).read_text(encoding="utf-8")
        self.assertIn("已验证结论", markdown)
        self.assertIn("未验证假设", markdown)
        self.assertIn("候选证据", markdown)
        self.assertIn("边界", markdown)
        boundary = json.loads(candidates_path.read_text(encoding="utf-8"))["boundary"]
        self.assertIn("never assigns an evidence level", boundary)

    def test_single_gap_run_stops_awaiting_semantic_review(self) -> None:
        self.write_study(gap="one")
        self.plan()
        self.authorize()
        completed = run_cli("loop", "run", str(self.study))
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        status = json.loads(completed.stdout)
        self.assertEqual("completed", status["status"])
        self.assertEqual("awaiting_semantic_review", status["stop_reason"])
        self.assertEqual(1, status["candidates"])

    def test_envelope_tamper_invalidates_authorization(self) -> None:
        self.write_study(gap="two")
        self.plan()
        self.authorize()
        state_path = self.study / "04-findings" / "research-loop.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["envelope"]["allowed_platforms"] = []
        state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        completed = run_cli("loop", "run", str(self.study))
        self.assertEqual(4, completed.returncode, completed.stdout)
        self.assertIn("stale", json.loads(completed.stdout)["reason"])

    def test_design_gate_blocks_collection(self) -> None:
        self.write_study(gap="two", break_design=True)
        self.plan()
        self.authorize()
        completed = run_cli("loop", "run", str(self.study))
        self.assertEqual(1, completed.returncode, completed.stdout)
        self.assertEqual("design_gate_failed", json.loads(completed.stdout)["status"])
        self.assertFalse((self.study / "02-data" / "normalized.jsonl").is_file())

    def test_platform_without_adapter_is_not_actionable(self) -> None:
        self.write_study(allowed=("youtube",), gap="two")
        completed, payload = self.plan()
        self.assertEqual(0, completed.returncode, completed.stdout)
        self.assertEqual([], payload["envelope"]["allowed_platforms"])
        self.assertEqual(0, payload["gaps"]["actionable"])
        self.assertIn("blocked_source", payload["gaps"]["by_kind"])
        self.authorize()
        run = run_cli("loop", "run", str(self.study))
        self.assertEqual(3, run.returncode, run.stdout)
        status = json.loads(run.stdout)
        self.assertEqual("blocked", status["status"])
        self.assertEqual("no_actionable_source", status["stop_reason"])

    def test_interrupted_state_requires_review_before_rerun(self) -> None:
        self.write_study(gap="two")
        self.plan()
        self.authorize()
        state_path = self.study / "04-findings" / "research-loop.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["status"] = "running"
        state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        first = run_cli("loop", "run", str(self.study))
        self.assertEqual(3, first.returncode, first.stdout)
        self.assertEqual("needs_review", json.loads(first.stdout)["status"])
        second = run_cli("loop", "run", str(self.study))
        self.assertEqual(3, second.returncode, second.stdout)

    def test_loop_never_edits_judgments(self) -> None:
        self.write_study(gap="two")
        judgments = self.study / "04-findings" / "demand-judgments.json"
        before = judgments.read_bytes()
        self.plan()
        self.authorize()
        completed = run_cli("loop", "run", str(self.study))
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertEqual(before, judgments.read_bytes())

    def test_mcp_exposes_loop_and_never_authorizes(self) -> None:
        self.write_study(gap="two")
        self.plan()
        responses = run_mcp(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                        "clientInfo": {"name": "test", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "askovo_research_loop",
                        "arguments": {"study_dir": str(self.study), "action": "run"}}},
        )
        by_id = {response.get("id"): response for response in responses}
        names = {tool["name"] for tool in by_id[2]["result"]["tools"]}
        self.assertIn("askovo_research_loop", names)
        result = tool_payload(by_id[3])
        self.assertEqual(4, result["exit_code"])
        self.assertIn("not authorized", result["result"]["reason"])


if __name__ == "__main__":
    unittest.main()
