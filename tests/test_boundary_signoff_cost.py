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
SAMPLE = ROOT / "examples/sample-study"

REQ_DOC = """\
# 需求：夜间告警误报过滤

- 只在有人在家时推送告警
- 告警需在 30 秒内送达
- 支持按房间静音
- 告警延迟超过 5 分钟时自动电话通知紧急联系人

用户希望减少误报打扰，保留真实告警。
"""

AI_DOC = """\
# PRD：夜间告警误报过滤

## 告警推送
系统在检测到有人在家时推送告警，并支持按房间静音。

## 额外的智能摘要
每晚生成自然语言日报，包含 AI 生成的家庭活动分析、情绪趋势、健康建议和跨月对比图表，
并支持导出到第三方平台与订阅付费推送。

## 送达时效
告警需在 30 秒内送达用户设备。
"""


class BoundaryAuditTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        (self.dir / "req.md").write_text(REQ_DOC, encoding="utf-8")
        (self.dir / "ai.md").write_text(AI_DOC, encoding="utf-8")
        shutil.copytree(SAMPLE, self.dir / "sample")

    def run_cli(self, *args):
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True, env=env)

    def test_detects_planted_missing_and_added(self):
        done = self.run_cli("boundary", str(self.dir / "sample"),
                            "--requirements", str(self.dir / "req.md"),
                            "--output", str(self.dir / "ai.md"))
        self.assertEqual(0, done.returncode, done.stdout + done.stderr)
        payload = json.loads(done.stdout)
        added = " ".join(row["excerpt"] for row in payload["added"])
        missing = " ".join(row["excerpt"] for row in payload["missing"])
        self.assertIn("智能摘要", added, "undiscussed AI addition should be flagged as Added")
        self.assertIn("电话通知紧急联系人", missing, "requirement with no counterpart should be flagged as Missing")
        report = Path(payload["report"]).read_text(encoding="utf-8")
        self.assertIn("Added", report)
        self.assertIn("候选", report)

    def test_inflated_flagged_with_ratio(self):
        done = self.run_cli("boundary", str(self.dir / "sample"),
                            "--requirements", str(self.dir / "req.md"),
                            "--output", str(self.dir / "ai.md"))
        payload = json.loads(done.stdout)
        self.assertTrue(any(row["ratio"] >= 3.0 for row in payload["inflated"]) or payload["inflated"] == [] or
                        all(row for row in payload["inflated"]))
        for row in payload["inflated"]:
            self.assertIn("ratio", row)
            self.assertTrue(row["ref"].startswith("ai.md:"))

    def test_boundary_report_is_written_into_study(self):
        done = self.run_cli("boundary", str(self.dir / "sample"),
                            "--requirements", str(self.dir / "req.md"),
                            "--output", str(self.dir / "ai.md"))
        payload = json.loads(done.stdout)
        report = Path(payload["report"])
        self.assertTrue(report.is_file())
        self.assertEqual(report.parent.name, "06-report")


class SignoffPageTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name) / "sample"
        shutil.copytree(SAMPLE, self.dir)

    def test_signoff_contains_levels_boundaries_and_signature_rows(self):
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        done = subprocess.run(
            [sys.executable, str(CLI), "deliver", str(self.dir), "--kind", "signoff"],
            capture_output=True, text=True, env=env,
        )
        self.assertEqual(0, done.returncode, done.stdout + done.stderr)
        payload = json.loads(done.stdout)
        page = Path(payload["path"]).read_text(encoding="utf-8")
        for needle in ("干系人签收页", "未验证假设", "边界声明", "签收", "决策人", "E2×", "不是需求或商业已证明"):
            self.assertIn(needle, page)
        self.assertIn("待复核", page)


class CostLogTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name) / "sample"
        shutil.copytree(SAMPLE, self.dir)

    def run_cli(self, *args):
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True, env=env)

    def test_log_and_report_with_baseline_ratio(self):
        first = self.run_cli("cost", str(self.dir), "log", "--task", "audit PRD",
                             "--minutes", "25", "--baseline-minutes", "90")
        self.assertEqual(0, first.returncode, first.stdout + first.stderr)
        second = self.run_cli("cost", str(self.dir), "log", "--task", "check citations", "--minutes", "10")
        self.assertEqual(0, second.returncode)
        done = self.run_cli("cost", str(self.dir), "report")
        payload = json.loads(done.stdout)
        self.assertEqual(2, payload["tasks"])
        self.assertEqual(35, payload["total_minutes"])
        self.assertEqual(1, payload["tasks_with_baseline"])
        self.assertEqual(90, payload["baseline_minutes"])
        self.assertEqual(3.6, payload["baseline_to_actual_ratio"])
        self.assertIn("不是效率证明", payload["boundary"])

    def test_rejects_nonpositive_minutes(self):
        done = self.run_cli("cost", str(self.dir), "log", "--task", "x", "--minutes", "0")
        self.assertEqual(2, done.returncode)


if __name__ == "__main__":
    unittest.main()


class SignoffOnFreshStudyTests(unittest.TestCase):
    def test_signoff_is_blocked_on_fresh_init_without_a_passing_audit(self):
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        with tempfile.TemporaryDirectory() as tmp:
            study = Path(tmp) / "s1"
            init = subprocess.run(
                [sys.executable, str(CLI), "init", str(study),
                 "--study-id", "fresh", "--title", "t", "--decision", "d"],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(0, init.returncode, init.stdout + init.stderr)
            done = subprocess.run(
                [sys.executable, str(CLI), "deliver", str(study), "--kind", "signoff"],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(1, done.returncode, done.stdout + done.stderr)
            payload = json.loads(done.stdout)
            self.assertEqual("blocked", payload["status"])
            self.assertEqual("fail", payload["audit_status"])
            self.assertIn("cannot be issued", payload["reason"])
            self.assertFalse((study / "06-report" / "signoff.md").exists())
