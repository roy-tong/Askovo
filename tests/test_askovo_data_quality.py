#!/usr/bin/env python3
"""Data-quality surface: `analyze` reports field completeness before conclusions.

Field preservation was the campaign's most expensive silent failure: a
positional conversion dropped ``author_hash`` and the persona analysis
collapsed while row counts looked healthy; Amazon dates read 0/16,226 until the
timestamp field was parsed. The engine now publishes non-empty rates for the
join fields and flags a 0% required field as a pipeline bug.
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/askovo/scripts/sure_engine.py"

spec = importlib.util.spec_from_file_location("sure_engine_data_quality_test", SCRIPT)
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)


CLEANER = ROOT / "skills/askovo/scripts/connectors/clean_screen_corpus.py"
cleaner_spec = importlib.util.spec_from_file_location("clean_screen_corpus_test", CLEANER)
cleaner = importlib.util.module_from_spec(cleaner_spec)
cleaner_spec.loader.exec_module(cleaner)


class NormalizationAliasTests(unittest.TestCase):
    def test_import_normalization_accepts_body_published_at_and_permalink(self) -> None:
        raw = {
            "id": "r1",
            "body": "夜间误报很烦，希望先判断再起床。",
            "published_at": "2026-01-02T00:00:00Z",
            "permalink": "https://www.reddit.com/r/example/comments/1",
            "author": "alice",
        }
        defaults = {
            "source_family": "imported", "source_ref": "fixture",
            "claim_type": "need", "evidence_form": "self_report",
            "method_id": "test", "product_domain": "unknown",
        }
        record = engine._normalize_record(raw, 1, defaults)
        self.assertEqual(raw["body"], record["text"])
        self.assertEqual(raw["published_at"], record["created_at"])
        self.assertEqual(raw["published_at"], record["collected_at"])
        self.assertEqual(raw["permalink"], record["source_url"])

    def test_created_utc_is_converted_to_iso(self) -> None:
        raw = {"id": "r2", "body": "正文", "created_utc": 1700000000}
        defaults = {
            "source_family": "imported", "source_ref": "fixture",
            "claim_type": "need", "evidence_form": "self_report",
            "method_id": "test", "product_domain": "unknown",
        }
        record = engine._normalize_record(raw, 2, defaults)
        self.assertTrue(record["created_at"].startswith("2023-11-14T"))
        self.assertEqual(record["created_at"], record["collected_at"])

    def test_platform_normalization_does_not_hash_empty_text(self) -> None:
        raw = {"title": "Title only", "permalink": "https://example.com/post/1",
               "published_at": "2026-01-01T00:00:00Z"}
        record = engine._normalize_platform_record(raw, "reddit", "run-1", "q")
        self.assertEqual("", record["text"])
        self.assertEqual("Title only", record["title"])
        self.assertEqual("https://example.com/post/1", record["source_url"])
        self.assertEqual(raw["published_at"], record["created_at"])
        self.assertTrue(record["record_id"].startswith("reddit:https://example.com/post/1"))

    def test_href_and_time_aliases_are_preserved(self) -> None:
        raw = {"title": "Kickstarter comment", "href": "https://example.com/post?comment=1",
               "time": "about 1 year ago"}
        record = engine._normalize_platform_record(raw, "kickstarter", "run-1", "q")
        self.assertEqual("https://example.com/post?comment=1", record["source_url"])
        self.assertEqual("about 1 year ago", record["created_at"])

    def test_cleaner_envelope_preserves_body_and_timestamp_aliases(self) -> None:
        envelope = cleaner.build_envelope(
            {"body": "正文", "published_at": "2026-01-01", "comment_id": "c1"},
            text="正文", text_hash="hash", record_key="c1", keep_fields=[],
            channel_field="", created_at_field="created_at,published_at,timestamp,time,created_utc",
            run_id="run-1", platform="reddit", source_family="reddit",
            source_tier="fixture", dataset_role="fixture", lexicon=None,
            keep_unlabeled=False, screening_method="test")
        self.assertEqual("2026-01-01", envelope["created_at"])
        self.assertEqual("正文", envelope["text"])

    def test_collected_at_is_not_used_as_created_at(self) -> None:
        defaults = {
            "source_family": "imported", "source_ref": "fixture",
            "claim_type": "need", "evidence_form": "self_report",
            "method_id": "test", "product_domain": "unknown",
        }
        record = engine._normalize_record(
            {"id": "r3", "body": "正文", "collected_at": "2026-01-05T00:00:00Z"},
            3, defaults)
        self.assertEqual("", record["created_at"])
        self.assertEqual("2026-01-05T00:00:00Z", record["collected_at"])

    def test_collected_at_does_not_mask_missing_created_at(self) -> None:
        quality = engine._analysis_field_completeness([
            {"record_id": "r1", "text": "body", "collected_at": "2026-01-01T00:00:00Z"},
        ])
        self.assertEqual(0.0, quality["fields"]["created_at"]["ratio"])
        self.assertIn("created_at", quality["zero_rate_fields"])

    def test_fixture_collection_does_not_require_enabled_adapter(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        study = Path(directory.name) / "study"
        study.mkdir()
        (study / "study.json").write_text(json.dumps({
            "scope": {"allowed_sources": ["github"]},
            "source_adapters": {},
        }), encoding="utf-8")
        fixture = Path(directory.name) / "export.jsonl"
        fixture.write_text(json.dumps({
            "id": "d1", "text": "Nested JSON logs fail to parse; retry by hand.",
            "url": "https://example.com/1", "author": "u1", "created_at": "2026-09-01",
        }) + "\n", encoding="utf-8")
        result = engine.collect_platform(study, "github", "logs", limit=1, fixture=fixture)
        self.assertEqual("collected", result["status"])
        self.assertEqual(1, result["records"])
        self.assertTrue((study / "02-data" / "normalized.jsonl").is_file())

    def test_topic_mechanism_and_duplicate_analysis(self) -> None:
        records = [
            {"record_id": "r1", "text": "Night alerts are too frequent, so users disable them",
             "platform": "reddit", "evidence_level": "E1"},
            {"record_id": "r2", "text": "Night alerts happen often, because false alarms wake users",
             "platform": "reddit", "evidence_level": "E1"},
            {"record_id": "r3", "text": "Price is high, but users still renew",
             "platform": "amazon", "evidence_level": "E2"},
            {"record_id": "r4", "text": "Price is high, but users still renew",
             "platform": "amazon", "evidence_level": "E2"},
        ]
        topics = engine._analysis_topics(records, set())
        self.assertTrue(any("night" in topic["terms"] or "alerts" in topic["terms"]
                            for topic in topics))
        mechanisms = engine._analysis_mechanisms(records)
        self.assertTrue(any(item["kind"] == "mechanism_candidate" for item in mechanisms))
        self.assertTrue(any(item["kind"] == "contrast_candidate" for item in mechanisms))
        duplicates = engine._analysis_duplicates(records)
        self.assertEqual(2, duplicates["duplicate_records"])
        self.assertEqual(3, duplicates["unique_records"])

    def test_cdp_extractors_keep_time_fields(self) -> None:
        self.assertIn("created_at: publishedText", engine.CDP_YOUTUBE_EXTRACTOR)
        self.assertIn("#published-time-text", engine.CDP_YOUTUBE_EXTRACTOR)
        self.assertIn('source_content_type: "forum_post"', engine.CDP_DISCORD_EXTRACTOR)
        self.assertIn('time[datetime]', engine.CDP_DISCORD_EXTRACTOR)

    def test_record_time_and_evidence_text_accept_aliases(self) -> None:
        self.assertEqual("2026-01-03", engine._record_time({"published_at": "2026-01-03"}))
        self.assertEqual("content text", engine._evidence_text({"content": "content text"}))
        self.assertEqual("body", engine._evidence_text({"title": "Title", "body": "body"}))
        self.assertEqual("", engine._evidence_text({"title": "Title only"}))


class AnalysisFieldCompletenessTests(unittest.TestCase):
    def make_study(self, records: list[dict]) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        study = Path(directory.name) / "study"
        (study / "02-data").mkdir(parents=True)
        with (study / "02-data" / "normalized.jsonl").open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return study

    def test_non_empty_rates_are_reported_per_join_field(self) -> None:
        study = self.make_study([
            {"record_id": "r1", "text": "first", "source_url": "https://example.com/1",
             "created_at": "2026-01-01T00:00:00Z"},
            {"record_id": "r2", "text": "second"},
        ])
        result = engine.analyze_study(study)
        analysis = json.loads(Path(result["analysis"]).read_text(encoding="utf-8"))
        fields = analysis["field_completeness"]["fields"]
        self.assertEqual(1.0, fields["record_id"]["ratio"])
        self.assertEqual(1.0, fields["text"]["ratio"])
        self.assertEqual(0.5, fields["source_url"]["ratio"])
        self.assertEqual(0.5, fields["created_at"]["ratio"])
        self.assertEqual([], analysis["field_completeness"]["required_zero_rate"])

    def test_a_zero_rate_required_field_is_a_pipeline_bug(self) -> None:
        study = self.make_study([
            {"text": "no id one", "source_ref": "https://example.com/1"},
            {"text": "no id two", "source_ref": "https://example.com/2"},
        ])
        result = engine.analyze_study(study)
        analysis = json.loads(Path(result["analysis"]).read_text(encoding="utf-8"))
        quality = analysis["field_completeness"]
        self.assertEqual(["record_id"], quality["required_zero_rate"])
        self.assertIn("record_id", quality["zero_rate_fields"])

    def test_markdown_surfaces_field_completeness(self) -> None:
        study = self.make_study([{"record_id": "r1", "text": "body", "source_ref": "url"}])
        engine.analyze_study(study)
        markdown = (study / "04-findings" / "analysis.md").read_text(encoding="utf-8")
        self.assertIn("字段完整性（管线体检）", markdown)
        self.assertIn("记录 id", markdown)
        self.assertIn("来源 URL", markdown)


if __name__ == "__main__":
    unittest.main()
