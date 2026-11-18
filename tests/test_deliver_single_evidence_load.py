# -*- coding: utf-8 -*-
"""一次 deliver 进程只读一次证据库（单一快照不变量）。

此前 deliver() 内部 _deliver_artifact 与 _with_chat_summary 各自独立调
_evidence_summary：同一进程里 evidence.jsonl/normalized.jsonl 被全量读两遍，
且两层之间存在理论上的中途变更窗口（artifact 与 chat summary 可能基于不同
快照）。本测试钉住修复后的不变量：单次 deliver 恰好加载一次。
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "examples" / "sample-study"
sys.path.insert(0, str(ROOT / "skills/askovo/scripts"))
import sure_engine  # noqa: E402
sys.path.pop(0)


class DeliverSingleEvidenceLoad(unittest.TestCase):
    def test_deliver_loads_the_evidence_store_exactly_once(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        study = Path(tmp.name) / "study"
        shutil.copytree(SAMPLE, study)

        original = sure_engine._evidence_summary
        calls: list[Path] = []

        def counting(path: Path) -> dict:
            calls.append(path)
            return original(path)

        with mock.patch.object(sure_engine, "_evidence_summary", side_effect=counting):
            result = sure_engine.deliver(study, "report", audit=None)
        self.assertEqual(1, len(calls), "deliver must load the evidence store exactly once")
        self.assertIn("chat_summary", result)
        self.assertTrue(Path(str(result.get("path", ""))).is_file() or result.get("path"))


if __name__ == "__main__":
    unittest.main()
