# -*- coding: utf-8 -*-
"""A-1 一致性断言（evidence-store 收敛后）：audit 与 deliver 对"证据有效性"
不得互相矛盾。

同一证据库判定（sure_engine.is_qualified_evidence / load_evidence_store）：
只有登记在 02-data/evidence.jsonl 且 evidence_level 合格的记录才是决策证据；
研究闭环采集落盘在 02-data/normalized.jsonl 的记录是采集库存，不是依据
（收集 ≠ 获得证据）。

场景（沿用 2026-11-04 冻结样例）：链条节点引用了只存在于 normalized.jsonl 的
R08 ——
  - `check --stage decision` 判 "references unknown evidence: R08"（严格侧不变）；
  - `deliver --kind report` 不得把 R08 渲染为依据，必须以"未评级引用"显式披露；
  - 交付计入依据的 id 集合 ⊆（且实际 ==）审计接受的合格证据集合。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/askovo/scripts/askovo.py"
SAMPLE = ROOT / "examples" / "sample-study"
sys.path.insert(0, str(ROOT / "skills/askovo/scripts"))
import sure_engine  # noqa: E402
sys.path.pop(0)  # 别把 scripts 目录留在 sys.path 前部，避免污染后续 `import askovo` 包解析


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run([sys.executable, str(CLI), *args],
                          check=False, capture_output=True, text=True, timeout=120, env=env)


class EvidenceAuditDeliverConsistency(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.study = Path(self.tmp.name) / "study"
        shutil.copytree(SAMPLE, self.study)
        # 闭环采集形态：记录只存在于 normalized.jsonl，不在 evidence.jsonl
        first = json.loads(next(
            line for line in (self.study / "02-data/evidence.jsonl")
            .read_text(encoding="utf-8").splitlines() if line.strip()))
        first["record_id"] = "R08"
        first["source_ref"] = "demo:loop-collect-1"
        (self.study / "02-data/normalized.jsonl").write_text(
            json.dumps(first, ensure_ascii=False) + "\n", encoding="utf-8")
        reasoning_path = self.study / "04-findings/product-reasoning.json"
        reasoning = json.loads(reasoning_path.read_text(encoding="utf-8"))
        reasoning["chains"][0]["nodes"]["pain"]["evidence_ids"].append("R08")
        reasoning_path.write_text(
            json.dumps(reasoning, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _deliver_summary_text(self) -> str:
        deliver = run_cli("deliver", str(self.study), "--kind", "report")
        self.assertEqual(0, deliver.returncode, deliver.stderr)
        payload = json.loads(deliver.stdout)
        summary = payload.get("chat_summary") or {}
        return str(summary.get("text") or "")

    def _basis_line(self, text: str) -> str:
        line = next((item for item in text.splitlines() if "需求判断" in item), "")
        self.assertTrue(line, "delivery summary must contain a basis line")
        return line

    @staticmethod
    def _segment_ids(line: str, prefix: str) -> set[str]:
        for segment in line.split("；"):
            segment = segment.strip()
            if segment.startswith(prefix):
                values = segment[len(prefix):].split("（", 1)[0].strip()
                return {item.strip() for item in values.split(",") if item.strip() and item.strip() != "无"}
        return set()

    def test_audit_and_deliver_agree_on_the_same_evidence(self):
        check = run_cli("check", str(self.study), "--stage", "decision")
        self.assertEqual(0 if check.returncode in (0, 1) else check.returncode,
                         0, check.stderr)
        # 审计侧（严格不变）：未评级采集记录不是决策证据
        self.assertIn("references unknown evidence: R08", check.stdout)

        line = self._basis_line(self._deliver_summary_text())
        # 交付侧不得把 R08 渲染为依据（矛盾的一半已被移除）
        self.assertNotIn("R08", self._segment_ids(line, "证据 "))
        self.assertNotIn("R08", self._segment_ids(line, "反证 "))
        # 交付侧必须以"未评级引用"显式披露，与审计同判
        self.assertEqual({"R08"}, self._segment_ids(line, "未评级引用 "))
        self.assertIn("不计入依据", line)

    def test_delivery_basis_equals_audit_qualified_set(self):
        """交付计入依据的 id 集合 == 审计接受的合格证据集合（同源判定）。"""
        line = self._basis_line(self._deliver_summary_text())
        rendered = self._segment_ids(line, "证据 ") | self._segment_ids(line, "反证 ")
        store = sure_engine.load_evidence_store(self.study)
        qualified = {str(record.get("record_id")) for record in store["records"]}
        cited = set(sure_engine.chain_cited_evidence_ids(
            json.loads((self.study / "04-findings/product-reasoning.json")
                       .read_text(encoding="utf-8"))))
        # 交付渲染的每一个依据 id 都是合格证据，且合格且被引用的都渲染了
        self.assertTrue(rendered)
        self.assertLessEqual(rendered, qualified)
        self.assertLessEqual(qualified & cited, rendered)
        # R08 属于采集库存，不属于合格证据
        self.assertNotIn("R08", qualified)
        self.assertIn("R08", {str(r.get("record_id")) for r in store["collected_records"]})

    def test_qualified_evidence_still_renders_as_basis(self):
        """收敛不是清空依据：合格证据（R01 在 evidence.jsonl）仍照常渲染。"""
        line = self._basis_line(self._deliver_summary_text())
        self.assertIn("R01", self._segment_ids(line, "证据 "))


if __name__ == "__main__":
    unittest.main()
