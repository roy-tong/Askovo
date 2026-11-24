from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
CONNECTORS = ROOT / "skills/askovo/scripts/connectors"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


sys.path.insert(0, str(CONNECTORS))
arctic = load_module("askovo_arctic_windows_test", CONNECTORS / "collect_arctic_windows.py")


def comment(index: int, created_utc: int) -> dict:
    return {
        "id": f"c{index:04d}",
        "body": f"comment body number {index} with enough characters to count",
        "created_utc": created_utc,
        "link_id": "t3_post1",
        "subreddit": "python",
        "author": "someone",
        "score": 1,
    }


class ArcticWindowTests(unittest.TestCase):
    def test_fields_never_request_permalink(self) -> None:
        # The archive rejects permalink as a requested field with HTTP 400
        # ("'permalink' is not a valid field"); requesting it fails every window.
        self.assertNotIn("permalink", arctic.FIELDS.split(","))

    def test_source_url_is_rebuilt_from_ids_when_permalink_is_absent(self) -> None:
        row = arctic.normalize_comment(
            {"id": "m4xgumf", "link_id": "t3_1hrb0vx", "subreddit": "Python",
             "body": "a comment body long enough to be kept by the normalizer",
             "created_utc": 1735775848},
            "python", 1735689600, None,
        )
        self.assertIsNotNone(row)
        self.assertEqual(
            "https://www.reddit.com/r/python/comments/1hrb0vx/_/m4xgumf/",
            row["source_url"],
        )

    def test_hard_failure_is_not_reported_as_an_empty_window(self) -> None:
        with mock.patch.object(arctic, "fetch_window_page", return_value=None):
            with self.assertRaises(arctic.ArchiveWindowError):
                arctic.pull_window(
                    "python", 1000, 5000, 4000, io.StringIO(), set(),
                    {"comments": 0, "windows": 0}, 30, 0, 0, None,
                )

    def test_pagination_keeps_window_end_and_walks_backwards(self) -> None:
        calls = []

        def fake_fetch(sub, after, before, cursor, timeout, max_wait):
            calls.append((after, before, cursor))
            if len(calls) == 1:
                return [comment(i, 2000 - i) for i in range(100)]
            return []

        stats = {"comments": 0, "windows": 0}
        with mock.patch.object(arctic, "fetch_window_page", side_effect=fake_fetch):
            arctic.pull_window(
                "python", 1000, 5000, 4000, io.StringIO(), set(),
                stats, 30, 0, 0, None,
            )
        self.assertEqual((1000, 5000, None), calls[0])
        self.assertEqual((1000, 5000, 1900), calls[1])
        self.assertEqual(100, stats["comments"])

    def test_main_records_failure_instead_of_completing_the_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = tmp_path / "windows.json"
            config.write_text(json.dumps([
                {"sub": "python", "windows": [{"after": "2024-01-01", "before": "2024-01-02"}]},
            ]), encoding="utf-8")
            state = tmp_path / "state.json"
            out = tmp_path / "out.jsonl"
            argv = [
                "collect_arctic_windows.py", "--config", str(config),
                "--out", str(out), "--state", str(state),
                "--user-agent", "askovo-test/1.0", "--max-wait", "0",
            ]
            with mock.patch.object(sys, "argv", argv), \
                    mock.patch.object(arctic, "fetch_window_page", return_value=None), \
                    self.assertRaises(SystemExit) as stopped:
                arctic.main()
            self.assertEqual(1, stopped.exception.code)
            saved = json.loads(state.read_text(encoding="utf-8"))
            key = "python:2024-01-01:2024-01-02"
            self.assertIn(key, saved["errors"])
            self.assertNotIn(key, saved["completed"])

    def test_empty_archive_page_completes_the_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = tmp_path / "windows.json"
            config.write_text(json.dumps([
                {"sub": "python", "windows": [{"after": "2024-01-01", "before": "2024-01-02"}]},
            ]), encoding="utf-8")
            state = tmp_path / "state.json"
            out = tmp_path / "out.jsonl"
            argv = [
                "collect_arctic_windows.py", "--config", str(config),
                "--out", str(out), "--state", str(state),
                "--user-agent", "askovo-test/1.0", "--max-wait", "0",
            ]
            with mock.patch.object(sys, "argv", argv), \
                    mock.patch.object(arctic, "fetch_window_page", return_value=[]):
                arctic.main()
            saved = json.loads(state.read_text(encoding="utf-8"))
            key = "python:2024-01-01:2024-01-02"
            self.assertNotIn(key, saved["errors"])
            self.assertIn(key, saved["completed"])
            self.assertEqual(0, saved["counts"][key])


if __name__ == "__main__":
    unittest.main()
