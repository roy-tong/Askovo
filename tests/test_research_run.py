#!/usr/bin/env python3
"""Research Run: authorized actions, bounded execution and hash-bound state."""
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


def run_cli(*args):
    return subprocess.run([sys.executable, str(CLI), *args],
                          capture_output=True, text=True)


class ResearchRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.study = self.dir / "study"
        shutil.copytree(SAMPLE, self.study)
        study_json = self.study / "study.json"
        data = json.loads(study_json.read_text(encoding="utf-8"))
        data["scope"]["allowed_sources"] = ["github"]
        study_json.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        auth = self.study / "01-sources" / "authorized"
        auth.mkdir(parents=True, exist_ok=True)
        self.fixture = auth / "export.jsonl"
        self.fixture.write_text(json.dumps({
            "id": "x1", "title": "billing issue", "text": "billing is confusing",
            "url": "https://github.com/o/r/issues/1", "author": "a",
            "created_at": "2026-01-01", "claim_type": "need",
            "evidence_form": "self_report",
        }) + "\n", encoding="utf-8")

    def actions(self, **over):
        data = {
            "schema_version": "1.0", "run_id": "run-test",
            "actions": [{
                "id": "A1", "node": "pain", "platform": "github",
                "query": "billing", "limit": 1,
                "fixture": "01-sources/authorized/export.jsonl",
            }],
        }
        data["actions"][0].update(over)
        path = self.dir / "actions.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_plan_then_authorized_run_and_status(self):
        actions = self.actions()
        planned = run_cli("research", "plan", str(self.study), "--actions", str(actions))
        self.assertEqual(0, planned.returncode, planned.stdout + planned.stderr)
        state = json.loads(planned.stdout)
        self.assertIsNone(state["authorization"])
        self.assertEqual("planned", state["status"])

        unauthorized = run_cli("research", "run", str(self.study))
        self.assertEqual(4, unauthorized.returncode, unauthorized.stdout + unauthorized.stderr)
        self.assertIn("not authorized", unauthorized.stdout)

        done = run_cli("research", "run", str(self.study), "--authorize", "--by", "researcher")
        self.assertEqual(0, done.returncode, done.stdout + done.stderr)
        self.assertEqual("completed", json.loads(done.stdout)["status"])
        status = run_cli("research", "status", str(self.study))
        self.assertEqual(0, status.returncode, status.stdout + status.stderr)
        payload = json.loads(status.stdout)
        self.assertTrue(payload["authorized"])
        self.assertEqual({"completed": 1}, payload["counts"])
        self.assertTrue((self.study / "02-data" / "raw" / "github").exists())
        self.assertTrue((self.study / "01-sources" / "manifests").exists())

    def test_action_platform_must_be_in_study_scope(self):
        actions = self.actions(platform="reddit")
        done = run_cli("research", "plan", str(self.study), "--actions", str(actions))
        self.assertEqual(2, done.returncode, done.stdout + done.stderr)
        self.assertIn("allowed_sources", done.stdout)

    def test_fixture_must_stay_inside_study(self):
        outside = self.dir / "outside.jsonl"
        outside.write_text("{}\n", encoding="utf-8")
        actions = self.actions(fixture=str(outside))
        done = run_cli("research", "plan", str(self.study), "--actions", str(actions))
        self.assertEqual(2, done.returncode, done.stdout + done.stderr)
        self.assertIn("inside the study", done.stdout)

    def test_changed_actions_require_a_new_plan_or_reset(self):
        actions = self.actions()
        self.assertEqual(0, run_cli("research", "plan", str(self.study),
                                    "--actions", str(actions)).returncode)
        self.assertEqual(0, run_cli("research", "run", str(self.study),
                                    "--authorize", "--by", "a").returncode)
        changed = self.actions(query="different")
        stale = run_cli("research", "run", str(self.study), "--actions", str(changed))
        self.assertEqual(2, stale.returncode, stale.stdout + stale.stderr)
        self.assertIn("differs", stale.stdout)
        reset = run_cli("research", "plan", str(self.study), "--actions", str(changed),
                        "--reset")
        self.assertEqual(0, reset.returncode, reset.stdout + reset.stderr)
        self.assertIsNone(json.loads(reset.stdout)["authorization"])

    def test_max_steps_and_analysis(self):
        second = self.study / "01-sources" / "authorized" / "second.jsonl"
        shutil.copy(self.fixture, second)
        actions = self.actions()
        data = json.loads(actions.read_text(encoding="utf-8"))
        data["actions"].append({
            "id": "A2", "node": "need", "platform": "github", "query": "billing",
            "limit": 1, "fixture": "01-sources/authorized/second.jsonl",
        })
        actions.write_text(json.dumps(data), encoding="utf-8")
        first = run_cli("research", "run", str(self.study), "--actions", str(actions),
                        "--authorize", "--by", "a", "--max-steps", "1")
        self.assertEqual(0, first.returncode, first.stdout + first.stderr)
        payload = json.loads(first.stdout)
        self.assertEqual({"pending": 1, "completed": 1}, payload["counts"])
        second_run = run_cli("research", "run", str(self.study), "--max-steps", "1",
                             "--analyze")
        self.assertEqual(0, second_run.returncode, second_run.stdout + second_run.stderr)
        payload = json.loads(second_run.stdout)
        self.assertEqual("completed", payload["status"])
        self.assertTrue(payload["analysis"])


if __name__ == "__main__":
    unittest.main()
