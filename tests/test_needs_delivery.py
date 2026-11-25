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
MCP = ROOT / "skills/askovo/scripts/askovo_mcp.py"
SAMPLE = ROOT / "examples/sample-study"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )


def run_mcp(request: dict) -> dict:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, str(MCP)],
        input=json.dumps(request) + "\n",
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    return json.loads(completed.stdout)


class NeedsDeliveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="askovo-needs-"))
        self.study = self.tmp / "study"
        shutil.copytree(SAMPLE, self.study)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_needs_report_leads_with_demand_and_does_not_invent_changes(self) -> None:
        evidence_path = self.study / "02-data/evidence.jsonl"
        records = [json.loads(line) for line in evidence_path.read_text(encoding="utf-8").splitlines() if line]
        records[0]["text_excerpt"] = "The pet is outside the camera view"
        records[0]["captured_at"] = "2026-11-01"
        evidence_path.write_text(
            "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
            encoding="utf-8",
        )
        result = run_cli("deliver", str(self.study), "--kind", "needs")

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("written", payload["status"])
        self.assertTrue(payload["path"].endswith("06-report/needs.md"))
        text = (self.study / "06-report/needs.md").read_text(encoding="utf-8")
        demand = text.index("## 1. 场景—痛点—需求")
        solution = text.index("## 2. 需求—特性—产品")
        business = text.index("## 3. 特性—产品—商业")
        self.assertLess(demand, solution)
        self.assertLess(solution, business)
        self.assertIn("An unusual-noise alert", text)
        self.assertIn("Fixed cameras or asking a neighbor", text)
        self.assertIn("Determine whether intervention is needed", text)
        self.assertIn("来源 interview", text)
        self.assertIn("时间窗 2026-11-01", text)
        self.assertIn("来自语料的声音", text)
        self.assertIn("The pet is outside the camera view", text)
        self.assertIn("未提供前后基线", text)
        self.assertIn("不自动算作新增需求", text)
        self.assertNotIn("先卖给谁", text)
        self.assertNotIn("怎么收钱", text)

    def test_needs_report_compares_demand_before_solution_and_business(self) -> None:
        baseline = self.tmp / "baseline"
        shutil.copytree(SAMPLE, baseline)
        path = self.study / "04-findings/product-reasoning.json"
        reasoning = json.loads(path.read_text(encoding="utf-8"))
        first = reasoning["chains"][0]
        first["nodes"]["need"]["desired_outcome"] = "Verify any blind spot without returning home"
        second = json.loads(json.dumps(first))
        second["id"] = "PR02"
        second["title"] = "Avatar integration for application developers"
        second["demand_judgment_id"] = "D02"
        second["nodes"]["scene"]["statement"] = "A developer integrates an avatar into an application"
        second["nodes"]["user"]["role"] = "Application developer"
        second["nodes"]["pain"]["statement"] = "Avatar formats and mappings conflict"
        second["nodes"]["need"]["desired_outcome"] = "Integrate lip sync with predictable effort"
        reasoning["chains"].append(second)
        path.write_text(json.dumps(reasoning, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        result = run_cli(
            "deliver", str(self.study), "--kind", "needs", "--baseline", str(baseline),
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("--baseline", payload["chat_summary"]["reproduce_command"])
        self.assertIn(str(baseline), payload["chat_summary"]["reproduce_command"])
        text = (self.study / "06-report/needs.md").read_text(encoding="utf-8")
        self.assertIn("## 0. 需求变化总览", text)
        self.assertIn("新增需求链 1", text)
        self.assertIn("新增不等于已验证", text)
        self.assertIn("Avatar integration for application developers", text)
        self.assertIn("需求表述变化", text)
        self.assertIn("Verify any blind spot without returning home", text)
        self.assertIn("Determine whether intervention is needed", text)
        self.assertLess(text.index("### 场景、痛点或需求变化"), text.index("### 特性或产品变化"))
        self.assertLess(text.index("### 特性或产品变化"), text.index("### 商业变化"))
        main = text.split("## 附录：", 1)[0]
        self.assertIn("新增方向", main)
        self.assertIn("以前", main)
        self.assertIn("现在", main)
        self.assertNotIn("`PR02`", main)

    def test_business_comparison_includes_structured_pricing_changes(self) -> None:
        baseline = self.tmp / "baseline"
        shutil.copytree(SAMPLE, baseline)
        path = self.study / "04-findings/product-reasoning.json"
        reasoning = json.loads(path.read_text(encoding="utf-8"))
        reasoning["chains"][0]["nodes"]["business"]["pricing"] = [
            {"model": "seat", "amount": 100, "currency": "USD", "unit": "month"},
        ]
        path.write_text(json.dumps(reasoning, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        result = run_cli(
            "deliver", str(self.study), "--kind", "needs", "--baseline", str(baseline),
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(1, payload["comparison"]["counts"]["business"])
        text = (self.study / "06-report/needs.md").read_text(encoding="utf-8")
        self.assertIn("商业 / 定价假设", text)
        self.assertIn("model=seat", text)
        self.assertIn("amount=100", text)

    def test_identical_baseline_does_not_fabricate_business_changes(self) -> None:
        result = run_cli(
            "deliver", str(self.study), "--kind", "needs", "--baseline", str(self.study),
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(
            {"added": 0, "removed": 0, "demand": 0, "solution": 0, "business": 0, "evidence": 0, "status": 0},
            payload["comparison"]["counts"],
        )
        text = (self.study / "06-report/needs.md").read_text(encoding="utf-8")
        main = text.split("## 附录：", 1)[0]
        self.assertIn("没有发现新增需求，也没有改变既有产品和商业判断", main)
        self.assertNotIn("新增需求链 0", main)
        self.assertNotIn("证据绑定变化", main)
        self.assertIn("新增需求链 0", text)
        self.assertIn("- 无新增需求链。", text)
        self.assertEqual(3, text.count("- 无语义字段变化。"))

    def test_main_report_is_written_for_business_readers(self) -> None:
        evidence_path = self.study / "02-data/evidence.jsonl"
        records = [json.loads(line) for line in evidence_path.read_text(encoding="utf-8").splitlines() if line]
        records[0]["text_excerpt"] = "The pet is outside the camera view"
        evidence_path.write_text(
            "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
            encoding="utf-8",
        )
        result = run_cli("deliver", str(self.study), "--kind", "needs")

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        text = (self.study / "06-report/needs.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# 业务需求报告"), text[:200])
        main = text.split("## 附录：", 1)[0]
        self.assertIn("面向业务负责人、产品经理和需求分析人员", main)
        self.assertIn("## 业务结论", main)
        self.assertIn("## 当前需求方向", main)
        self.assertIn("## 对产品方案的影响", main)
        self.assertIn("## 对商业判断的影响", main)
        self.assertIn("## 下一步怎么推进", main)
        self.assertIn("业务上怎么算有效", main)
        for token in (
            "record_id", "context_key", "canonical", "语义字段", "证据绑定",
            "来源 interview", "来自语料的声音", "hackernews", "`R01`", "E1", "审计",
        ):
            self.assertNotIn(token, main)
        self.assertIn("来自语料的声音", text)
        self.assertIn("The pet is outside the camera view", text)

    def test_chat_summary_leads_with_business_not_research_codes(self) -> None:
        result = run_cli(
            "deliver", str(self.study), "--kind", "needs", "--baseline", str(self.study),
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        summary = json.loads(result.stdout)["chat_summary"]
        self.assertEqual("business_and_product", summary["audience"])
        self.assertIn("没有发现新增需求", summary["headline"])
        text = summary["text"]
        self.assertIn("业务结论", text)
        self.assertIn("怎么判断有效", text)
        for token in (
            "审计", "Canonical", "证据", "E4", "Unknowns", "input_fingerprint",
            "reproduce_command", "decided", "context_key", "R01",
        ):
            self.assertNotIn(token, text)

    def test_baseline_is_rejected_for_non_needs_delivery(self) -> None:
        result = run_cli(
            "deliver", str(self.study), "--kind", "plan", "--baseline", str(self.study),
        )

        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertIn("only supported for --kind needs", result.stdout + result.stderr)

    def test_missing_baseline_fails_without_a_report(self) -> None:
        result = run_cli(
            "deliver", str(self.study), "--kind", "needs", "--baseline", str(self.tmp / "missing"),
        )

        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertIn("baseline product-reasoning.json not found", result.stdout + result.stderr)
        self.assertFalse((self.study / "06-report/needs.md").exists())

    def test_mcp_supports_the_same_needs_projection(self) -> None:
        response = run_mcp({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "askovo_deliver",
                "arguments": {
                    "study_dir": str(self.study),
                    "kind": "needs",
                    "baseline": str(self.study),
                },
            },
        })

        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(0, payload["exit_code"], json.dumps(payload, ensure_ascii=False))
        self.assertEqual("needs", payload["result"]["kind"])
        self.assertEqual(0, payload["result"]["comparison"]["counts"]["demand"])
        self.assertTrue((self.study / "06-report/needs.md").is_file())


if __name__ == "__main__":
    unittest.main()
