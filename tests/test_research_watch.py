from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/askovo/scripts"
CLI = SCRIPTS / "askovo.py"
SAMPLE = ROOT / "examples/sample-study"
sys.path.insert(0, str(SCRIPTS))

import research_watch  # noqa: E402
import write_integrity  # noqa: E402


class ResearchWatchTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.study = self.dir / "study"
        shutil.copytree(SAMPLE, self.study)
        self.now = "2026-11-25T00:00:00+00:00"

    def create(self) -> dict:
        return research_watch.create(
            self.study, question="Track changes for the mobile decision",
            interval_hours=24, owner="research-owner", now=self.now)

    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(CLI), *args],
                              capture_output=True, text=True, timeout=180)

    def test_create_persists_due_watch_without_collecting_evidence(self) -> None:
        created = self.create()
        self.assertEqual("askovo.research-watch/1", created["schema"])
        self.assertEqual("W001", created["watch"]["watch_id"])
        self.assertEqual(self.now, created["watch"]["next_due_at"])
        self.assertFalse(created["watch"]["new_evidence_collected"])
        status = research_watch.status(self.study, now=self.now)
        self.assertEqual(1, status["due_count"])
        self.assertTrue(status["watches"][0]["due"])

    def test_corrupt_state_is_not_replaced_with_an_empty_watch_list(self) -> None:
        self.create()
        (self.study / research_watch.STATE_RELATIVE).write_text("{", encoding="utf-8")
        with self.assertRaises(write_integrity.IntegrityError):
            research_watch.status(self.study, now=self.now)

    def test_due_run_records_review_and_source_fingerprint(self) -> None:
        self.create()
        first = research_watch.run_due(self.study, now=self.now)
        self.assertEqual("completed", first["status"])
        self.assertEqual(1, len(first["runs"]))
        self.assertEqual("local_review_only", first["runs"][0]["execution"])
        self.assertFalse(first["runs"][0]["new_evidence_collected"])
        self.assertFalse(first["runs"][0]["source_changed_since_last_run"])
        not_due = research_watch.run_due(self.study, now="2026-11-25T01:00:00+00:00")
        self.assertEqual("no_due_watches", not_due["status"])
        second = research_watch.run_due(self.study, now="2026-11-26T00:00:00+00:00")
        self.assertEqual(1, len(second["runs"]))
        self.assertFalse(second["runs"][0]["source_changed_since_last_run"])
        history = (self.study / research_watch.HISTORY_RELATIVE).read_text(encoding="utf-8").splitlines()
        self.assertEqual(2, len(history))

    def test_pause_blocks_run_and_resume_schedules_due_review(self) -> None:
        self.create()
        paused = research_watch.set_paused(self.study, "W001", True, now=self.now)
        self.assertEqual("paused", paused["watch"]["state"])
        self.assertEqual("no_due_watches", research_watch.run_due(self.study, now=self.now)["status"])
        resumed = research_watch.set_paused(self.study, "W001", False, now=self.now)
        self.assertEqual("active", resumed["watch"]["state"])
        self.assertEqual(self.now, resumed["watch"]["next_due_at"])

    def test_execute_due_runs_authorized_collection_before_local_review(self) -> None:
        self.create()
        execute = getattr(research_watch, "execute_due", None)
        self.assertIsNotNone(execute)
        calls = []
        def collected(*args, **kwargs):
            calls.append("collect")
            return {"state": {"status": "completed", "actions": [
                {"id": "A1", "state": "completed", "result": {"records": 3}}]}}
        def reviewed(*args, **kwargs):
            calls.append("review")
            return {"status": "completed", "runs": [{"status": "completed"}]}
        with mock.patch("research_run.run", side_effect=collected), \
                mock.patch.object(research_watch, "run_due", side_effect=reviewed):
            result = execute(self.study, watch_id="W001", now=self.now, max_steps=1)
        self.assertEqual(["collect", "review"], calls)
        self.assertEqual("authorized_research_run_and_local_review", result["execution"])
        self.assertEqual(3, result["collection"]["records"])
        self.assertEqual(3, result["new_source_records_collected"])
        self.assertTrue(result["new_source_material_collected"])
        self.assertFalse(result["new_evidence_collected"])

    def test_serve_executes_authorized_collection_before_review(self) -> None:
        self.create()
        import research_run
        research_run.state_path(self.study).parent.mkdir(parents=True, exist_ok=True)
        research_run.state_path(self.study).write_text("{}", encoding="utf-8")
        calls = []
        def collected(*args, **kwargs):
            calls.append("collect")
            return {"new_records": 2, "state": {"status": "completed", "actions": [
                {"id": "A1", "state": "completed", "result": {"records": 2}}]}}
        def reviewed(*args, **kwargs):
            calls.append("review")
            return {"status": "completed", "runs": [{"status": "completed"}]}
        with mock.patch("research_run.run", side_effect=collected), \
                mock.patch.object(research_watch, "run_due", side_effect=reviewed):
            result = research_watch.serve(self.study, once=True, now=self.now)
        self.assertEqual(["collect", "review"], calls)
        self.assertEqual(2, result["new_source_records_collected"])
        self.assertTrue(result["new_source_material_collected"])
        self.assertFalse(result["new_evidence_collected"])

    def test_outbox_is_atomic_with_run_and_delivery_is_persistent(self) -> None:
        import notification_outbox
        self.create()
        research_watch.run_due(self.study, now=self.now)
        self.assertEqual(1, len(notification_outbox.pending(self.study)))
        research_watch.run_due(self.study, now=self.now)
        self.assertEqual(1, len(notification_outbox.pending(self.study)))
        got = notification_outbox.deliver_pending(
            self.study, lambda event: {"receipt": "offline-watch-delivery"})
        self.assertEqual(1, got["delivered"])
        self.assertEqual([], notification_outbox.pending(self.study))

    def test_empty_delivery_receipt_remains_pending(self) -> None:
        import notification_outbox
        self.create()
        research_watch.run_due(self.study, now=self.now)
        got = notification_outbox.deliver_pending(self.study, lambda event: "")
        self.assertEqual(1, got["failed"])
        self.assertEqual(0, got["delivered"])
        self.assertEqual(1, len(notification_outbox.pending(self.study)))

    def test_serve_runs_without_agent_and_reports_cost_boundary(self) -> None:
        self.assertTrue(hasattr(research_watch, "serve"))
        self.create()
        got = research_watch.serve(self.study, once=True, now=self.now)
        self.assertEqual("tick_finished", got["status"])
        self.assertEqual("not_used", got["operations"]["host_agent"])
        self.assertEqual(0, got["operations"]["scheduler_token_usage"])
        self.assertEqual("not_measured", got["operations"]["other_token_usage"])

    def test_cli_serve_and_notifications(self) -> None:
        created = self.run_cli(
            "watch", "create", str(self.study), "--question", "Track demand changes",
            "--interval-hours", "12", "--by", "owner", "--now", self.now)
        self.assertEqual(0, created.returncode, created.stdout + created.stderr)
        served = self.run_cli("watch", "serve", str(self.study), "--once", "--now", self.now)
        self.assertEqual(0, served.returncode, served.stdout + served.stderr)
        self.assertEqual("not_used", json.loads(served.stdout)["operations"]["host_agent"])
        notifications = self.run_cli("watch", "notifications", str(self.study))
        self.assertEqual(0, notifications.returncode, notifications.stdout + notifications.stderr)
        self.assertEqual(1, json.loads(notifications.stdout)["pending"])

    def test_cli_create_run_and_status(self) -> None:
        created = self.run_cli(
            "watch", "create", str(self.study), "--question", "Track demand changes",
            "--interval-hours", "12", "--by", "owner", "--now", self.now)
        self.assertEqual(0, created.returncode, created.stdout + created.stderr)
        ran = self.run_cli("watch", "run", str(self.study), "--now", self.now)
        self.assertEqual(0, ran.returncode, ran.stdout + ran.stderr)
        self.assertEqual("completed", json.loads(ran.stdout)["status"])
        status = self.run_cli(
            "watch", "status", str(self.study), "--now", "2026-11-25T13:00:00+00:00")
        self.assertEqual(0, status.returncode, status.stdout + status.stderr)
        self.assertEqual(1, json.loads(status.stdout)["due_count"])


if __name__ == "__main__":
    unittest.main()
