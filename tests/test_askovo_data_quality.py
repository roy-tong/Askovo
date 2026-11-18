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
