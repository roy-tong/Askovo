from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("askovo_import_journey", ROOT / "skills/askovo/scripts/sure_engine.py")
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)

TEXT_ONE = "在下班后到孩子睡前的一小时，是家庭清洁唯一可执行的窗口的真实场景里，城市有娃家庭的家务主理人遇到边角进不去、毛发缠绕滚刷、拖完留水痕。（interview 第01条：受访家庭面积约 65 平米，每周补扫 2 次，最近一次发生在 11 月第 1 周，单次耗时 15 分钟）"
TEXT_TWO = "在下班后到孩子睡前的一小时，是家庭清洁唯一可执行的窗口的真实场景里，城市有娃家庭的家务主理人遇到边角进不去、毛发缠绕滚刷、拖完留水痕。（interview 第02条：受访家庭面积约 72 平米，每周补扫 3 次，最近一次发生在 12 月第 2 周，单次耗时 18 分钟）"


class ImportJourneyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.study = root / "study"
        (self.study / "01-sources").mkdir(parents=True)
        (self.study / "02-data").mkdir()
        (self.study / "study.json").write_text(json.dumps({"product_domain": "hardware"}), encoding="utf-8")
        self.english = root / "english.csv"
        self.english.write_text(
            "record_id,text,evidence_level,source_family,collected_at\n"
            f'R01,"{TEXT_ONE}",E1,interview,2026-10-01\n'
            f'R02,"{TEXT_TWO}",E1,interview,2026-10-01\n', encoding="utf-8")
        self.chinese = root / "chinese.csv"
        self.chinese.write_text(
            "记录编号,内容,证据等级,来源,采集时间\n"
            f'R01,"{TEXT_ONE}",E1,interview,2026-10-01\n'
            f'R02,"{TEXT_TWO}",E1,interview,2026-10-01\n', encoding="utf-8")

    def rows(self):
        path = self.study / "02-data/evidence.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_chinese_headers_deduplicate_without_losing_source_or_collection_time(self) -> None:
        engine.import_material(self.study, self.english)
        result = engine.import_material(self.study, self.chinese)
        self.assertEqual(2, result["parsed"])
        self.assertEqual(0, result["added"], result)
        self.assertEqual(2, result["skipped_duplicates"])
        self.assertEqual(2, len(self.rows()))
        first = self.rows()[0]
        self.assertEqual("R01", first["record_id"])
        self.assertEqual("interview", first["source_family"])
        self.assertEqual("2026-10-01", first["collected_at"])
        self.assertEqual("", first["created_at"])
        self.assertEqual("E1", first["evidence_level"])
        self.assertEqual("E1", first["level_declared"])

    def test_same_text_with_different_id_is_not_counted_twice(self) -> None:
        engine.import_material(self.study, self.english)
        duplicate = Path(self.tmp.name) / "different-id.jsonl"
        duplicate.write_text(json.dumps({"record_id": "imported-0001", "text": TEXT_ONE}) + "\n", encoding="utf-8")
        result = engine.import_material(self.study, duplicate)
        self.assertEqual(0, result["added"])
        self.assertEqual(1, result["skipped_duplicates"])
        self.assertEqual([{"record_id": "imported-0001", "duplicate_of": "R01", "reason": "same_text"}],
                         result["duplicates"])
        self.assertEqual(2, len(self.rows()))

    def test_retraction_excludes_evidence_and_restore_preserves_original_text(self) -> None:
        engine.import_material(self.study, self.english)
        cli = ROOT / "skills/askovo/scripts/askovo.py"
        before = self.rows()
        retracted = subprocess.run([
            sys.executable, str(cli), "evidence", str(self.study), "retract", "R01",
            "--by", "赵敏", "--reason", "纠正误导入记录",
        ], text=True, capture_output=True)
        self.assertEqual(0, retracted.returncode, retracted.stderr)
        self.assertEqual(1, len(engine.load_evidence_store(self.study)["records"]))
        self.assertNotIn("R01", engine._evidence_records_by_id(self.study))
        restored = subprocess.run([
            sys.executable, str(cli), "evidence", str(self.study), "restore", "R01", "--by", "赵敏",
        ], text=True, capture_output=True)
        self.assertEqual(0, restored.returncode, restored.stderr)
        self.assertEqual(2, len(engine.load_evidence_store(self.study)["records"]))
        self.assertEqual([row["text"] for row in before], [row["text"] for row in self.rows()])

    def test_same_id_with_different_text_rejects_whole_batch(self) -> None:
        engine.import_material(self.study, self.english)
        before = (self.study / "02-data/evidence.jsonl").read_bytes()
        conflict = Path(self.tmp.name) / "conflict.csv"
        conflict.write_text('record_id,text\nR03,"new valid row"\nR01,"different text under an existing id"\n', encoding="utf-8")
        with self.assertRaises(engine.ImportReviewError) as caught:
            engine.import_material(self.study, conflict)
        self.assertIn("R01", str(caught.exception))
        self.assertIn("正文", str(caught.exception))
        self.assertEqual(before, (self.study / "02-data/evidence.jsonl").read_bytes())


if __name__ == "__main__":
    unittest.main()
