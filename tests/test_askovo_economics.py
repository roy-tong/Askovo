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
SAMPLE = ROOT / "examples/sample-study"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        check=False,
        capture_output=True,
        text=True,
    )


class EconomicsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.study = Path(tempfile.mkdtemp(prefix="askovo-econ-")) / "study"
        shutil.copytree(SAMPLE, self.study)
        self.addCleanup(shutil.rmtree, self.study.parent, ignore_errors=True)

    def _inject_business_numbers(self) -> None:
        path = self.study / "04-findings/product-reasoning.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        business = data["chains"][0]["nodes"]["business"]
        business["pricing"] = [
            {
                "model": "pilot_subscription",
                "amount": 199,
                "currency": "CNY",
                "unit": "pilot",
                "term": "monthly",
                "evidence_type": "paid",
                "evidence_ids": ["R04"],
            }
        ]
        business["unit_economics_inputs"] = [
            {"metric": "Device cost per pilot", "value": 60, "unit": "pilot", "source_ref": "fin-2026-10", "status": "assumption"},
            {"metric": "Support cost per pilot", "value": 39, "unit": "pilot", "source_ref": "fin-2026-10", "status": "assumption"},
            {"metric": "Churn rate", "value": 0.08, "unit": "monthly_ratio", "source_ref": "ops-2026-09", "status": "assumption"},
            {"metric": "CAC", "value": None, "unit": "pilot", "source_ref": "", "status": "unknown"},
        ]
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def test_sample_renders_unknowns_without_inventing_zeros(self) -> None:
        completed = run_cli("economics", str(self.study))
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        report = (self.study / "06-report/unit-economics.md").read_text(encoding="utf-8")
        self.assertIn("null 表示未知，不是零", report)
        self.assertIn("不构成商业证明", report)
        payload = json.loads(completed.stdout)
        chain = payload["chains"][0]
        self.assertGreaterEqual(chain["unknown_inputs"], 1)
        self.assertFalse(chain["computed"])

    def test_numeric_projection_computes_only_unit_matched_inputs(self) -> None:
        self._inject_business_numbers()
        completed = run_cli("economics", str(self.study))
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        report = (self.study / "06-report/unit-economics.md").read_text(encoding="utf-8")
        self.assertIn("199 − 60 = 139", report)
        self.assertIn("199 − 39 = 160", report)
        self.assertIn("99", report)  # indicative cost-like sum
        self.assertIn("50.3%", report)  # indicative margin
        self.assertNotIn("Churn rate：199", report)  # unit mismatch never enters the arithmetic
        payload = json.loads(completed.stdout)
        chain = payload["chains"][0]
        self.assertTrue(chain["computed"])
        self.assertEqual(2, chain["unit_matched_inputs"])
        self.assertEqual(1, chain["unknown_inputs"])

    def test_numeric_input_without_source_ref_never_computes(self) -> None:
        path = self.study / "04-findings/product-reasoning.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        business = data["chains"][0]["nodes"]["business"]
        business["pricing"] = [
            {"model": "flat", "amount": 100, "currency": "CNY", "unit": "seat", "term": "monthly",
             "evidence_type": "paid", "evidence_ids": []}
        ]
        business["unit_economics_inputs"] = [
            {"metric": "Serving cost", "value": 20, "unit": "seat", "source_ref": "", "status": "assumption"},
        ]
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        completed = run_cli("economics", str(self.study))
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        report = (self.study / "06-report/unit-economics.md").read_text(encoding="utf-8")
        self.assertIn("缺少 source_ref，不进入计算", report)
        self.assertNotIn("100 − 20", report)
        payload = json.loads(completed.stdout)
        self.assertEqual(1, payload["chains"][0]["provenance_warnings"])

    def test_missing_study_is_a_usage_error(self) -> None:
        completed = run_cli("economics", str(self.study / "nowhere"))
        self.assertEqual(2, completed.returncode)


class PsmTests(unittest.TestCase):
    def setUp(self) -> None:
        self.study = Path(tempfile.mkdtemp(prefix="askovo-psm-")) / "study"
        shutil.copytree(SAMPLE, self.study)
        self.addCleanup(shutil.rmtree, self.study.parent, ignore_errors=True)
        self.csv = self.study.parent / "psm.csv"

    def test_symmetric_sample_matches_hand_computed_intersections(self) -> None:
        self.csv.write_text(
            "respondent_id,too_cheap,cheap,expensive,too_expensive\n"
            "r1,20,50,100,200\nr2,30,60,120,240\nr3,40,70,140,280\n"
            "r4,50,80,160,320\nr5,60,90,180,360\nr6,90,40,100,150\n",
            encoding="utf-8",
        )
        completed = run_cli("psm", str(self.study), "--input", str(self.csv), "--currency", "CNY")
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(5, payload["valid_rows"])
        self.assertEqual(1, payload["rejected_rows"])  # r6 violates the ordering invariant
        points = payload["intersections"]
        self.assertAlmostEqual(80.0, points["pmc"], places=6)
        self.assertAlmostEqual(130.0, points["opp"], places=6)
        self.assertAlmostEqual(95.0, points["idp"], places=6)
        self.assertAlmostEqual(145.0, points["pme"], places=6)
        report = (self.study / "06-report/pricing-psm.md").read_text(encoding="utf-8")
        self.assertIn("80.00 – 145.00 CNY", report)
        self.assertIn("陈述意向，不是付费行为", report)

    def test_chinese_column_aliases_are_accepted(self) -> None:
        self.csv.write_text(
            "respondent_id,太便宜,便宜,贵,太贵\na,10,20,30,40\nb,12,22,32,42\n",
            encoding="utf-8",
        )
        completed = run_cli("psm", str(self.study), "--input", str(self.csv))
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(2, payload["valid_rows"])

    def test_single_row_is_insufficient(self) -> None:
        self.csv.write_text(
            "respondent_id,too_cheap,cheap,expensive,too_expensive\na,10,20,30,40\n",
            encoding="utf-8",
        )
        completed = run_cli("psm", str(self.study), "--input", str(self.csv))
        self.assertEqual(1, completed.returncode)

    def test_missing_columns_is_a_usage_error(self) -> None:
        self.csv.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
        completed = run_cli("psm", str(self.study), "--input", str(self.csv))
        self.assertEqual(2, completed.returncode)
        self.assertIn("缺少列", completed.stderr)

    def test_missing_input_file_is_a_usage_error(self) -> None:
        completed = run_cli("psm", str(self.study), "--input", str(self.study / "nope.csv"))
        self.assertEqual(2, completed.returncode)


if __name__ == "__main__":
    unittest.main()
