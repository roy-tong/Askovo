#!/usr/bin/env python3
"""GitHub REST issue exports use comments as a count, not comment objects."""
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
SAMPLE = ROOT / "examples/sample-study"


class GithubRestExportTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.study = self.base / "study"
        shutil.copytree(SAMPLE, self.study)

    def test_rest_comment_count_imports_without_inventing_comment_bodies(self) -> None:
        row = {
            "id": 19757, "number": 19757,
            "title": "24 GB Mac reaches critical memory pressure",
            "body": "On a 24 GB Mac the first requests reach critical memory pressure.",
            "state": "open", "html_url": "https://github.com/ollama/ollama/issues/19757",
            "user": {"login": "public-user", "id": 42, "type": "User"},
            "author_association": "NONE", "created_at": "2026-11-18T00:00:00Z",
            "updated_at": "2026-11-18T00:00:00Z", "labels": [], "comments": 7,
            "visibility": "public",
        }
        source = self.base / "rest-export.json"
        source.write_text(json.dumps([row]), encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, str(CLI), "issues", "import", str(self.study), "--file", str(source),
             "--authorized-by", "test-reviewer"], capture_output=True, text=True, timeout=120)
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        snapshots = list((self.study / "02-data/raw/issues").glob("*.jsonl"))
        self.assertTrue(snapshots)
        stored_rows = [json.loads(line) for line in snapshots[0].read_text(encoding="utf-8").splitlines()
                       if line.strip()]
        stored = next(item for item in stored_rows if item.get("number") == 19757)
        self.assertEqual(7, stored["comments_count"])
        self.assertEqual([], stored["comments"])
        extracted = subprocess.run(
            [sys.executable, str(CLI), "issues", "extract", str(self.study)],
            capture_output=True, text=True, timeout=120)
        self.assertEqual(0, extracted.returncode, extracted.stdout + extracted.stderr)


if __name__ == "__main__":
    unittest.main()
