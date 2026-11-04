# -*- coding: utf-8 -*-
"""A-1 冻结失败样例（review 2026-11-04）：audit 与 deliver 对"证据库"定义不一致。

场景：研究闭环（collect/_write_run）采集的记录落在 02-data/normalized.jsonl，
链条节点以 record_id 引用它后——
  - `check --stage decision` 只读 evidence.jsonl（_load_evidence_by_id），
    判 "references unknown evidence"，审计 fail；
  - `deliver --kind report` 混读 evidence.jsonl + normalized.jsonl
    （_evidence_summary），把同一条记录当作"依据"渲染进交付摘要。

本测试**钉住今天的矛盾现状**（两断言都过 = 矛盾仍在）。它是绊线而非认可：
evidence-store 收敛（A-1 修复）合入后，本测试必然失败，修复 PR 须将其改写为
"audit 与 deliver 不得在证据有效性上互相矛盾"的一致性断言并删除此说明。
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


class EvidenceAuditDeliverContradiction(unittest.TestCase):
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

    def test_audit_and_deliver_disagree_on_the_same_evidence(self):
        check = run_cli("check", str(self.study), "--stage", "decision")
        self.assertEqual(0 if check.returncode in (0, 1) else check.returncode,
                         0, check.stderr)  # 命令本身可运行（fail 以 findings 表达）
        # 现状一：决策审计不认识 normalized.jsonl 里的 R08
        self.assertIn("references unknown evidence: R08", check.stdout)

        deliver = run_cli("deliver", str(self.study), "--kind", "report")
        self.assertEqual(0, deliver.returncode, deliver.stderr)
        # 现状二：交付报告却把 R08 当作决策依据渲染
        self.assertIn("R08", deliver.stdout)
        # ↑ 两件事同时成立即矛盾：同一条证据"不存在"却又"支持决策"。
        #   A-1 修复（evidence-store 收敛）后请把本测试改写为一致性断言。


if __name__ == "__main__":
    unittest.main()
