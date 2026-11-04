# -*- coding: utf-8 -*-
"""A-1 已知缺陷：audit 与 deliver 对"证据库"定义不一致（review 2026-11-04）。

场景：研究闭环（collect/_write_run）采集的记录落在 02-data/normalized.jsonl，
链条节点以 record_id 引用它后——
  - `check --stage decision` 只读 evidence.jsonl（_load_evidence_by_id），
    判 "references unknown evidence"，审计 fail；
  - `deliver --kind report` 混读 evidence.jsonl + normalized.jsonl
    （_evidence_summary），把同一条记录当作"依据"渲染进交付摘要。

本测试采用**严格的 Expected Failure 机制**（复核约定 2026-11-04）：
断言的是修复后应成立的一致性行为——deliver 不得把审计判为 unknown 的
证据渲染为决策依据。今天该断言必然失败（expectedFailure 使套件保持绿）；
当 evidence-store 收敛修复合入时，此测试会以 unexpected success 报告，
提醒删除 expectedFailure 装饰器并关闭 A-1。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/askovo/scripts/askovo.py"
SAMPLE = ROOT / "examples" / "sample-study"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(CLI), *args],
                          check=False, capture_output=True, text=True)


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

    @unittest.expectedFailure
    def test_deliver_must_not_cite_evidence_the_audit_rejects(self):
        """期望行为（A-1 修复目标）：审计不认可的引用不得进入交付依据。"""
        check = run_cli("check", str(self.study), "--stage", "decision")
        deliver = run_cli("deliver", str(self.study), "--kind", "report")
        self.assertEqual(0, deliver.returncode, deliver.stderr)

        # 精确断言"依据"渲染：deliver 输出的证据列表行（"证据 R01, R02, …"）
        # 不得包含 R08——不是只看 R08 是否出现在任意文本（错误提示里出现不算）。
        import re
        self.assertIsNone(
            re.search(r"证据[^\n]*\bR08\b", deliver.stdout),
            "deliver 把审计判为 unknown 的 R08 渲染为决策依据（A-1 缺陷仍在）")

        # 反向一致性：若未来审计认可 normalized.jsonl 为证据库，则 check
        # 不应再对 R08 报 unknown——两边任一收敛即满足一致性。
        self.assertNotIn("references unknown evidence: R08", check.stdout)


if __name__ == "__main__":
    unittest.main()
