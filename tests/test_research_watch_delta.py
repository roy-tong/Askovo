from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "examples/sample-study"
SCRIPTS = ROOT / "skills/askovo/scripts"
sys.path.insert(0, str(SCRIPTS))

import research_watch  # noqa: E402


def issue(number=1, title="Nested log failure"):
    return {
        "id": 10000 + number, "number": number, "title": title,
        "body": "Nested logs fail and we retry by hand every week.", "state": "open",
        "html_url": "https://github.com/owner/repo/issues/%d" % number,
        "user": {"login": "alice", "id": 501}, "author_association": "NONE",
        "created_at": "2026-11-01T10:00:00Z", "updated_at": "2026-11-01T10:00:00Z",
        "labels": [], "comments": [], "visibility": "public",
    }


class ResearchWatchDeltaTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.study = self.root / "study"
        shutil.copytree(SAMPLE, self.study)
        self.export = self.root / "issues.jsonl"
        self.export.write_text(json.dumps(issue()) + "\n", encoding="utf-8")

    def create(self):
        return research_watch.create(
            self.study, question="Track issue changes", interval_hours=24, owner="research-owner",
            delta_file=str(self.export), delta_authorized_by="data-owner",
            now="2026-11-25T00:00:00+00:00")

    def versions(self):
        path = self.study / "04-findings/deltas/index.jsonl"
        return path.read_text(encoding="utf-8").splitlines() if path.is_file() else []

    def test_due_watch_syncs_local_delta_then_reviews_without_promoting_evidence(self):
        self.create()
        first = research_watch.run_due(self.study, now="2026-11-25T00:00:00+00:00")["runs"][0]
        self.assertEqual("local_authorized_delta_and_review", first["execution"])
        self.assertTrue(first["delta"]["has_changes"])
        self.assertTrue(first["new_source_snapshot_created"])
        self.assertFalse(first["canonical_evidence_promoted"])
        self.assertFalse(first["decision_mutated"])
        self.assertEqual(1, len(self.versions()))
        second = research_watch.run_due(self.study, now="2026-11-26T00:00:00+00:00")["runs"][0]
        self.assertTrue(second["delta"]["noop"])
        self.assertFalse(second["new_source_snapshot_created"])
        self.assertFalse(second["source_changed_since_last_run"])
        self.assertEqual(1, len(self.versions()))
        self.export.write_text(json.dumps(issue()) + "\n" + json.dumps(issue(2, "Second issue")) + "\n",
                               encoding="utf-8")
        third = research_watch.run_due(self.study, now="2026-11-27T00:00:00+00:00")["runs"][0]
        self.assertTrue(third["delta"]["has_changes"])
        self.assertTrue(third["source_changed_since_last_run"])
        self.assertEqual(2, len(self.versions()))

    def test_delta_failure_keeps_watch_needs_attention_even_if_old_review_runs(self):
        self.create()
        self.export.unlink()
        result = research_watch.run_due(self.study, now="2026-11-25T00:00:00+00:00")
        self.assertEqual("failed", result["status"])
        run = result["runs"][0]
        self.assertEqual("failed", run["delta"]["status"])
        self.assertIn(run["review_status"], {"pass", "needs_work", "fail", "not_completed"})
        status = research_watch.status(self.study, now="2026-11-25T00:00:00+00:00")
        self.assertTrue(status["watches"][0]["needs_attention"])

    def test_delta_file_and_authorizer_are_required_together(self):
        with self.assertRaisesRegex(ValueError, "together"):
            research_watch.create(
                self.study, question="Incomplete delta config", interval_hours=24,
                owner="research-owner", delta_file=str(self.export),
                now="2026-11-25T00:00:00+00:00")

    def test_cli_create_and_run_authorized_delta_watch(self):
        cli = ROOT / "skills/askovo/scripts/askovo.py"
        created = subprocess.run([
            sys.executable, str(cli), "watch", "create", str(self.study),
            "--question", "Track CLI issue changes", "--interval-hours", "24", "--by", "owner",
            "--delta-file", str(self.export), "--delta-authorized-by", "data-owner",
            "--now", "2026-11-25T00:00:00+00:00",
        ], text=True, capture_output=True)
        self.assertEqual(0, created.returncode, created.stdout + created.stderr)
        ran = subprocess.run([
            sys.executable, str(cli), "watch", "run", str(self.study),
            "--now", "2026-11-25T00:00:00+00:00",
        ], text=True, capture_output=True)
        self.assertEqual(0, ran.returncode, ran.stdout + ran.stderr)
        run = json.loads(ran.stdout)["runs"][0]
        self.assertEqual("local_authorized_delta_and_review", run["execution"])
        self.assertTrue(run["new_source_snapshot_created"])


if __name__ == "__main__":
    unittest.main()
