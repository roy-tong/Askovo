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


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


class EconomicsValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.study = Path(tempfile.mkdtemp(prefix="askovo-econ-validation-")) / "study"
        shutil.copytree(SAMPLE, self.study)
        self.addCleanup(shutil.rmtree, self.study.parent, ignore_errors=True)

    def _write_business(self, pricing: list[dict], inputs: list[dict]) -> None:
        path = self.study / "04-findings/product-reasoning.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        business = data["chains"][0]["nodes"]["business"]
        business["pricing"] = pricing
        business["unit_economics_inputs"] = inputs
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _price(self, **overrides: object) -> dict:
        entry = {
            "model": "pilot_subscription",
            "amount": 199,
            "currency": "CNY",
            "unit": "pilot",
            "term": "monthly",
            "evidence_type": "paid",
            "evidence_ids": ["R04"],
        }
        entry.update(overrides)
        return entry

    def _input(self, metric: str, value: object, unit: str = "pilot") -> dict:
        return {
            "metric": metric,
            "value": value,
            "unit": unit,
            "source_ref": "fin-2026-10",
            "status": "assumption",
        }

    def _economics(self) -> tuple[dict, str]:
        completed = run_cli("economics", str(self.study))
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        report = (self.study / "06-report/unit-economics.md").read_text(encoding="utf-8")
        return json.loads(completed.stdout), report

    def test_price_restated_as_input_is_not_subtracted(self) -> None:
        self._write_business(
            [self._price(model="seat_subscription", amount=50, unit="seat/month")],
            [self._input("每坐席月费", 50, unit="seat/month")],
        )
        payload, report = self._economics()
        self.assertNotIn("50 − 50", report)
        self.assertNotIn("1.00×", report)
        self.assertIn("不参与价格减法", report)
        self.assertIn("疑似重复登记", report)
        self.assertEqual("insufficient", payload["validation"]["status"])
        self.assertEqual(0, payload["validation"]["mismatch_count"])

    def test_decimal_checks_report_mismatches(self) -> None:
        self._write_business(
            [self._price(volume=5, revenue=1000)],
            [
                self._input("Device cost", 60),
                self._input("Support cost", 39),
                self._input("Total cost", 120),
                self._input("Gross profit", 80),
                self._input("Gross margin rate", 50.3),
                self._input("ROI", 1.01),
            ],
        )
        payload, report = self._economics()
        mismatches = payload["validation"]["mismatches"]
        self.assertEqual(3, payload["validation"]["mismatch_count"], mismatches)
        self.assertEqual(
            {
                "chain": payload["chains"][0]["id"],
                "code": "economics_mismatch",
                "kind": "revenue",
                "metric": "pilot_subscription · 收入",
                "expected": "995",
                "actual": "1000",
                "delta": "5",
            },
            mismatches[0],
        )
        metrics = {item["metric"]: item for item in mismatches}
        self.assertEqual("99", metrics["pilot_subscription · Total cost"]["expected"])
        self.assertEqual("120", metrics["pilot_subscription · Total cost"]["actual"])
        self.assertEqual("21", metrics["pilot_subscription · Total cost"]["delta"])
        self.assertEqual("-20", metrics["pilot_subscription · Gross profit"]["delta"])
        self.assertIn("发现 3 处声明值与确定性计算不一致", report)
        self.assertIn("应为 995，声明 1000，差 5", report)
        self.assertIn("199 − 99 = 100", report)
        self.assertIn("50.3%", report)
        # Declared margin and ROI are inside the stated tolerance: reported as consistent, not mismatched.
        self.assertEqual(3, len(mismatches))

    def test_roi_with_zero_cost_is_a_gap_not_a_crash(self) -> None:
        self._write_business(
            [self._price()],
            [
                self._input("Support cost", 0),
                self._input("ROI", 1),
            ],
        )
        payload, report = self._economics()
        self.assertEqual("insufficient", payload["validation"]["status"])
        self.assertEqual(0, payload["validation"]["mismatch_count"])
        self.assertIn("ROI 无定义", report)

    def test_validate_insufficient_without_declarations(self) -> None:
        self._write_business(
            [self._price()],
            [self._input("Device cost", 60), self._input("Support cost", 39)],
        )
        payload, report = self._economics()
        chain = payload["chains"][0]
        self.assertEqual("insufficient", chain["validation_status"])
        self.assertEqual([], chain["mismatches"])
        self.assertIn("没有可校验的数量声明", report)
        self.assertIn("199 − 99 = 100", report)

    def test_check_warns_on_unit_economics_mismatch(self) -> None:
        self._write_business(
            [self._price(model="flat", amount=100, volume=2, revenue=250)],
            [],
        )
        completed = run_cli("check", str(self.study), "--stage", "full")
        payload = json.loads(completed.stdout)
        finding = next(item for item in payload["checks"] if item["id"] == "unit_economics")
        self.assertEqual("warn", finding["status"], completed.stdout + completed.stderr)
        self.assertIn("应为 200", finding["detail"])
        self.assertIn("声明 250", finding["detail"])


if __name__ == "__main__":
    unittest.main()
