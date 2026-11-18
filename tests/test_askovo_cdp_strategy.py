#!/usr/bin/env python3
"""CDP strategy policy: registry → runtime guard → collectors and engine.

The 2026-11-17 CDP lesson was not a new page selector: a timeout/abort followed
by continued driving is what dropped Discord sessions (three times in one day),
deliberately idle sessions also fail, and a blank 200 is an unsupported stack.
These tests pin the integrated layer: the registry's ``runtime_policies`` are
the only source of budgets, ``SessionGuard`` enforces them, the collectors
persist before stopping, and the engine's capture/collect paths share the same
page triage and timeout classification.
"""
from __future__ import annotations

import importlib.util
import json
import socket
import subprocess
import types
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/askovo/scripts/askovo.py"
SCRIPTS = ROOT / "skills/askovo/scripts"
CONNECTORS = SCRIPTS / "connectors"
ASSETS = ROOT / "skills/askovo/assets"
if str(CONNECTORS) not in sys.path:
    sys.path.insert(0, str(CONNECTORS))

import cdp_strategy  # noqa: E402


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


engine = _load("sure_engine_cdp_strategy_test", SCRIPTS / "sure_engine.py")


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(CLI), *args], check=False, capture_output=True, text=True)


def load_registry() -> dict:
    return json.loads((ASSETS / "platform-field-notes.json").read_text(encoding="utf-8"))


class PolicyRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = load_registry()
        self.section = self.registry["runtime_policies"]
        self.catalog = json.loads((ASSETS / "platform-catalog.json").read_text(encoding="utf-8"))
        self.cdp_platforms = [str(item["id"]) for item in self.catalog["platforms"] if item.get("cdp")]

    def test_section_is_complete_and_valid(self) -> None:
        self.assertEqual([], cdp_strategy.policy_problems(self.section))
        for key in ("guards", "defaults", "platforms"):
            self.assertIn(key, self.section)
        for key in cdp_strategy.POLICY_KEYS:
            self.assertIn(key, self.section["defaults"])

    def test_every_cdp_platform_builds_a_policy(self) -> None:
        self.assertTrue(self.cdp_platforms)
        for platform in self.cdp_platforms:
            with self.subTest(platform=platform):
                policy = cdp_strategy.policy_for(platform)
                self.assertEqual(platform, policy.platform)
                self.assertEqual(1, policy.max_gotos_per_cell)
                self.assertFalse(policy.allow_reload)
                self.assertLess(policy.budget_fraction, 1.0)

    def test_field_numbers_reach_the_runtime(self) -> None:
        discord = cdp_strategy.policy_for("discord")
        self.assertEqual(20.0, discord.cadence_seconds)
        self.assertEqual(40.0, discord.session_minutes)
        self.assertEqual(15.0, discord.timeout_cooldown_minutes)
        self.assertEqual(0.6, discord.budget_fraction)
        self.assertTrue(discord.requires_session)
        self.assertEqual(("messages", "forum", "invite"), discord.exclusive_modes)
        self.assertEqual(36.0, discord.effective_budget(60.0))
        kickstarter = cdp_strategy.policy_for("kickstarter")
        self.assertEqual(0.7, kickstarter.budget_fraction)
        self.assertFalse(kickstarter.requires_session)

    def test_unknown_platform_gets_the_conservative_defaults(self) -> None:
        policy = cdp_strategy.policy_for("some_new_site")
        self.assertEqual(1, policy.max_gotos_per_cell)
        self.assertEqual(cdp_strategy.CHALLENGE_POLICY, policy.challenge_policy)

    def test_every_runtime_strategy_has_a_resolving_guard(self) -> None:
        strategies = {item["id"]: item for item in self.registry["strategies"]}
        guards = self.section["guards"]
        for strategy_id, record in strategies.items():
            with self.subTest(strategy=strategy_id):
                self.assertIn(record["enforcement"], ("runtime", "operator"))
                if record["enforcement"] == "runtime":
                    self.assertIn(strategy_id, guards)
        for strategy_id, helper in guards.items():
            self.assertIn(strategy_id, strategies)
            module_name, _, attr = helper.rpartition(".")
            module_path = SCRIPTS / (module_name.replace(".", "/") + ".py")
            self.assertTrue(module_path.is_file(), helper)
            source = module_path.read_text(encoding="utf-8")
            self.assertTrue(
                f"def {attr}(" in source or f"class {attr}(" in source or f"class {attr}:" in source,
                helper)

    def test_malformed_policy_is_refused(self) -> None:
        broken = json.loads(json.dumps(self.section))
        broken["defaults"]["budget_fraction"] = 1.5
        self.assertTrue(cdp_strategy.policy_problems(broken))
        with self.assertRaises(cdp_strategy.PolicyError):
            cdp_strategy.build_policy("discord", broken)
        unknown = json.loads(json.dumps(self.section))
        unknown["platforms"]["not_a_platform"] = {}
        self.assertTrue(cdp_strategy.policy_problems(unknown, known_platforms=self.cdp_platforms))
        missing = json.loads(json.dumps(self.section))
        missing["platforms"]["discord"]["allow_reload"] = True  # reload is never allowed
        self.assertTrue(cdp_strategy.policy_problems(missing, known_platforms=self.cdp_platforms))
        with self.assertRaises(cdp_strategy.PolicyError):
            cdp_strategy.load_runtime_policies(Path("/nonexistent/registry.json"))


class RotationConsistencyTests(unittest.TestCase):
    def test_rotation_reads_the_same_registry_budgets(self) -> None:
        import rotation  # noqa: WPS433 - connectors dir is on sys.path above

        for platform in ("discord", "x", "instagram", "tiktok", "kickstarter", "vertical_forum", "weibo"):
            with self.subTest(platform=platform):
                policy = cdp_strategy.policy_for(platform)
                cadence = rotation.build_cadences([platform])[0]
                self.assertEqual(policy.cadence_seconds, cadence.min_interval)
                self.assertEqual(policy.requires_session, cadence.requires_session)

    def test_archive_routes_keep_their_field_cadence(self) -> None:
        import rotation  # noqa: WPS433

        self.assertEqual(3.0, rotation.build_cadences(["reddit"])[0].min_interval)
        self.assertEqual(2.5, rotation.build_cadences(["youtube"])[0].min_interval)


class PageTriageTests(unittest.TestCase):
    def test_page_states_are_classified_in_one_place(self) -> None:
        self.assertEqual("challenge", cdp_strategy.classify_page("Just a moment...", "Just a moment..."))
        self.assertEqual("page_not_found", cdp_strategy.classify_page("Page not found", "x"))
        self.assertEqual("page_not_found", cdp_strategy.classify_page("Error 404", "x"))
        self.assertEqual("page_not_found", cdp_strategy.classify_page("页面不存在", "x"))
        self.assertEqual("blank_render", cdp_strategy.classify_page("", ""))
        self.assertEqual("content", cdp_strategy.classify_page("Product reviews", "the product is fine"))

    def test_not_found_in_a_review_body_is_not_an_error_page(self) -> None:
        # Titles only: reviews legitimately mention "not found".
        self.assertEqual("content", cdp_strategy.classify_page(
            "Great camera", "the app said firmware not found, but it works"))

    def test_challenge_markers_in_a_normal_page_stay_content(self) -> None:
        # A review can say "just a moment later" without the page being an
        # interstitial; Cloudflare titles are matched, body prose is not.
        self.assertEqual("content", cdp_strategy.classify_page(
            "Falcon camera review", "just a moment later the app reconnected"))

    def test_blank_render_is_not_a_challenge(self) -> None:
        self.assertTrue(cdp_strategy.is_blank_render("", "  \n "))
        self.assertFalse(cdp_strategy.is_blank_render("GolfWRX", ""))

    def test_membership_gate_detection_is_narrow(self) -> None:
        self.assertTrue(cdp_strategy.detect_membership_gate(
            "You must be a member of this server to view this channel"))
        self.assertTrue(cdp_strategy.detect_membership_gate("仅会员可查看该频道"))
        self.assertFalse(cdp_strategy.detect_membership_gate(
            "membership has grown steadily this year"))
        self.assertFalse(cdp_strategy.detect_membership_gate("the review body is visible"))

    def test_login_page_detection_is_narrow(self) -> None:
        self.assertTrue(cdp_strategy.looks_logged_out("https://discord.com/login"))
        self.assertTrue(cdp_strategy.looks_logged_out("https://discord.com/channels/1/2", "You need to log in"))
        self.assertFalse(cdp_strategy.looks_logged_out("https://discord.com/channels/1/2", "Log in to join the fun"))
        self.assertFalse(cdp_strategy.looks_logged_out("https://kickstarter.com/projects/x"))


class SessionGuardTests(unittest.TestCase):
    def make(self, now=None):
        now = now if now is not None else [1000.0]
        guard = cdp_strategy.SessionGuard(
            "discord", clock=lambda: now[0], wall_clock=lambda: now[0])
        return guard, now

    def test_one_goto_per_cell(self) -> None:
        guard, _ = self.make()
        cell = guard.begin_cell("messages")
        self.assertEqual(0, cell["gotos"])
        guard.navigate()
        with self.assertRaises(cdp_strategy.CellViolation):
            guard.navigate()
        with self.assertRaises(cdp_strategy.CellViolation):
            guard.begin_cell("messages")  # a second cell at once
        guard.end_cell()

    def test_reload_is_forbidden_by_default(self) -> None:
        guard, _ = self.make()
        with self.assertRaises(cdp_strategy.CellViolation):
            guard.reload()

    def test_modes_are_exclusive_within_a_session_stretch(self) -> None:
        guard, _ = self.make()
        guard.begin_cell("messages")
        guard.end_cell()
        with self.assertRaises(cdp_strategy.CellViolation):
            guard.begin_cell("forum")

    def test_timeout_opens_the_circuit_for_the_policy_cooldown(self) -> None:
        guard, now = self.make()
        guard.begin_cell("messages")
        guard.record_timeout("cuaScroll timeout")
        guard.end_cell("timeout")
        with self.assertRaises(cdp_strategy.CircuitOpen) as caught:
            guard.check()
        self.assertGreaterEqual(caught.exception.retry_after_seconds, 899)
        self.assertEqual("timeout_abort", guard.journal()["circuit"]["reason"])
        now[0] += 14 * 60
        with self.assertRaises(cdp_strategy.CircuitOpen):
            guard.check()
        now[0] += 2 * 60  # 16 minutes: the cooldown elapsed
        guard.check()

    def test_session_time_box_stops_the_stretch(self) -> None:
        guard, now = self.make()
        self.assertEqual(40 * 60, int(guard.remaining_session_seconds()))
        now[0] += 41 * 60
        self.assertTrue(guard.session_expired())
        with self.assertRaises(cdp_strategy.SessionExpired):
            guard.check_session()
        with self.assertRaises(cdp_strategy.SessionExpired):
            guard.begin_cell("messages")

    def test_cell_budget_applies_headroom(self) -> None:
        guard, _ = self.make()
        self.assertEqual(36.0, guard.cell_budget(60.0))
        self.assertEqual(18.0, guard.cell_budget(30.0))

    def test_journal_is_persisted_next_to_the_snapshot(self) -> None:
        guard, _ = self.make()
        guard.begin_cell("messages")
        guard.navigate()
        guard.end_cell("ok")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "discord.session.json"
            guard.save(path)
            payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual("askovo.cdp-session/1", payload["schema"])
        self.assertEqual("discord", payload["platform"])
        self.assertEqual(1, len(payload["cells"]))
        self.assertEqual(40.0, payload["policy"]["session_minutes"])
        self.assertFalse(payload["circuit"]["open"])

    def test_selftest_exits_clean(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(CONNECTORS / "cdp_strategy.py"), "--selftest"],
            check=False, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("[ok]", completed.stdout)

    def test_failure_classification_maps_to_actions(self) -> None:
        timeout = cdp_strategy.classify_failure(TimeoutError("torn"), platform="discord")
        self.assertEqual("circuit_break", timeout["action"])
        self.assertEqual(900.0, timeout["cooldown_seconds"])
        # Python 3.9 keeps socket.timeout outside TimeoutError; it is the same stop.
        socket_timeout = cdp_strategy.classify_failure(socket.timeout("timed out"), platform="discord")
        self.assertEqual("circuit_break", socket_timeout["action"])

        class ChallengeStopped(RuntimeError):
            pass

        self.assertEqual("human_required",
                         cdp_strategy.classify_failure(ChallengeStopped(), platform="kickstarter")["action"])
        expired = cdp_strategy.SessionExpired("box")
        self.assertEqual("stop", cdp_strategy.classify_failure(expired)["action"])
        self.assertEqual("cooldown",
                         cdp_strategy.classify_failure(cdp_strategy.CircuitOpen("x", 5.0))["action"])


class RegistryArtifactTests(unittest.TestCase):
    def test_repo_relative_artifact_maps_to_the_installed_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "runtime"
            (runtime / "references").mkdir(parents=True)
            (runtime / "references" / "doc.md").write_text("x", encoding="utf-8")
            saved = (engine.REPO_ROOT, engine.SKILL_ROOT)
            engine.REPO_ROOT = root / "site-packages"
            engine.SKILL_ROOT = runtime
            try:
                resolved = engine._registry_artifact_path("skills/askovo/references/doc.md")
            finally:
                engine.REPO_ROOT, engine.SKILL_ROOT = saved
            self.assertEqual(runtime / "references" / "doc.md", resolved)


class EngineWiringTests(unittest.TestCase):
    def test_engine_loads_the_same_policy(self) -> None:
        policy = engine._cdp_strategy().policy_for("discord")
        self.assertEqual(40.0, policy.session_minutes)
        self.assertEqual(36.0, policy.effective_budget(60.0))

    def test_doctor_gates_the_runtime_policy_layer(self) -> None:
        completed = run_cli("doctor")
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertRegex(completed.stdout, r"\[ok\] cdp-runtime-policies \d+ CDP platforms")

    def test_platforms_policies_view_and_json(self) -> None:
        text = run_cli("platforms", "Discord 社区抱怨", "--platform", "discord", "--policies")
        self.assertEqual(0, text.returncode, text.stderr)
        self.assertIn("CDP 运行时策略", text.stdout)
        self.assertIn("discord", text.stdout)
        self.assertIn("40 min", text.stdout)
        self.assertIn("60%", text.stdout)
        payload = json.loads(run_cli(
            "platforms", "Discord 社区抱怨", "--platform", "discord", "--json").stdout)
        entry = payload["recommended"][0]
        self.assertEqual("discord", entry["id"])
        self.assertEqual(1, entry["runtime_policy"]["max_gotos_per_cell"])
        self.assertEqual(40.0, entry["runtime_policy"]["session_minutes"])
        self.assertEqual(["discord"], list(payload["runtime_policies"]))

    def test_only_cdp_platforms_carry_a_runtime_policy(self) -> None:
        plan = engine.platform_fit("Discord 社区和 Kickstarter 众筹评论", domain="hardware")
        self.assertTrue(plan["runtime_policies"])
        catalog = engine.platform_index()
        for platform in plan["runtime_policies"]:
            self.assertTrue(catalog[platform].get("cdp"), platform)
        for item in plan["recommended"]:
            if not item.get("cdp"):
                self.assertNotIn("runtime_policy", item)

    def test_mcp_platforms_accepts_policies(self) -> None:
        sys.path.insert(0, str(SCRIPTS))
        try:
            import askovo_mcp  # noqa: WPS433 - local import keeps the sys.path fixture
        finally:
            sys.path.pop(0)
        namespace = askovo_mcp._build_platforms({"need": "Discord 采集", "policies": True})
        self.assertTrue(namespace.policies)


class _BlankClient:
    def __init__(self, ws): self.ws = ws
    def call(self, method, params=None, **kwargs): return {}
    def evaluate(self, expression, **kwargs):
        return {"title": "", "url": "https://www.amazon.com/product-reviews/B0", "text": ""}
    def close(self): pass


class _ChallengeTitleClient:
    def __init__(self, ws): self.ws = ws
    def call(self, method, params=None, **kwargs): return {}
    def evaluate(self, expression, **kwargs):
        return {"title": "Just a moment...", "url": "https://www.amazon.com/product-reviews/B0",
                "text": "the review body is already visible but the title is still the interstitial"}
    def close(self): pass


class _MembershipGateClient:
    def __init__(self, ws): self.ws = ws
    def call(self, method, params=None, **kwargs): return {}
    def evaluate(self, expression, **kwargs):
        return {"title": "Discord", "url": "https://discord.com/channels/1/2",
                "text": "You must be a member of this server to view this channel."}
    def close(self): pass


class _TimeoutClient:
    def __init__(self, ws): self.ws = ws
    def call(self, method, params=None, **kwargs):
        if method == "Runtime.enable":
            return {}
        raise engine.CDPTimeout(method, 30.0)
    def evaluate(self, expression, **kwargs):
        raise engine.CDPTimeout("Runtime.evaluate", 30.0)
    def close(self): pass


class CaptureAndCollectTriageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.study = Path(self.tmp.name) / "study"
        self.study.mkdir()
        (self.study / "study.json").write_text(json.dumps({
            "study_id": "s1", "title": "t",
            "scope": {"allowed_sources": ["amazon"]},
            "source_adapters": {"amazon": {"enabled": True}},
        }), encoding="utf-8")

    def _patch(self, client):
        saved = (engine.cdp_new_page, engine._WebSocket, engine.CDPClient)
        engine.cdp_new_page = lambda base, url: "ws://127.0.0.1:9222/devtools/page/1"
        engine._WebSocket = lambda url: object()
        engine.CDPClient = client
        self.addCleanup(lambda: setattr(engine, "cdp_new_page", saved[0]))
        self.addCleanup(lambda: setattr(engine, "_WebSocket", saved[1]))
        self.addCleanup(lambda: setattr(engine, "CDPClient", saved[2]))

    def test_capture_refuses_a_blank_render(self) -> None:
        self._patch(_BlankClient)
        result = engine.capture_page(
            self.study, "https://www.amazon.com/product-reviews/B0",
            "http://127.0.0.1:9222", True)
        self.assertEqual("blank_render", result["status"])
        self.assertFalse((self.study / "01-sources/captures/index.jsonl").exists())

    def test_capture_refuses_a_residual_challenge_title(self) -> None:
        self._patch(_ChallengeTitleClient)
        result = engine.capture_page(
            self.study, "https://www.amazon.com/product-reviews/B0",
            "http://127.0.0.1:9222", True)
        self.assertEqual("challenge", result["status"])
        self.assertFalse((self.study / "01-sources/captures/index.jsonl").exists())

    def test_capture_refuses_a_membership_gate(self) -> None:
        document = json.loads((self.study / "study.json").read_text(encoding="utf-8"))
        document["scope"]["allowed_sources"] = ["discord"]
        document["source_adapters"] = {"discord": {"enabled": True}}
        (self.study / "study.json").write_text(json.dumps(document), encoding="utf-8")
        self._patch(_MembershipGateClient)
        result = engine.capture_page(
            self.study, "https://discord.com/channels/1/2",
            "http://127.0.0.1:9222", True)
        self.assertEqual("membership_gated", result["status"])
        self.assertFalse((self.study / "01-sources/captures/index.jsonl").exists())

    def test_capture_timeout_is_a_circuit_breaker(self) -> None:
        self._patch(_TimeoutClient)
        result = engine.capture_page(
            self.study, "https://www.amazon.com/product-reviews/B0",
            "http://127.0.0.1:9222", True)
        self.assertEqual("cdp_timeout", result["status"])
        self.assertEqual(900, result["retry_after_seconds"])
        self.assertFalse((self.study / "01-sources/captures/index.jsonl").exists())

    def test_collect_timeout_and_blank_render_do_not_write_a_run(self) -> None:
        for client, expected in ((_TimeoutClient, "cdp_timeout"), (_BlankClient, "blank_render")):
            with self.subTest(expected=expected):
                self._patch(client)
                result = engine.collect_cdp(
                    self.study, "amazon", "q", "https://www.amazon.com/product-reviews/B0",
                    "http://127.0.0.1:9222", True, wait_seconds=0.0)
                self.assertEqual(expected, result["status"])
        self.assertFalse((self.study / "02-data" / "raw").exists())

    def test_cdp_client_never_reads_on_after_a_timeout(self) -> None:
        class _TornWebSocket:
            sock = None
            def send_text(self, text): pass
            def recv_text(self): raise socket.timeout("timed out")
            def close(self): pass

        client = engine.CDPClient(_TornWebSocket())
        with self.assertRaises(engine.CDPTimeout):
            client.call("Runtime.enable")
        self.assertTrue(client.broken)
        with self.assertRaises(engine.CDPTransportError):
            client.call("Runtime.enable")


class CollectorWiringTests(unittest.TestCase):
    def test_discord_scroll_stops_and_reports_a_timeout(self) -> None:
        discord = _load("collect_cdp_discord_test", CONNECTORS / "collect_cdp_discord.py")

        class _Client:
            def call(self, method, params=None, **kwargs): return {}
            def evaluate(self, expression, **kwargs): raise TimeoutError("torn")

        now = [1000.0]
        guard = cdp_strategy.SessionGuard("discord", clock=lambda: now[0], wall_clock=lambda: now[0])
        guard.begin_cell("messages")
        messages, stopped = discord.scroll_collect(_Client(), "() => 1", guard, max_rounds=3, scroll_sleep=0.5)
        self.assertEqual([], messages)
        self.assertEqual("timeout", stopped)
        self.assertTrue(guard.circuit()["open"])
        self.assertEqual("timeout_abort", guard.journal()["circuit"]["reason"])

    def test_discord_lists_channel_names_before_collection(self) -> None:
        discord = _load("collect_cdp_discord_list_test", CONNECTORS / "collect_cdp_discord.py")

        class _Client:
            def evaluate(self, expression, **kwargs):
                return {"url": "https://discord.com/channels/1/2",
                        "channels": [
                            {"channel_id": "2", "name": "help-channel", "url": "u2"},
                            {"channel_id": "3", "name": "gspro-tips", "url": "u3"},
                            {"channel_id": "", "name": "broken", "url": "u4"},
                        ]}

        guard = cdp_strategy.SessionGuard(
            "discord", clock=lambda: 1000.0, wall_clock=lambda: 1000.0)
        guard.begin_cell("channels")
        channels = discord.list_channels(_Client(), guard)
        self.assertEqual(["help-channel", "gspro-tips"], [item["name"] for item in channels])

    def test_channel_listing_writes_no_snapshot_and_needs_no_out(self) -> None:
        discord = _load("collect_cdp_discord_list_main_test", CONNECTORS / "collect_cdp_discord.py")

        class _Client:
            def __init__(self, ws): pass
            def call(self, method, params=None, **kwargs): return {}
            def evaluate(self, expression, **kwargs):
                return {"channels": [{"channel_id": "2", "name": "help-channel"}]}
            def close(self): pass

        saved = (discord.sure_engine.cdp_new_page, discord.sure_engine._WebSocket,
                 discord.sure_engine.CDPClient, discord.time.sleep)
        discord.sure_engine.cdp_new_page = lambda base, url: "ws://127.0.0.1:9222/devtools/page/1"
        discord.sure_engine._WebSocket = lambda url: object()
        discord.sure_engine.CDPClient = _Client
        discord.time.sleep = lambda seconds: None
        try:
            args = types.SimpleNamespace(cdp_url="http://127.0.0.1:9222",
                                         url="https://discord.com/channels/1/2")
            guard = cdp_strategy.SessionGuard(
                "discord", clock=lambda: 1000.0, wall_clock=lambda: 1000.0)
            self.assertEqual(0, discord._list_channels_main(args, guard))
        finally:
            (discord.sure_engine.cdp_new_page, discord.sure_engine._WebSocket,
             discord.sure_engine.CDPClient, discord.time.sleep) = saved

    def test_kickstarter_expansion_persists_best_before_stopping(self) -> None:
        kickstarter = _load("collect_cdp_kickstarter_test", CONNECTORS / "collect_cdp_kickstarter.py")

        class _Client:
            def call(self, method, params=None, **kwargs): return {}
            def evaluate(self, expression, **kwargs):
                raise TimeoutError("torn")

        now = [1000.0]
        guard = cdp_strategy.SessionGuard("kickstarter", clock=lambda: now[0], wall_clock=lambda: now[0])
        guard.begin_cell("comments")
        comments, stopped = kickstarter.expand_and_extract(
            _Client(), max_clicks=10, click_burst=3, burst_pause=1.0, guard=guard)
        self.assertEqual([], comments)
        self.assertEqual("timeout", stopped)
        self.assertTrue(guard.circuit()["open"])


if __name__ == "__main__":
    unittest.main()
