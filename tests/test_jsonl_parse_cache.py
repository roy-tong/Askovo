# -*- coding: utf-8 -*-
"""A-3 解析缓存不变量（review 2026-11-09）。

冻结放大样例：一次 audit_payload 将 evidence.jsonl 全量解析 3 遍
（_check_evidence / _compute_signals / _load_evidence_by_id），一次 loop
run 最多 18 遍。修复后 _load_jsonl 以内容摘要为键复用解析结果：
  - 同内容多次读取只解析一次（audit_payload 三路收敛为一次）；
  - 同尺寸改写（digest 不同）必须失效重解析；
  - 返回行是拷贝，行内注解不污染缓存。
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
CLI_DIR = ROOT / "skills/askovo/scripts"
SAMPLE = ROOT / "examples/sample-study"
# 以独立模块名按路径加载，不与 askovo 薄包（tests 里其他测试 import 的同名包）
# 争夺 sys.modules["askovo"]。
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("askovo_scripts_cli_cache_test", CLI_DIR / "askovo.py")
askovo = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = askovo  # askovo.py 执行期即查 sys.modules[自身名]（bind_cli）
_spec.loader.exec_module(askovo)


class JsonlParseCache(unittest.TestCase):
    def _study(self, tmp: Path) -> Path:
        study = tmp / "study"
        shutil.copytree(SAMPLE, study)
        return study

    def test_audit_payload_parses_evidence_once(self):
        with tempfile.TemporaryDirectory() as d:
            study = self._study(Path(d))
            with mock.patch.object(
                    askovo, "_parse_jsonl_bytes",
                    side_effect=askovo._parse_jsonl_bytes,
                    wraps=askovo._parse_jsonl_bytes) as parse:
                askovo._JSONL_PARSE_CACHE.clear()
                askovo.audit_payload(study)
                first = parse.call_count
                self.assertEqual(1, first, first)  # 三路读取收敛为一次解析
                askovo._JSONL_PARSE_CACHE.clear()

    def test_same_size_rewrite_invalidates(self):
        with tempfile.TemporaryDirectory() as d:
            evidence = self._study(Path(d)) / "02-data/evidence.jsonl"
            original = evidence.read_text(encoding="utf-8")
            first = askovo._load_jsonl(evidence)
            # 同尺寸改写：把首行 record_id 的末字符换一个（长度不变）
            lines = original.splitlines()
            changed = lines[0].replace("R01", "R0X")
            self.assertEqual(len(lines[0]), len(changed))
            evidence.write_text(changed + "\n" + "\n".join(lines[1:]) + "\n", encoding="utf-8")
            second = askovo._load_jsonl(evidence)
            self.assertNotEqual(first[0]["record_id"], second[0]["record_id"])

    def test_row_annotations_do_not_pollute_cache(self):
        with tempfile.TemporaryDirectory() as d:
            evidence = self._study(Path(d)) / "02-data/evidence.jsonl"
            rows = askovo._load_jsonl(evidence)
            rows[0]["_line_number"] = 999
            rows[0]["polluted"] = True
            again = askovo._load_jsonl(evidence)
            self.assertNotIn("polluted", again[0])
            self.assertNotEqual(999, again[0]["_line_number"])


if __name__ == "__main__":
    unittest.main()
