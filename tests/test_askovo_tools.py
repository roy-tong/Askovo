from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
CONNECTORS = ROOT / "skills/askovo/scripts/connectors"
STAGES = ROOT / "skills/askovo/scripts/stages"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


sys.path.insert(0, str(STAGES))
stage_common = load_module("askovo_stage_common_test", STAGES / "common.py")
sys.modules["common"] = stage_common
workbook = load_module("askovo_workbook_test", STAGES / "audit_workbook.py")
candidate_signals = load_module("askovo_candidate_signals_test", STAGES / "extract_candidate_signals.py")
sys.path.insert(0, str(CONNECTORS))
connector_common = load_module("askovo_connector_common_test", CONNECTORS / "common.py")
sys.modules["common"] = connector_common
amazon = load_module("askovo_amazon_test", CONNECTORS / "collect_amazon_reviews_2023.py")
yt_innertube = load_module("askovo_youtube_innertube_test", CONNECTORS / "collect_youtube_innertube.py")
legacy_reddit = load_module("askovo_legacy_reddit_test", CONNECTORS / "collect_legacy_reddit.py")
sure_engine = load_module("askovo_tools_engine_test", ROOT / "skills/askovo/scripts/sure_engine.py")


class AuxiliaryScriptTests(unittest.TestCase):
    def test_every_connector_and_stage_help_exits_cleanly(self) -> None:
        scripts = [
            path for directory in (CONNECTORS, STAGES)
            for path in directory.glob("*.py")
            if path.name not in {"common.py", "__init__.py"}
        ]
        self.assertGreaterEqual(len(scripts), 10)
        for script in scripts:
            with self.subTest(script=script.name):
                completed = subprocess.run(
                    [sys.executable, str(script), "--help"],
                    check=False, capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_amazon_stream_disables_remote_code_and_pins_revision(self) -> None:
        loader = mock.Mock(return_value=iter([]))
        revision = "a" * 40
        with mock.patch.object(amazon, "import_datasets", return_value=loader):
            list(amazon.stream_dataset("dataset", "raw_review_test", revision))
        kwargs = loader.call_args.kwargs
        self.assertFalse(kwargs["trust_remote_code"])
        self.assertEqual(revision, kwargs["revision"])
        with self.assertRaises(ValueError):
            amazon.collect({"categories": ["test"]}, 1, 1, True, None)

    def test_amazon_fallback_id_is_stable_sha256(self) -> None:
        row = {
            "asin": "A1", "user_id": "U1", "timestamp": 1700000000000,
            "title": "Synthetic", "text": "A sufficiently long synthetic review body",
        }
        first = amazon.normalize_review(row, "test", "query", "salt")
        second = amazon.normalize_review(dict(row), "test", "query", "salt")
        self.assertEqual(first["record_id"], second["record_id"])
        self.assertRegex(first["record_id"], r"[0-9a-f]{24}$")


class YouTubeInnertubeParserTests(unittest.TestCase):
    """No-network parser tests for the collected innertube comment collector."""

    @staticmethod
    def _entity_payload_page() -> dict:
        # Minimal 2024+ shape: thread view models keyed by commentKey,
        # payloads delivered through frameworkUpdates.entityBatchUpdate.
        return {
            "frameworkUpdates": {"entityBatchUpdate": {"mutations": [
                {"payload": {"commentEntityPayload": {
                    "key": "ck1",
                    "author": {"displayName": "Golfer A"},
                    "properties": {"commentId": "UgComment1", "content": {"content": "Tracking works great at the range"},
                                   "publishedTime": "3 months ago"},
                    "toolbar": {"likeCountNotliked": "12"},
                }}},
            ]}},
            "onResponseReceivedEndpoints": [{"contents": {"itemSectionRenderer": {"contents": [
                {"commentThreadRenderer": {"commentViewModel": {"commentViewModel": {
                    "commentKey": "ck1", "commentId": "UgComment1",
                }}}}
            ]}}}],
        }

    def test_parses_comment_entity_payload_shape(self) -> None:
        rows = yt_innertube.parse_comments(self._entity_payload_page())
        self.assertEqual(1, len(rows))
        self.assertEqual("UgComment1", rows[0]["id"])
        self.assertEqual("Golfer A", rows[0]["author"])
        self.assertIn("Tracking works", rows[0]["text"])
        self.assertEqual("3 months ago", rows[0]["time_text"])

    def test_parses_legacy_comment_renderer_shape(self) -> None:
        page = {"onResponseReceivedEndpoints": [{"contents": {"itemSectionRenderer": {"contents": [
            {"commentRenderer": {
                "commentId": "UgLegacy1",
                "authorText": {"simpleText": "Golfer B"},
                "contentText": {"runs": [{"text": "Battery dies in the cold"}, {"text": " after an hour"}]},
                "publishedTimeText": {"simpleText": "1 year ago"},
                "voteCount": {"simpleText": "4"},
            }}
        ]}}}]}
        rows = yt_innertube.parse_comments(page)
        self.assertEqual(1, len(rows))
        self.assertEqual("UgLegacy1", rows[0]["id"])
        self.assertEqual("Battery dies in the cold after an hour", rows[0]["text"])

    def test_relative_time_becomes_approximate_date(self) -> None:
        import time as _time
        now = _time.time()
        iso = yt_innertube.approx_time("10 months ago", now)
        self.assertIsNotNone(iso)
        delta_days = abs((date.fromisoformat(iso) - date.fromtimestamp(now)).days)
        self.assertTrue(280 <= delta_days <= 340, iso)
        self.assertIsNone(yt_innertube.approx_time("edited", now))

    def test_comment_continuation_token_is_found_under_item_section(self) -> None:
        page = {"contents": {"a": {"itemSectionRenderer": {"contents": [
            {"continuationItemRenderer": {"continuationEndpoint": {
                "continuationCommand": {"token": "tok-1"}}}}
        ]}}}}
        self.assertEqual("tok-1", yt_innertube.comment_token(page))
        self.assertIsNone(yt_innertube.comment_token({"contents": {}}))

    def test_record_envelope_marks_approximate_dates_and_quality(self) -> None:
        comment = {"id": "UgComment1", "author": "Golfer A",
                   "text": "Tracking works great at the range and the app is stable.",
                   "time_text": "3 months ago", "likes": "12"}
        record = yt_innertube.build_record(
            comment, {"channel": "Chan", "title": "T"}, "vid1",
            {"q": "golf cam", "route": "yt-comp"}, None)
        self.assertEqual("youtube:UgComment1", record["record_id"])
        self.assertEqual("approximate", record["date_precision"])
        self.assertEqual("public_page_uncoded", record["source_tier"])
        self.assertIn("quality_flags", record)
        self.assertIn("quality_score", record)
        self.assertEqual("yt-comp", record["route_id"])
        self.assertEqual("vid1", record["thread_id"])


class AnalysisCorrectnessTests(unittest.TestCase):
    def test_legacy_reddit_respects_exact_day_window(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            routes = root / "routes.csv"
            routes.write_text("route_id,subreddit,per_month_cap\nr1,synthetic,10\n", encoding="utf-8")
            argv = [
                "collect_legacy_reddit.py", "--routes", str(routes),
                "--out", str(root / "out.jsonl"), "--state", str(root / "state.json"),
                "--start", "2026-09-15", "--end", "2026-09-20",
                "--user-agent", "synthetic-test", "--windows", "1", "--sleep", "0",
            ]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(
                legacy_reddit, "fetch_with_backoff", return_value=[]
            ) as fetch:
                legacy_reddit.main()
            after = fetch.call_args.args[1]
            before = fetch.call_args.args[2]
            self.assertEqual("2026-09-15T00:00:00+00:00", after.isoformat())
            self.assertEqual("2026-09-20T00:00:00+00:00", before.isoformat())

    def test_candidate_scores_use_document_frequency(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.jsonl"
            output = root / "signals.json"
            records = [
                {"text": "alpha beta alpha beta", "parent_id": "t1", "source_platform": "reddit", "month_bucket": "2026-01", "demand_evidence_level": "E2"},
                {"text": "gamma delta", "parent_id": "t2", "source_platform": "reddit", "month_bucket": "2026-01", "demand_evidence_level": "E0"},
                {"text": "epsilon zeta", "parent_id": "t3", "source_platform": "reddit", "month_bucket": "2026-01", "demand_evidence_level": "E0"},
                {"text": "eta theta", "parent_id": "t4", "source_platform": "reddit", "month_bucket": "2026-01", "demand_evidence_level": "E0"},
                {"text": "iota kappa", "parent_id": "t5", "source_platform": "reddit", "month_bucket": "2026-01", "demand_evidence_level": "E0"},
                {"text": "lambda mu", "parent_id": "t6", "source_platform": "reddit", "month_bucket": "2026-01", "demand_evidence_level": "E0"},
                {"text": "nu xi", "parent_id": "t7", "source_platform": "reddit", "month_bucket": "2026-01", "demand_evidence_level": "E0"},
                {"text": "omicron pi", "parent_id": "t8", "source_platform": "reddit", "month_bucket": "2026-01", "demand_evidence_level": "E0"},
            ]
            source.write_text("\n".join(json.dumps(row) for row in records) + "\n", encoding="utf-8")
            argv = [
                "extract_candidate_signals.py", "--input", str(source), "--out", str(output),
                "--min-records", "1", "--min-threads", "1", "--top", "10",
                "--evidence-field", "demand_evidence_level",
            ]
            with mock.patch.object(sys, "argv", argv):
                candidate_signals.main()
            ranked = json.loads(output.read_text(encoding="utf-8"))["ranked_latin_signals"]
            alpha = next(row for row in ranked if row["term"] == "alpha beta")
            self.assertEqual(1, alpha["records"])

    def test_workbook_csv_only_does_not_require_openpyxl(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.jsonl"
            source.write_text(json.dumps({"record_id": "r1", "text": "synthetic"}) + "\n", encoding="utf-8")
            args = argparse.Namespace(
                input=source, seed=7, label_fields="label", no_stratify=True,
                stratum_field="label", cross_field=None, cross_values=None,
                per_cross=1, per_stratum=10, excerpt=320, platform_cap=0.5, month_cap=0.4,
                out=root / "sample.xlsx", csv_out=root / "sample.csv", coverage_config=None,
            )
            with mock.patch.object(workbook, "Workbook", None):
                self.assertEqual(0, workbook.cmd_sample(args))
            self.assertFalse(args.out.exists())
            with args.csv_out.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(1, len(rows))


class SpreadsheetSafetyTests(unittest.TestCase):
    def test_spreadsheet_values_are_literal(self) -> None:
        for value in ("=1+1", " +SUM(A1:A2)", "\t@cmd", "-2+3"):
            self.assertTrue(stage_common.spreadsheet_safe(value).startswith("'"))
        self.assertEqual(3, stage_common.spreadsheet_safe(3))

    def test_metadata_csv_escapes_formula_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.jsonl"
            output = Path(directory) / "out.csv"
            source.write_text(json.dumps({"record_id": "r1", "text": "=1+1"}) + "\n", encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(STAGES / "export_metadata_detail.py"), "--input", str(source), "--out", str(output)],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            with output.open(encoding="utf-8", newline="") as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual("'=1+1", row["text_excerpt"])

    @unittest.skipIf(workbook.Workbook is None, "openpyxl optional dependency is not installed")
    def test_xlsx_formula_is_a_string_and_small_pool_is_retained(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.jsonl"
            source.write_text(json.dumps({"record_id": "r1", "text": "=1+1"}) + "\n", encoding="utf-8")
            args = argparse.Namespace(
                input=source, seed=7, label_fields="label", no_stratify=True,
                stratum_field="label", cross_field=None, cross_values=None,
                per_cross=1, per_stratum=10, excerpt=320, platform_cap=0.5, month_cap=0.4,
                out=Path(directory) / "sample.xlsx", csv_out=Path(directory) / "sample.csv",
                coverage_config=None,
            )
            self.assertEqual(0, workbook.cmd_sample(args))
            wb = workbook.load_workbook(args.out)
            ws = wb[workbook.SAMPLE_SHEET]
            self.assertEqual(2, ws.max_row)
            values = [cell for row in ws.iter_rows() for cell in row if cell.value == "'=1+1"]
            self.assertTrue(values)
            self.assertEqual("s", values[0].data_type)
            wb.close()

    def test_snapshot_hash_covers_content(self) -> None:
        first = [{"record_id": "r1", "text": "one"}]
        second = [{"record_id": "r1", "text": "two"}]
        self.assertNotEqual(workbook.snapshot_hash(first), workbook.snapshot_hash(second))

    def test_empty_gold_fails_agreement_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            reviewed = Path(directory) / "review.csv"
            reviewed.write_text("label_auto,gold_label\nauto,\n", encoding="utf-8")
            args = argparse.Namespace(
                reviewed=reviewed, sheet=None, out=None, report_out=None, min_agreement=0.8,
            )
            self.assertEqual(1, workbook.cmd_score(args))


class RepositoryHygieneTests(unittest.TestCase):
    def test_json_assets_parse(self) -> None:
        paths = [
            path for path in ROOT.rglob("*.json")
            if not any(part in {".git", ".venv", "build", "dist"} or part.endswith(".egg-info") for part in path.parts)
        ]
        self.assertGreater(len(paths), 10)
        for path in paths:
            with self.subTest(path=path.relative_to(ROOT)):
                with path.open(encoding="utf-8") as handle:
                    json.load(handle)

    def test_markdown_relative_links_resolve(self) -> None:
        link_pattern = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
        markdown_files = [
            path for path in ROOT.rglob("*.md")
            if not any(part in {".git", ".venv", "build", "dist"} or part.endswith(".egg-info") for part in path.parts)
        ]
        self.assertGreater(len(markdown_files), 20)
        for path in markdown_files:
            text = path.read_text(encoding="utf-8")
            for match in link_pattern.finditer(text):
                target = match.group(1).strip().strip("<>")
                if not target or target.startswith(("#", "mailto:")) or "://" in target:
                    continue
                target = target.split("#", 1)[0]
                if not target:
                    continue
                with self.subTest(file=path.relative_to(ROOT), target=target):
                    self.assertTrue((path.parent / target).exists())
        self.assertTrue((ROOT / "assets/brand/askovo-logo.png").is_file())
        self.assertTrue((ROOT / "assets/brand/askovo-logo-600.png").is_file())

    @unittest.skipIf(importlib.util.find_spec("yaml") is None, "PyYAML is not installed")
    def test_github_yaml_parses(self) -> None:
        import yaml
        paths = list((ROOT / ".github").rglob("*.yml")) + list((ROOT / ".github").rglob("*.yaml"))
        self.assertGreaterEqual(len(paths), 4)
        for path in paths:
            with self.subTest(path=path.relative_to(ROOT)):
                with path.open(encoding="utf-8") as handle:
                    self.assertIsInstance(yaml.safe_load(handle), dict)


class ConnectorPolicyTests(unittest.TestCase):
    def test_recheck_deadline_is_machine_enforced(self) -> None:
        connector = {"policy_watch": {"recheck_by": "2026-09-30"}}
        self.assertTrue(sure_engine.connector_review_expired(connector, date(2026, 10, 30)))
        connector["policy_watch"]["recheck_by"] = "2026-12-31"
        self.assertFalse(sure_engine.connector_review_expired(connector, date(2026, 10, 30)))
        connector["policy_watch"]["recheck_by"] = "invalid"
        self.assertTrue(sure_engine.connector_review_expired(connector, date(2026, 10, 30)))

    def test_author_pseudonym_requires_study_salt(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual("", sure_engine._hash_author("public-user"))
        with mock.patch.dict("os.environ", {"ASKOVO_AUTHOR_SALT": "study-a"}):
            first = sure_engine._hash_author("public-user")
        with mock.patch.dict("os.environ", {"ASKOVO_AUTHOR_SALT": "study-b"}):
            second = sure_engine._hash_author("public-user")
        self.assertTrue(first.startswith("hmac-sha256:"))
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
