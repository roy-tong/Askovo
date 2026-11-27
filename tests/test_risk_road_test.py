"""Risk gate coverage for road and driving-safety studies.

The 2026-11-26 campaign found that "在真实道路上测试驾驶分心预警原型" reached a
research plan with ``safety_gate=clear``: the road_test rule only listed
"开放道路/实车路测/上路测试" and missed ordinary road/driving wording. The rule
stays a review gate — it never blocks research by itself, and a car-cabin
study without a test still stays clear.
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/askovo/scripts"

spec = importlib.util.spec_from_file_location("sure_engine_risk_test",
                                              SCRIPTS / "sure_engine.py")
engine = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = engine
spec.loader.exec_module(engine)


def flags(text: str) -> set[str]:
    return {row["flag"] for row in engine.detect_risks(text)}


class RoadTestRiskTests(unittest.TestCase):
    def test_real_road_test_wording_is_flagged(self) -> None:
        self.assertIn("road_test", flags("在真实道路上测试驾驶分心预警原型"))

    def test_distraction_and_road_test_phrases_are_flagged(self) -> None:
        for text in ("开放道路实车验证", "分心驾驶场景观察", "驾驶分心预警的实车测试",
                     "on-road validation of a driver distraction warning",
                     "road test with real drivers"):
            self.assertIn("road_test", flags(text), text)

    def test_cabin_research_without_a_test_stays_clear(self) -> None:
        self.assertEqual(set(), flags("车载语音助手的场景与需求研究"))

    def test_other_risk_flags_are_unaffected(self) -> None:
        self.assertIn("skin_contact", flags("未成年人的眼霜皮肤接触测试"))
        self.assertIn("destructive_test", flags("给生产数据库做破坏性测试"))


if __name__ == "__main__":
    unittest.main()
