import json
import os
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

    def test_active_request_rejects_external_rewrite(self):
        import write_integrity
        _, StudyContext, StudyRepository, current_study_context = _api()
        context = StudyContext(StudyRepository(self.study))
        with self.assertRaises(write_integrity.IntegrityError) as raised:
            with context.activate():
                self.assertIs(context, current_study_context())
                context.read_jsonl(self.evidence)
                before = self.evidence.stat()
                self.evidence.write_text('{"record_id":"r2","value":2}\n', encoding="utf-8")
                os.utime(self.evidence, (before.st_atime, before.st_mtime))
                context.read_jsonl(self.evidence)
        self.assertEqual("STALE_SOURCE", raised.exception.code)
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

    def test_jsonl_nested_rows_are_isolated_from_caller_mutation(self):
        _, StudyContext, StudyRepository, _ = _api()
        self.evidence.write_text(
            '{"record_id":"r1","claims":[{"statement":"original"}]}\n', encoding="utf-8")
        context = StudyContext(StudyRepository(self.study))
        rows = context.read_jsonl(self.evidence)
        rows[0]["claims"][0]["statement"] = "caller-mutated"
        self.assertEqual(
            "original", context.read_jsonl(self.evidence)[0]["claims"][0]["statement"])

    def test_request_snapshot_survives_cache_capacity_and_external_rewrite(self):
        _, StudyContext, StudyRepository, _ = _api()
        paths = []
        for index in range(33):
            path = self.study / ("snapshot-%02d.json" % index)
            path.write_text(json.dumps({"version": "old", "index": index}), encoding="utf-8")
            paths.append(path)
        context = StudyContext(StudyRepository(self.study))
        first = context.read_json(paths[0])
        for path in paths[1:]:
            context.read_json(path)
        paths[0].write_text(json.dumps({"version": "new", "index": 0}), encoding="utf-8")
        second = context.read_json(paths[0])
        self.assertEqual(first, second)
        self.assertEqual("old", second["version"])

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
    def test_audit_and_deliver_reject_external_rewrite(self):
        import shutil
        import write_integrity
        from tests.test_jsonl_parse_cache import askovo, SAMPLE
        _, StudyContext, StudyRepository, _ = _api()
        with tempfile.TemporaryDirectory() as directory:
            study = Path(directory) / "study"
            shutil.copytree(SAMPLE, study)
            evidence = study / "02-data/evidence.jsonl"
            first_context = StudyContext(StudyRepository(study))
            with self.assertRaises(write_integrity.IntegrityError) as raised:
                with first_context.activate():
                    audit = askovo.audit_study(study, "full")
                    evidence.write_text("", encoding="utf-8")
                    askovo.sure_engine.deliver(study, "plan", audit=audit)
            self.assertEqual("STALE_SOURCE", raised.exception.code)
            second_context = StudyContext(StudyRepository(study))
            with second_context.activate():
                second = askovo.sure_engine.deliver(study, "plan", audit=audit)
            self.assertEqual(0, second["evidence_count"])

    def test_multi_file_commit_cannot_mix_old_study_with_new_evidence(self):
        import write_integrity
        _, StudyContext, StudyRepository, _ = _api()
        with tempfile.TemporaryDirectory() as directory:
            study = Path(directory) / "study"
            study.mkdir()
            study_file = study / "study.json"
            evidence = study / "evidence.jsonl"
            study_file.write_text('{"decision":{"question":"old"}}', encoding="utf-8")
            evidence.write_text('{"record_id":"r1","value":1}\n', encoding="utf-8")
            repository = StudyRepository(study)
            context = StudyContext(repository)
            with self.assertRaises(write_integrity.IntegrityError) as raised:
                with context.activate():
                    self.assertEqual("old", context.read_json(study_file)["decision"]["question"])
                    with repository.transaction("test multi-file commit") as txn:
                        txn.add(study_file, '{"decision":{"question":"new"}}')
                        txn.add(evidence, '{"record_id":"r2","value":2}\n')
                        txn.commit()
                    self.assertEqual("r2", context.read_jsonl(evidence)[0]["record_id"])
            self.assertEqual("STALE_SOURCE", raised.exception.code)
            with StudyContext(repository).activate() as fresh:
                self.assertEqual("new", fresh.read_json(study_file)["decision"]["question"])
                self.assertEqual("r2", fresh.read_jsonl(evidence)[0]["record_id"])

    def test_legacy_cache_is_bounded(self):
        from tests.test_jsonl_parse_cache import askovo
        BoundedJsonlCache, _, _, _ = _api()
        self.assertIsInstance(askovo._JSONL_PARSE_CACHE, BoundedJsonlCache)


if __name__ == "__main__":
    unittest.main()
