from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/user-demand-research/scripts/sure.py"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(CLI), *args], check=False, capture_output=True, text=True)


class QueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.study = self.base / "study"
        completed = run_cli("do", "家用摄像头夜间告警", "--study", str(self.study), "--json")
        self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)

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
