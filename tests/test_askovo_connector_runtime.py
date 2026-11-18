"""Runtime guards extracted from the campaign: backoff, single writer, relative time, CDP helpers.

These are the reusable parts of the field experience — a future collection should
import them instead of re-deriving 422/429 handling, stale-process state
corruption, relative timestamps and lazy-loading input events.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONNECTORS = ROOT / "skills/askovo/scripts/connectors"
if str(CONNECTORS) not in sys.path:
    sys.path.insert(0, str(CONNECTORS))

import cdp_runtime  # noqa: E402
import common  # noqa: E402


class ClassifiedBackoffTests(unittest.TestCase):
    def test_success_and_permanent_statuses(self) -> None:
        self.assertEqual("continue", common.classify_backoff(200)["action"])
        self.assertEqual("continue", common.classify_backoff(204)["action"])
        for status in (400, 401, 404, 410, 451):
            with self.subTest(status=status):
                decision = common.classify_backoff(status)
                self.assertEqual("stop", decision["action"])
                self.assertEqual("permanent", decision["reason"])

    def test_rate_limit_waits_for_epoch_reset_header(self) -> None:
        decision = common.classify_backoff(
            429, {"X-RateLimit-Reset": "1794892000"}, now=1794891900)
        self.assertEqual("wait", decision["action"])
        self.assertEqual(100.0, decision["wait_seconds"])
        self.assertEqual("rate_limit_reset", decision["reason"])

    def test_rate_limit_accepts_relative_reset_and_retry_after(self) -> None:
        self.assertEqual(30.0, common.classify_backoff(429, {"Retry-After": "30"})["wait_seconds"])
        self.assertEqual(15.0, common.classify_backoff(403, {"x-ratelimit-reset": "15"})["wait_seconds"])

    def test_slow_down_uses_exponential_retry(self) -> None:
        first = common.classify_backoff(422, attempt=0)
        second = common.classify_backoff(422, attempt=2)
        self.assertEqual("retry", first["action"])
        self.assertEqual("slow_down", first["reason"])
        self.assertGreater(second["wait_seconds"], first["wait_seconds"])

    def test_waits_are_capped(self) -> None:
        decision = common.classify_backoff(503, attempt=40, max_wait=120.0)
        self.assertEqual(120.0, decision["wait_seconds"])
        self.assertEqual("server_error", decision["reason"])


class SingleWriterStateTests(unittest.TestCase):
    def test_lock_is_exclusive_and_released(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "run.state.json"
            with common.single_writer_state(state):
                self.assertTrue((Path(directory) / "run.state.json.lock").exists())
            self.assertFalse((Path(directory) / "run.state.json.lock").exists())

    def test_live_owner_blocks_a_second_writer(self) -> None:
        import os

        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "run.state.json"
            with common.single_writer_state(state):
                with self.assertRaises(common.SingleWriterError) as caught:
                    with common.single_writer_state(state):
                        pass
            self.assertIn(str(os.getpid()), str(caught.exception))

    def test_stale_owner_is_reclaimed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "run.state.json"
            lock = Path(directory) / "run.state.json.lock"
            # PID 999999 is not live on any supported host.
            lock.write_text('{"pid": 999999, "started_at": "2026-11-17T00:00:00+00:00"}', encoding="utf-8")
            with common.single_writer_state(state):
                self.assertIn('"pid"', lock.read_text(encoding="utf-8"))

    def test_process_is_alive(self) -> None:
        import os

        self.assertTrue(common.process_is_alive(os.getpid()))
        self.assertFalse(common.process_is_alive(999999))
        self.assertFalse(common.process_is_alive(0))


class RelativeTimeTests(unittest.TestCase):
    NOW = datetime(2026, 11, 17, 5, 0, 0, tzinfo=timezone.utc)

    def parse(self, text: str) -> dict:
        result = common.parse_relative_time(text, now=self.NOW)
        self.assertIsNotNone(result, text)
        self.assertEqual("approximate", result["date_precision"])
        return result

    def test_english(self) -> None:
        self.assertEqual(10 * 2592000, self.parse("10 months ago")["seconds_ago"])

    def test_chinese(self) -> None:
        self.assertEqual(3 * 3600, self.parse("3小时前")["seconds_ago"])

    def test_korean(self) -> None:
        self.assertEqual(2 * 86400, self.parse("2일 전")["seconds_ago"])

    def test_japanese(self) -> None:
        self.assertEqual(5 * 60, self.parse("5 分前")["seconds_ago"])

    def test_just_now(self) -> None:
        self.assertEqual(0, self.parse("just now")["seconds_ago"])

    def test_absolute_and_garbage_dates_are_not_guessed(self) -> None:
        self.assertIsNone(common.parse_relative_time("2024年11月"))
        self.assertIsNone(common.parse_relative_time("2026-11-01"))
        self.assertIsNone(common.parse_relative_time(""))
        self.assertIsNone(common.parse_relative_time(None))


class CdpRuntimeTests(unittest.TestCase):
    def test_challenge_clears_passively(self) -> None:
        states = iter(["challenge", "challenge", "clear"])
        result = cdp_runtime.wait_for_challenge_clear(states.__next__, sleep=lambda _: None)
        self.assertEqual("cleared", result["status"])
        self.assertEqual(3, result["polls"])

    def test_interactive_challenge_stops_immediately(self) -> None:
        result = cdp_runtime.wait_for_challenge_clear(lambda: "interactive", sleep=lambda _: None)
        self.assertEqual("interactive", result["status"])
        self.assertEqual(1, result["polls"])

    def test_challenge_times_out(self) -> None:
        ticks = iter([0.0, 1.0, 1.0, 30.0, 30.0, 90.0, 90.0])
        result = cdp_runtime.wait_for_challenge_clear(
            lambda: "challenge", timeout_seconds=60.0, sleep=lambda _: None,
            clock=lambda: next(ticks))
        self.assertEqual("timeout", result["status"])

    def test_wheel_scroll_sends_move_then_wheel(self) -> None:
        sent = []

        def send(method, params):
            sent.append((method, dict(params)))

        events = cdp_runtime.wheel_scroll(send, delta_y=-500)
        self.assertEqual(["mouseMoved", "mouseWheel"], [event["type"] for event in events])
        self.assertEqual(-500, events[-1]["deltaY"])
        self.assertTrue(all(method == "Input.dispatchMouseEvent" for method, _ in sent))

    def test_rebind_tab_relists_after_a_miss(self) -> None:
        listings = iter([[], [{"id": "t1", "url": "https://discord.com/channels/1/2"}]])
        tab = cdp_runtime.rebind_tab(listings.__next__, r"discord\.com", sleep=lambda _: None)
        self.assertEqual("t1", tab["id"])

    def test_rebind_tab_raises_when_the_binding_rots(self) -> None:
        with self.assertRaises(cdp_runtime.TabNotFound):
            cdp_runtime.rebind_tab(lambda: [], r"nope", attempts=2, sleep=lambda _: None)

    def test_bounded_load_more_stops_on_no_more(self) -> None:
        summary = cdp_runtime.bounded_load_more(
            lambda: False, lambda: 25, sleep=lambda _: None)
        self.assertEqual("no_more", summary["stopped"])
        self.assertEqual(0, summary["clicks"])

    def test_bounded_load_more_stops_when_the_list_stalls(self) -> None:
        counts = iter([25, 25])
        summary = cdp_runtime.bounded_load_more(
            lambda: True, lambda: next(counts), max_clicks=10, burst=1, sleep=lambda _: None)
        self.assertEqual("stalled", summary["stopped"])
        self.assertEqual(25, summary["rows"])

    def test_bounded_load_more_caps_clicks(self) -> None:
        counter = {"rows": 0}

        def grow() -> int:
            counter["rows"] += 5
            return counter["rows"]

        summary = cdp_runtime.bounded_load_more(
            lambda: True, grow, max_clicks=4, burst=1, sleep=lambda _: None)
        self.assertEqual("cap", summary["stopped"])
        self.assertEqual(4, summary["clicks"])

    def test_run_lanes_isolates_failures(self) -> None:
        outcome = cdp_runtime.run_lanes({
            "archive": lambda: ["row"],
            "browser": lambda: (_ for _ in ()).throw(RuntimeError("cell timeout")),
        })
        self.assertEqual(["row"], outcome["results"]["archive"])
        self.assertIn("cell timeout", outcome["errors"]["browser"])
        self.assertEqual(["archive", "browser"], outcome["lanes"])

    def test_run_lanes_rejects_two_tabs_on_one_site(self) -> None:
        with self.assertRaises(ValueError):
            cdp_runtime.run_lanes(
                {"a": lambda: 1, "b": lambda: 2},
                site_of={"a": "discord.com", "b": "discord.com"},
            )

    def test_run_lanes_requires_a_lane(self) -> None:
        with self.assertRaises(ValueError):
            cdp_runtime.run_lanes({})

    def test_selftest_exits_clean(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(CONNECTORS / "cdp_runtime.py"), "--selftest"],
            check=False, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("[ok]", completed.stdout)


if __name__ == "__main__":
    unittest.main()
