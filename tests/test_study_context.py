import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/askovo/scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _api():
    from study_context import (
        BoundedJsonlCache,
        StudyContext,
        StudyRepository,
        current_study_context,
    )
    return BoundedJsonlCache, StudyContext, StudyRepository, current_study_context


class BoundedJsonlCacheTests(unittest.TestCase):
    def test_lru_eviction_and_clear(self):
        try:
            BoundedJsonlCache, _, _, _ = _api()
        except ModuleNotFoundError as exc:
            self.fail("study context API is missing: %s" % exc)
        cache = BoundedJsonlCache(max_entries=2)
        cache.put("a", [1])
        cache.put("b", [2])
        self.assertEqual([1], cache.get("a"))
        cache.put("c", [3])
        self.assertEqual(2, len(cache))
        self.assertIsNone(cache.get("b"))
        cache["d"] = [4]
        self.assertIsNone(cache.get("a"))
        self.assertEqual([4], cache["d"])
        cache.clear()
        self.assertEqual(0, len(cache))


class StudyContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.study = Path(self.temp.name) / "study"
        self.study.mkdir()
        self.evidence = self.study / "evidence.jsonl"
        self.evidence.write_text('{"record_id":"r1","value":1}\n', encoding="utf-8")

    def test_one_active_snapshot_survives_external_rewrite(self):
        _, StudyContext, StudyRepository, current_study_context = _api()
        context = StudyContext(StudyRepository(self.study))
        with context.activate():
            self.assertIs(context, current_study_context())
            first = context.read_jsonl(self.evidence)
            self.evidence.write_text('{"record_id":"r2","value":2}\n', encoding="utf-8")
            second = context.read_jsonl(self.evidence)
        self.assertEqual(first, second)
        self.assertEqual("r1", second[0]["record_id"])
        self.assertIsNone(current_study_context())
        with StudyContext(StudyRepository(self.study)).activate() as fresh:
            self.assertEqual("r2", fresh.read_jsonl(self.evidence)[0]["record_id"])

    def test_default_jsonl_parser_is_strict_and_returns_safe_rows(self):
        _, StudyContext, StudyRepository, _ = _api()
        context = StudyContext(StudyRepository(self.study))
        rows = context.read_jsonl(self.evidence)
        rows[0]["value"] = 99
        self.assertEqual(1, context.read_jsonl(self.evidence)[0]["value"])
        self.evidence.write_text('{"record_id":"r1"}\nnot-json\n', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "line 2"):
            StudyContext(StudyRepository(self.study)).read_jsonl(self.evidence)

    def test_json_reads_return_deep_copies(self):
        _, StudyContext, StudyRepository, _ = _api()
        path = self.study / "study.json"
        path.write_text(json.dumps({"decision": {"question": "original"}}), encoding="utf-8")
        context = StudyContext(StudyRepository(self.study))
        value = context.read_json(path)
        value["decision"]["question"] = "changed"
        self.assertEqual("original", context.read_json(path)["decision"]["question"])

    def test_repository_rejects_paths_outside_study(self):
        _, StudyContext, StudyRepository, _ = _api()
        outside = Path(self.temp.name) / "outside.jsonl"
        outside.write_text("{}\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            StudyContext(StudyRepository(self.study)).read_jsonl(outside)


class StudyContextIntegrationTests(unittest.TestCase):
    def test_audit_and_deliver_use_one_snapshot_but_next_request_reloads(self):
        import shutil
        from unittest import mock
        from tests.test_jsonl_parse_cache import askovo, SAMPLE
        _, StudyContext, StudyRepository, _ = _api()
        with tempfile.TemporaryDirectory() as directory:
            study = Path(directory) / "study"
            shutil.copytree(SAMPLE, study)
            evidence = study / "02-data/evidence.jsonl"
            original = evidence.read_text(encoding="utf-8")
            expected = sum(1 for line in original.splitlines() if line.strip())
            first_context = StudyContext(StudyRepository(study))
            with first_context.activate():
                audit = askovo.audit_study(study, "full")
                evidence.write_text("", encoding="utf-8")
                result = askovo.sure_engine.deliver(study, "plan", audit=audit)
            self.assertEqual(expected, result["evidence_count"])
            second_context = StudyContext(StudyRepository(study))
            with second_context.activate():
                second = askovo.sure_engine.deliver(study, "plan", audit=audit)
            self.assertEqual(0, second["evidence_count"])

    def test_legacy_cache_is_bounded(self):
        from tests.test_jsonl_parse_cache import askovo
        BoundedJsonlCache, _, _, _ = _api()
        self.assertIsInstance(askovo._JSONL_PARSE_CACHE, BoundedJsonlCache)


if __name__ == "__main__":
    unittest.main()
