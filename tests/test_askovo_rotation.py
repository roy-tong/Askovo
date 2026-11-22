"""Multi-platform rotation strategy: cadence, rotation, cooldown and session health.

Covers the runtime scheduler (`connectors/rotation.py`), the strategy layer in the
field-notes registry, and the engine surface that exposes it.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONNECTORS = ROOT / "skills/askovo/scripts/connectors"
CLI = ROOT / "skills/askovo/scripts/askovo.py"
ASSETS = ROOT / "skills/askovo/assets"
if str(CONNECTORS) not in sys.path:
    sys.path.insert(0, str(CONNECTORS))

import rotation  # noqa: E402


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(CLI), *args], check=False, capture_output=True, text=True)


class CadenceTests(unittest.TestCase):
    def test_default_cadences_follow_the_field_numbers(self) -> None:
        cadences = {item.platform: item for item in rotation.build_cadences(["reddit", "youtube", "discord", "x"])}
        self.assertEqual(3.0, cadences["reddit"].min_interval)
        self.assertEqual(3.0, cadences["youtube"].min_interval)
        self.assertEqual(20.0, cadences["discord"].min_interval)
        self.assertTrue(cadences["discord"].requires_session)
        self.assertFalse(cadences["reddit"].requires_session)
        self.assertEqual("elevated", cadences["x"].risk_tier)

    def test_unknown_platform_gets_a_conservative_default(self) -> None:
        (cadence,) = rotation.build_cadences(["some_new_site"])
        self.assertEqual(3.0, cadence.min_interval)
        self.assertFalse(cadence.requires_session)

    def test_duplicate_platform_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            rotation.RotationScheduler([rotation.Cadence("x"), rotation.Cadence("x")])

    def test_negative_interval_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            rotation.RotationScheduler([rotation.Cadence("x", min_interval=-1)])

    def test_empty_scheduler_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            rotation.RotationScheduler([])


class RotationSchedulerTests(unittest.TestCase):
    def make(self, platforms=("reddit", "youtube", "discord"), **kwargs):
        now = [1000.0]

        def sleep(seconds: float) -> None:
            now[0] += seconds

        scheduler = rotation.RotationScheduler(
            rotation.build_cadences(list(platforms), **kwargs),
            clock=lambda: now[0],
            sleep=sleep,
        )
        return scheduler, now

    def test_round_order_prefers_the_fastest_cadence(self) -> None:
        scheduler, _ = self.make()
        self.assertEqual(["reddit", "youtube", "discord"], scheduler.plan_round())

    def test_plan_round_limit(self) -> None:
        scheduler, _ = self.make()
        self.assertEqual(["reddit", "youtube"], scheduler.plan_round(limit=2))

    def test_per_site_minimum_interval_blocks_a_second_hit(self) -> None:
        scheduler, _ = self.make()
        self.assertEqual(0.0, scheduler.acquire("reddit"))
        with self.assertRaises(rotation.PlatformCooling) as caught:
            scheduler.acquire("reddit")
        self.assertLessEqual(caught.exception.wait_seconds, 3.0)
        self.assertEqual("min_interval", caught.exception.reason)

    def test_rotation_to_another_site_is_never_blocked(self) -> None:
        scheduler, _ = self.make()
        scheduler.acquire("reddit")
        scheduler.acquire("youtube")  # different site: the whole point of rotation
        self.assertEqual("discord", scheduler.next_platform())

    def test_acquire_wait_sleeps_out_the_cadence(self) -> None:
        scheduler, now = self.make()
        scheduler.acquire("reddit")
        waited = scheduler.acquire("reddit", wait=True)
        self.assertGreater(waited, 0)
        self.assertGreaterEqual(now[0], 1003.0)

    def test_rate_limit_reset_header_pushes_the_next_slot(self) -> None:
        scheduler, _ = self.make()
        decision = scheduler.record_error("reddit", 429, {"X-RateLimit-Reset": "60"})
        self.assertEqual("rate_limit_reset", decision["reason"])
        self.assertEqual(60.0, decision["next_ready_in"])
        self.assertEqual(60.0, scheduler.seconds_until_ready("reddit"))
        self.assertFalse(decision["requires_human"])

    def test_slow_down_retries_exponentially(self) -> None:
        scheduler, _ = self.make()
        first = scheduler.record_error("reddit", 422)
        second = scheduler.record_error("reddit", 422)
        self.assertEqual("slow_down", first["reason"])
        self.assertGreater(second["next_ready_in"], first["next_ready_in"])

    def test_permanent_status_requires_a_human(self) -> None:
        scheduler, _ = self.make()
        decision = scheduler.record_error("youtube", 404)
        self.assertTrue(decision["requires_human"])
        self.assertEqual(float("inf"), scheduler.seconds_until_ready("youtube"))

    def test_session_drop_gates_the_platform_and_rotation_continues(self) -> None:
        scheduler, _ = self.make()
        scheduler.record_session_drop("discord")
        self.assertEqual(float("inf"), scheduler.seconds_until_ready("discord"))
        self.assertEqual("reddit", scheduler.next_platform())
        scheduler.record_human_relogin("discord")
        self.assertEqual(0.0, scheduler.seconds_until_ready("discord"))
        self.assertEqual("discord", scheduler.next_platform())

    def test_daily_cap_cools_until_the_next_day(self) -> None:
        now = [1000.0]
        scheduler = rotation.RotationScheduler(
            [rotation.Cadence("vertical_forum", min_interval=0.0, daily_cap=1)],
            clock=lambda: now[0],
        )
        scheduler.acquire("vertical_forum")
        with self.assertRaises(rotation.PlatformCooling) as caught:
            scheduler.acquire("vertical_forum")
        self.assertEqual("daily_cap", caught.exception.reason)
        self.assertGreater(caught.exception.wait_seconds, 0)

    def test_success_resets_the_attempt_counter(self) -> None:
        scheduler, _ = self.make()
        scheduler.record_error("reddit", 422)
        scheduler.record_success("reddit")
        self.assertEqual(0, scheduler.snapshot()["platforms"]["reddit"]["attempt"])

    def test_snapshot_and_resume_keep_the_slot(self) -> None:
        scheduler, _ = self.make()
        scheduler.acquire("reddit")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rotation.json"
            scheduler.save(path)
            self.assertTrue(path.is_file())
            resumed = rotation.RotationScheduler.load(path, clock=lambda: 1000.0)
            self.assertGreater(resumed.seconds_until_ready("reddit"), 0)
            self.assertIn(resumed.next_platform(), {"youtube", "discord"})

    def test_selftest_exits_clean(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(CONNECTORS / "rotation.py"), "--selftest"],
            check=False, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("[ok]", completed.stdout)

    def test_plan_cli_orders_platforms(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(CONNECTORS / "rotation.py"), "--plan", "discord,reddit,youtube"],
            check=False, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(["reddit", "youtube", "discord"], payload["round"])


class StrategyRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = json.loads((ASSETS / "platform-field-notes.json").read_text(encoding="utf-8"))
        self.catalog = json.loads((ASSETS / "platform-catalog.json").read_text(encoding="utf-8"))
        self.catalog_ids = {str(item["id"]) for item in self.catalog["platforms"]}
        self.legend = set(self.registry["verification_legend"])

    def strategies(self) -> list[dict]:
        return self.registry.get("strategies") or []

    def test_strategy_layer_exists(self) -> None:
        self.assertGreaterEqual(len(self.strategies()), 10)

    def test_required_fields_and_unique_ids(self) -> None:
        required = (
            "id", "name", "when", "invariant", "mechanism", "platforms",
            "artifacts", "verification",
        )
        seen: set[str] = set()
        for strategy in self.strategies():
            with self.subTest(strategy=strategy.get("id")):
                for key in required:
                    self.assertNotIn(strategy.get(key), (None, "", []), f"{strategy.get('id')} missing {key}")
                self.assertNotIn(strategy["id"], seen, "duplicate strategy id")
                seen.add(strategy["id"])

    def test_platforms_are_catalog_ids_or_wildcard(self) -> None:
        allowed = self.catalog_ids | set(self.registry.get("source_types") or {}) | {"*"}
        for strategy in self.strategies():
            with self.subTest(strategy=strategy["id"]):
                for platform in strategy["platforms"]:
                    self.assertIn(platform, allowed)

    def test_artifacts_and_helpers_resolve(self) -> None:
        for strategy in self.strategies():
            with self.subTest(strategy=strategy["id"]):
                for artifact in strategy["artifacts"]:
                    self.assertTrue((ROOT / artifact).is_file(), artifact)
                helper = strategy.get("helper")
                if helper:
                    module_name, _, attr = helper.rpartition(".")
                    module_path = ROOT / "skills/askovo/scripts" / (module_name.replace(".", "/") + ".py")
                    self.assertTrue(module_path.is_file(), helper)
                    self.assertIn(attr, module_path.read_text(encoding="utf-8"))

    def test_verification_uses_the_legend(self) -> None:
        for strategy in self.strategies():
            with self.subTest(strategy=strategy["id"]):
                self.assertIn(strategy["verification"]["status"], self.legend)
                self.assertRegex(strategy["verification"]["date"], r"^\d{4}-\d{2}-\d{2}$")
                self.assertTrue(strategy["verification"]["evidence"])

    def test_late_campaign_strategies_are_registered(self) -> None:
        by_id = {strategy["id"]: strategy for strategy in self.strategies()}
        guards = self.registry["runtime_policies"]["guards"]
        for strategy_id in ("classification-coverage", "field-preservation"):
            with self.subTest(strategy=strategy_id):
                self.assertIn(strategy_id, by_id)
                self.assertEqual("operator", by_id[strategy_id]["enforcement"])
                self.assertNotIn(strategy_id, guards)
        self.assertEqual("runtime", by_id["join-is-not-access"]["enforcement"])
        self.assertIn("join-is-not-access", guards)
        self.assertIn("derived output", by_id["single-writer-quota"]["invariant"])
        self.assertIn("word choice", by_id["multilingual-routing"]["invariant"].lower())

    def test_rotation_invariants_are_explicit(self) -> None:
        by_id = {strategy["id"]: strategy for strategy in self.strategies()}
        for required in ("platform-rotation", "per-site-frequency-invariant", "single-writer-quota"):
            with self.subTest(strategy=required):
                self.assertIn(required, by_id)
        self.assertIn("never", by_id["platform-rotation"]["invariant"])
        self.assertIn("identity", by_id["backup-channel-pivot"]["invariant"])


class StrategyEngineTests(unittest.TestCase):
    def test_doctor_reports_the_strategy_layer(self) -> None:
        completed = run_cli("doctor")
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertRegex(completed.stdout, r"\[ok\] collection-strategies \d+ strategies")

    def test_platforms_strategies_view(self) -> None:
        completed = run_cli("platforms", "Discord 和 Kickstarter 的多平台采集", "--strategies")
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("多平台采集策略", completed.stdout)
        self.assertIn("Platform rotation", completed.stdout)
        self.assertIn("不是许可", completed.stdout)

    def test_platforms_json_carries_strategies(self) -> None:
        completed = run_cli("platforms", "Discord 和 Kickstarter 的多平台采集", "--json")
        self.assertEqual(0, completed.returncode, completed.stderr)
        payload = json.loads(completed.stdout)
        ids = {strategy["id"] for strategy in payload["strategies"]}
        self.assertIn("platform-rotation", ids)
        self.assertIn("per-site-frequency-invariant", ids)

    def test_default_radar_markdown_surfaces_strategies(self) -> None:
        completed = run_cli("platforms", "Discord 和 Kickstarter 的多平台采集")
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("多平台轮转策略", completed.stdout)

    def test_mcp_platforms_accepts_strategies(self) -> None:
        sys.path.insert(0, str(ROOT / "skills/askovo/scripts"))
        try:
            import askovo_mcp  # noqa: WPS433 - local import keeps sys.path fixture
        finally:
            sys.path.pop(0)
        namespace = askovo_mcp._build_platforms(
            {"need": "多平台采集", "strategies": True, "field_notes": True, "platform": "discord"}
        )
        self.assertTrue(namespace.strategies)
        self.assertTrue(namespace.field_notes)
        self.assertEqual("discord", namespace.platform)


if __name__ == "__main__":
    unittest.main()
