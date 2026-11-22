"""Collection policy layer: a budget per platform, never an access permission.

Covers the registry contract (access modes inside the catalog, budgets no
looser than the runtime policy, graded signals, dated sources, blocked
platforms excluded), the engine surface (`--collection-policies`, JSON) and
the doctor gate.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/askovo/scripts/askovo.py"
ASSETS = ROOT / "skills/askovo/assets"
SCRIPTS = ROOT / "skills/askovo/scripts"
PRIORITY = ("reddit", "amazon", "kickstarter", "instagram", "youtube")

sys.path.insert(0, str(SCRIPTS))
import sure_engine  # noqa: E402
sys.path.pop(0)  # keep scripts/ out of the front of sys.path so `import askovo` still resolves to the package


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args], check=False, capture_output=True, text=True
    )


def load_registry() -> dict:
    return json.loads((ASSETS / "platform-field-notes.json").read_text(encoding="utf-8"))


class CollectionPolicyRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = load_registry()
        self.section = self.registry["collection_policies"]
        self.catalog = json.loads((ASSETS / "platform-catalog.json").read_text(encoding="utf-8"))
        self.catalog_index = {
            str(item["id"]): item for item in self.catalog["platforms"] if item.get("id")
        }

    def test_doctor_gate_passes(self) -> None:
        self.assertEqual([], sure_engine.collection_policy_problems())

    def test_section_is_dated_and_reviewed_later(self) -> None:
        self.assertEqual("1.0", self.section["schema_version"])
        self.assertRegex(self.section["generated_at"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertRegex(self.section["review_by"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertGreater(self.section["review_by"], self.section["generated_at"])
        self.assertEqual({"block", "throttle", "watch"}, set(self.section["levels"]))

    def test_priority_platforms_have_a_policy(self) -> None:
        for platform in PRIORITY:
            self.assertIn(platform, self.section["platforms"])

    def test_access_modes_stay_inside_the_catalog(self) -> None:
        for platform, entry in self.section["platforms"].items():
            allowed = set(self.catalog_index[platform]["access_modes"])
            self.assertTrue(set(entry["access_modes"]) <= allowed, platform)

    def test_no_policy_for_a_blocked_platform(self) -> None:
        blocked = {
            pid for pid, item in self.catalog_index.items() if item.get("decision") == "blocked"
        }
        self.assertFalse(blocked & set(self.section["platforms"]))
        excluded = {str(item["platform"]) for item in self.section["excluded"]}
        self.assertEqual(blocked, excluded)

    def test_every_platform_carries_a_block_signal_and_sourced_claims(self) -> None:
        for platform, entry in self.section["platforms"].items():
            levels = [str(signal["level"]) for signal in entry["signals"]]
            self.assertIn("block", levels, platform)
            grades = {str(source["grade"]) for source in entry["sources"]}
            self.assertTrue(grades & {"official", "craft"}, platform)
            self.assertIsInstance(entry["unverified"], list, platform)

    def test_collection_budget_and_stop_rules_reach_the_runtime(self) -> None:
        cdp_strategy = sure_engine._cdp_strategy()
        for platform, entry in self.section["platforms"].items():
            with self.subTest(platform=platform):
                enforced = cdp_strategy.policy_for(platform)
                budget = entry["budget"]
                self.assertEqual(budget["cadence_seconds"], enforced.cadence_seconds)
                self.assertEqual(budget["session_minutes"], enforced.session_minutes)
                self.assertEqual(budget["budget_fraction"], enforced.budget_fraction)
                self.assertEqual(tuple(entry["stop_rules"]), enforced.collection_stop_rules)
                self.assertIn("collection_policy", enforced.source)

    def test_budget_is_not_looser_than_the_runtime_policy(self) -> None:
        cdp_strategy = sure_engine._cdp_strategy()

        for platform, entry in self.section["platforms"].items():
            enforced = cdp_strategy.policy_for(platform)
            budget = entry["budget"]
            self.assertGreaterEqual(budget["cadence_seconds"], enforced.cadence_seconds, platform)
            self.assertLessEqual(budget["session_minutes"], enforced.session_minutes, platform)
            self.assertLessEqual(budget["budget_fraction"], enforced.budget_fraction, platform)

    def test_validator_catches_regressions(self) -> None:
        cases = {
            "looser than the runtime policy": lambda s: s["platforms"]["reddit"]["budget"].__setitem__(
                "cadence_seconds", 0.5
            ),
            "outside the platform catalog": lambda s: s["platforms"]["amazon"]["access_modes"].append(
                "scrape_anything"
            ),
            "needs at least one block-level signal": self._demote_blocks,
            "no exclusion note": lambda s: s.__setitem__(
                "excluded", [item for item in s["excluded"] if item["platform"] != "jd"]
            ),
            "experience values may only slow a run down": lambda s: s["platforms"]["reddit"][
                "observed"
            ][0].__setitem__("suggested_cadence_seconds", 0.5),
            "confidence must be one of": lambda s: s["platforms"]["amazon"]["observed"][
                0
            ].__setitem__("confidence", "certain"),
            "observed must be present": lambda s: s["platforms"]["youtube"].pop("observed"),
            "must be an http(s) URL": lambda s: s["platforms"]["github"]["observed"][
                0
            ].__setitem__("source_urls", ["not a url"]),
        }
        for expected, mutate in cases.items():
            section = copy.deepcopy(self.section)
            mutate(section)
            problems = self._problems_with(section)
            self.assertTrue(
                any(expected in problem for problem in problems),
                f"{expected}: {problems}",
            )

    def test_every_platform_carries_dated_observed_entries(self) -> None:
        for platform, entry in self.section["platforms"].items():
            observed = entry["observed"]
            self.assertTrue(observed, platform)
            ids = [str(item["id"]) for item in observed]
            self.assertEqual(len(ids), len(set(ids)), platform)
            for item in observed:
                self.assertIn(item["confidence"], ("high", "medium", "low"), platform)
                self.assertRegex(item["as_of"], r"^\d{4}-\d{2}-\d{2}$", platform)
                self.assertTrue(item["source_urls"], platform)
                for url in item["source_urls"]:
                    self.assertTrue(str(url).startswith(("http://", "https://")), platform)

    def test_observed_suggestions_never_speed_up_the_budget(self) -> None:
        for platform, entry in self.section["platforms"].items():
            floor = entry["budget"]["cadence_seconds"]
            for item in entry["observed"]:
                suggested = item.get("suggested_cadence_seconds")
                if suggested is not None:
                    self.assertGreaterEqual(suggested, floor, f"{platform}/{item['id']}")

    @staticmethod
    def _demote_blocks(section: dict) -> None:
        for signal in section["platforms"]["youtube"]["signals"]:
            if signal["level"] == "block":
                signal["level"] = "throttle"

    def _problems_with(self, section: dict) -> list[str]:
        data = copy.deepcopy(self.registry)
        data["collection_policies"] = section
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        ) as handle:
            json.dump(data, handle, ensure_ascii=False)
            path = Path(handle.name)
        original = sure_engine.FIELD_NOTES_PATH
        sure_engine.FIELD_NOTES_PATH = path
        try:
            return sure_engine.collection_policy_problems()
        finally:
            sure_engine.FIELD_NOTES_PATH = original
            path.unlink(missing_ok=True)


class CollectionPolicyCliTests(unittest.TestCase):
    def test_markdown_card_renders_budget_and_sources(self) -> None:
        result = run_cli("platforms", "Reddit 和 Kickstarter 的用户抱怨", "--collection-policies")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("# Askovo 采集策略卡", result.stdout)
        self.assertIn("2027-02-21", result.stdout)
        self.assertIn("策略是**预算**，不是访问许可", result.stdout)
        self.assertIn("public-api-shutdown", result.stdout)
        self.assertIn("社区经验：5 条（high 4 / medium 1 / low 0）", result.stdout)
        self.assertIn("## 不做", result.stdout)

    def test_json_carries_collection_policy(self) -> None:
        result = run_cli("platforms", "Reddit 和 Kickstarter 的用户抱怨", "--json")
        self.assertEqual(0, result.returncode, result.stderr)
        plan = json.loads(result.stdout)
        policies = plan["collection_policies"]
        self.assertIn("reddit", policies)
        self.assertEqual("2027-02-21", policies["reddit"]["review_by"])
        for item in plan["recommended"]:
            if item["id"] in policies:
                self.assertEqual(policies[item["id"]], item["collection_policy"])

    def test_blocked_platform_filter_gets_no_card(self) -> None:
        result = run_cli("platforms", "知乎讨论", "--platform", "zhihu", "--collection-policies")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("本次选择里没有可采集策略", result.stdout)


if __name__ == "__main__":
    unittest.main()
