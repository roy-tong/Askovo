from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/askovo/scripts/askovo.py"
ENGINE_PATH = ROOT / "skills/askovo/scripts/sure_engine.py"
SPEC = importlib.util.spec_from_file_location("askovo_queue_engine_test", ENGINE_PATH)
sure_engine = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(sure_engine)


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(CLI), *args], check=False, capture_output=True, text=True)


def complete_design(target: Path) -> None:
    path = target / "study.json"
    study = json.loads(path.read_text(encoding="utf-8"))
    study["decision"].update({
        "owner": "Synthetic owner", "deadline": "2027-12-31",
        "options": ["Pilot", "Stop"], "minimum_evidence": ["Synthetic evidence"],
    })
    study["scope"].update({
        "target_users": ["Synthetic users"], "markets": ["synthetic"], "languages": ["en"],
        "source_time_window": {"start": "2026-01-01", "end": "2026-12-31"},
        "allowed_sources": ["reddit", "github"],
    })
    study["hypotheses"] = [{"id": "H1", "statement": "Synthetic hypothesis", "falsified_if": "Synthetic falsifier"}]
    study["stopping_rules"] = ["Stop after fixture"]
    study["restart_rules"] = ["Restart after redesign"]
    path.write_text(json.dumps(study), encoding="utf-8")


class QueueStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = sure_engine.QueueStore(Path(self._tmp.name) / "queue.db")
        self.store.init()

    def test_rate_slots_are_reserved_before_waiting(self) -> None:
        with mock.patch.object(sure_engine.time, "time", return_value=100.0):
            waits = [self.store.acquire_rate("reddit", 10.0) for _ in range(3)]
        self.assertEqual([0.0, 10.0, 20.0], waits)
        with sqlite3.connect(str(self.store.db_path)) as conn:
            next_at = conn.execute("SELECT next_at FROM rate_state WHERE platform='reddit'").fetchone()[0]
        self.assertEqual(130.0, next_at)

    def test_only_current_owner_can_finish_a_lease(self) -> None:
        job_id = self.store.add("reddit", "night")
        job = self.store.lease("run-a-worker-1")
        self.assertEqual(job_id, job["id"])
        self.assertFalse(self.store.renew(job_id, "run-b-worker-1", 300))
        self.assertTrue(self.store.renew(job_id, "run-a-worker-1", 300))
        self.assertFalse(self.store.complete(job_id, 1, "run-b-worker-1"))
        self.assertFalse(self.store.fail(job_id, "stale", 1, "run-b-worker-1"))
        self.assertTrue(self.store.complete(job_id, 1, "run-a-worker-1"))
        self.assertFalse(self.store.fail(job_id, "late", 1, "run-a-worker-1"))

    def test_queue_parameters_are_validated(self) -> None:
        with self.assertRaises(ValueError):
            sure_engine.run_queue(Path(self._tmp.name), workers=0)
        with self.assertRaises(ValueError):
            sure_engine.run_queue(Path(self._tmp.name), lease_seconds=float("nan"))
        with self.assertRaises(ValueError):
            sure_engine.queue_add(Path(self._tmp.name), "reddit", "night", limit=0)
        with self.assertRaises(ValueError):
            sure_engine.queue_add(Path(self._tmp.name), "reddit", "night", max_attempts=0)

    def test_lost_lease_stops_worker_before_collection(self) -> None:
        queue_store = sure_engine.QueueStore(Path(self._tmp.name) / "01-sources" / "queue.db")
        queue_store.init()
        queue_store.add("reddit", "night")
        with mock.patch.object(sure_engine.QueueStore, "renew", return_value=False), mock.patch.object(
            sure_engine.QueueStore, "acquire_rate", return_value=0.2
        ), mock.patch.object(sure_engine, "collect_platform") as collector:
            summary = sure_engine.run_queue(
                Path(self._tmp.name), workers=1, min_interval=0, lease_seconds=0.01,
            )
        self.assertEqual(1, summary["leased"])
        collector.assert_not_called()

    def test_duplicate_run_id_never_overwrites_raw_or_manifest(self) -> None:
        study = Path(self._tmp.name)
        record = {"record_id": "reddit:a", "text": "first", "normalized_text_hash": "sha256:a"}
        raw = {"id": "a", "text": "first"}
        sure_engine._write_run(study, "reddit", "same-run", [record], {}, [raw])
        raw_path = study / "02-data/raw/reddit/same-run.jsonl"
        first = raw_path.read_text(encoding="utf-8")
        with self.assertRaises(FileExistsError):
            sure_engine._write_run(study, "reddit", "same-run", [record], {}, [raw])
        self.assertEqual(first, raw_path.read_text(encoding="utf-8"))


class QueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.study = self.base / "study"
        completed = run_cli("do", "家用摄像头夜间告警", "--study", str(self.study), "--json")
        self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)
        complete_design(self.study)

    def _fixture(self, name: str, rid: str) -> Path:
        path = self.base / name
        path.write_text(
            json.dumps(
                {
                    "id": rid,
                    "title": rid,
                    "text": f"night alert false alarm {rid}",
                    "author": "u",
                    "created_at": "2026-09-01T00:00:00Z",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return path

    def test_queue_run_requires_completed_design(self) -> None:
        fresh = self.base / "fresh"
        created = run_cli("do", "家用摄像头夜间告警", "--study", str(fresh), "--json")
        self.assertEqual(0, created.returncode)
        fixture = self._fixture("blocked-design.jsonl", "blocked-design")
        added = run_cli(
            "queue", "add", str(fresh), "--platform", "reddit", "--query", "night", "--fixture", str(fixture),
        )
        self.assertEqual(0, added.returncode)
        completed = run_cli("queue", "run", str(fresh), "--workers", "1", "--min-interval", "0")
        self.assertEqual(1, completed.returncode)
        self.assertEqual("design_gate_failed", json.loads(completed.stdout)["status"])
        self.assertFalse((fresh / "02-data/normalized.jsonl").exists())

    def test_concurrent_workers_drain_queue(self) -> None:
        for index in range(3):
            fixture = self._fixture(f"f{index}.jsonl", f"r{index}")
            added = run_cli(
                "queue", "add", str(self.study), "--platform", "reddit",
                "--query", "night", "--limit", "1", "--fixture", str(fixture),
            )
            self.assertEqual(0, added.returncode, added.stderr + added.stdout)
        completed = run_cli(
            "queue", "run", str(self.study), "--workers", "3", "--min-interval", "0",
        )
        self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)
        summary = json.loads(completed.stdout)
        self.assertEqual(3, summary["done"])
        self.assertEqual(0, summary["failed"])
        self.assertEqual(3, summary["records"])
        self.assertEqual(3, len(list((self.study / "01-sources/manifests").glob("*.json"))))
        self.assertEqual(3, len((self.study / "02-data/normalized.jsonl").read_text(encoding="utf-8").splitlines()))

    def test_failure_and_retry(self) -> None:
        missing = self.base / "missing.jsonl"
        run_cli(
            "queue", "add", str(self.study), "--platform", "reddit",
            "--query", "night", "--limit", "1", "--fixture", str(missing), "--max-attempts", "1",
        )
        completed = run_cli("queue", "run", str(self.study), "--workers", "1", "--min-interval", "0")
        self.assertEqual(1, completed.returncode)
        summary = json.loads(completed.stdout)
        self.assertEqual(1, summary["failed"])
        retried = run_cli("queue", "retry", str(self.study))
        self.assertEqual(0, retried.returncode, retried.stderr)
        self.assertEqual(1, json.loads(retried.stdout)["count"])
        status = json.loads(run_cli("queue", "status", str(self.study)).stdout)
        self.assertTrue(any(row["status"] == "pending" for row in status["counts"]))

    def test_expired_lease_is_reclaimed(self) -> None:
        fixture = self._fixture("lease.jsonl", "lease-1")
        run_cli(
            "queue", "add", str(self.study), "--platform", "reddit",
            "--query", "night", "--limit", "1", "--fixture", str(fixture),
        )
        db = self.study / "01-sources" / "queue.db"
        with sqlite3.connect(str(db)) as conn:
            conn.execute("UPDATE jobs SET status='running', lease_until=0, attempts=0")
        completed = run_cli("queue", "run", str(self.study), "--workers", "1", "--min-interval", "0")
        self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)
        self.assertEqual(1, json.loads(completed.stdout)["done"])


if __name__ == "__main__":
    unittest.main()
