#!/usr/bin/env python3
"""CDP page capture: terms/URL gates and a mocked text+screenshot+OCR capture."""
import base64
import importlib.util
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
spec = importlib.util.spec_from_file_location("sure_engine_capture_test", CLI.parent / "sure_engine.py")
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)


def run_cli(*args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run([sys.executable, str(CLI), *args],
                          check=False, capture_output=True, text=True, timeout=120, env=env)

_PNG = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()


class _FakeClient:
    def __init__(self, ws):
        self.ws = ws

    def call(self, method, params=None):
        if method == "Page.captureScreenshot":
            return {"data": _PNG}
        return {}

    def evaluate(self, expression):
        return {"title": "示例页面", "url": "https://www.amazon.com/product-reviews/B0",
                "text": "用户说夜间误报很烦。\n她希望先判断再起床。"}

    def close(self):
        pass


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.study = Path(self.tmp.name) / "study"
        self.study.mkdir()
        (self.study / "study.json").write_text(json.dumps({
            "study_id": "s1", "title": "t",
            "scope": {"allowed_sources": ["amazon"]},
            "source_adapters": {"amazon": {"enabled": True}},
        }), encoding="utf-8")

    def test_terms_are_required(self):
        result = engine.capture_page(
            self.study, "https://www.amazon.com/product-reviews/B0",
            "http://127.0.0.1:9222", False)
        self.assertEqual("terms_required", result["status"])

    def test_url_must_be_http_credential_free_and_default_port(self):
        for url in ("file:///etc/passwd", "https://u:p@example.com",
                    "https://www.amazon.com:8443/product-reviews/B0"):
            with self.assertRaises(ValueError):
                engine._validate_capture_url(url)

    def test_capture_writes_text_screenshot_and_ocr(self):
        old_new, old_ws, old_client, old_ocr = (
            engine.cdp_new_page, engine._WebSocket, engine.CDPClient, engine._ocr_with_vision)
        engine.cdp_new_page = lambda base, url: "ws://127.0.0.1:9222/devtools/page/1"
        engine._WebSocket = lambda url: object()
        engine.CDPClient = _FakeClient
        engine._ocr_with_vision = lambda path: {"engine": "fake", "text": "OCR 文本", "error": ""}
        try:
            result = engine.capture_page(
                self.study, "https://www.amazon.com/product-reviews/B0",
                "http://127.0.0.1:9222", True, ocr=True)
        finally:
            engine.cdp_new_page, engine._WebSocket, engine.CDPClient, engine._ocr_with_vision = (
                old_new, old_ws, old_client, old_ocr)
        self.assertEqual("captured", result["status"])
        payload = json.loads(Path(result["capture"]).read_text(encoding="utf-8"))
        self.assertEqual("candidate", payload["evidence_status"])
        self.assertEqual("candidate", result["evidence_status"])
        self.assertEqual(payload["capture_id"], result["capture_id"])
        self.assertEqual("passed", payload["governance"]["challenge_check"])
        self.assertIn("夜间误报", payload["text"])
        self.assertEqual("OCR 文本", payload["ocr"]["text"])
        self.assertTrue(Path(payload["screenshot"]).is_file())
        self.assertTrue((self.study / "01-sources/captures/index.jsonl").is_file())

    # ------------------------------------------------------------------ #
    # P0.4 unified governance: one entry, one rule set. `capture` must not
    # become a second, laxer collection entrance than `collect`.
    # ------------------------------------------------------------------ #

    def test_capture_writes_no_candidate_for_not_found_page(self):
        document = json.loads((self.study / "study.json").read_text(encoding="utf-8"))
        document["scope"]["allowed_sources"] = ["kickstarter"]
        document["source_adapters"] = {"kickstarter": {"enabled": True}}
        (self.study / "study.json").write_text(
            json.dumps(document, ensure_ascii=False), encoding="utf-8")

        class _NotFoundClient(_FakeClient):
            def evaluate(self, expression):
                return {"title": "The page you were looking for doesn't exist (404)",
                        "url": "https://www.kickstarter.com/projects/gone/missing",
                        "text": "We can't find this page, but we can show you a new project."}

        old_new, old_ws, old_client = (
            engine.cdp_new_page, engine._WebSocket, engine.CDPClient)
        engine.cdp_new_page = lambda base, url: "ws://127.0.0.1:9222/devtools/page/1"
        engine._WebSocket = lambda url: object()
        engine.CDPClient = _NotFoundClient
        try:
            result = engine.capture_page(
                self.study, "https://www.kickstarter.com/projects/gone/missing",
                "http://127.0.0.1:9222", True)
        finally:
            engine.cdp_new_page, engine._WebSocket, engine.CDPClient = (
                old_new, old_ws, old_client)
        self.assertEqual("page_not_found", result["status"])
        self.assertIn("no candidate was written", result["reason"])
        self.assertEqual([], list((self.study / "01-sources/captures").glob("*.json")))
        # 404 detection must not fire on ordinary titles that merely contain digits.
        self.assertFalse(engine._capture_title_reports_not_found("B014045 车充 2 合 1"))
        self.assertTrue(engine._capture_title_reports_not_found("Page not found"))
        self.assertTrue(engine._capture_title_reports_not_found("页面不存在"))


    def _sample_study(self, target: Path) -> Path:
        shutil.copytree(SAMPLE, target)
        return target

    def test_capture_refuses_when_design_gate_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            study = self._sample_study(Path(directory) / "study")
            document = json.loads((study / "study.json").read_text(encoding="utf-8"))
            document["decision"]["question"] = ""  # break the design contract
            (study / "study.json").write_text(
                json.dumps(document, ensure_ascii=False), encoding="utf-8")
            completed = run_cli("capture", "page", str(study), "--url",
                                "https://www.amazon.com/product-reviews/B0", "--ack-terms")
            self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual("design_gate_failed", payload["status"])
            self.assertIn("design", json.dumps(payload.get("next_step", "")))

    def test_capture_scope_blocks_approved_host_the_study_never_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            study = self._sample_study(Path(directory) / "study")
            document = json.loads((study / "study.json").read_text(encoding="utf-8"))
            document["scope"]["allowed_sources"] = ["amazon"]
            (study / "study.json").write_text(
                json.dumps(document, ensure_ascii=False), encoding="utf-8")
            result = engine.capture_page(study, "https://www.instagram.com/p/visible",
                                         "http://127.0.0.1:9222", True)
            self.assertEqual("scope_blocked", result["status"])
            self.assertIn("allowed_sources", result["reason"])

    def test_cdp_host_allowlist_matches_catalog_cdp_true(self):
        expected = {platform for platform, entry in engine.platform_index().items()
                    if entry.get("cdp")}
        self.assertEqual(expected, set(engine.CDP_TARGET_HOSTS))
        self.assertEqual(
            expected,
            set(json.loads((ROOT / "docs/delivery-contract.json").read_text(
                encoding="utf-8"))["candidate_inputs"]["cdp_page"]["approved_platforms"]))

    def test_capture_never_opens_generic_web_reddit_or_youtube(self):
        with tempfile.TemporaryDirectory() as directory:
            study = self._sample_study(Path(directory) / "study")
            document = json.loads((study / "study.json").read_text(encoding="utf-8"))
            document["scope"]["allowed_sources"] = ["web", "reddit", "x", "youtube"]
            (study / "study.json").write_text(
                json.dumps(document, ensure_ascii=False), encoding="utf-8")
            for url in ("https://internal-intranet.example.org/wiki/page",
                        "https://www.reddit.com/r/somebody/thread",
                        "https://www.youtube.com/watch?v=1"):
                with self.subTest(url=url):
                    result = engine.capture_page(study, url, "http://127.0.0.1:9222", True)
                    self.assertEqual("cdp_not_allowed", result["status"])
            # x is now a CDP-enabled user-session platform: the scope gate passes
            # and the next check is the enabled-adapter requirement.
            x_result = engine.capture_page(study, "https://x.com/user/status/1",
                                           "http://127.0.0.1:9222", True)
            self.assertEqual("adapter_disabled", x_result["status"])
            document["scope"]["allowed_sources"] = ["amazon"]
            document["source_adapters"] = {"amazon": {"enabled": True}}
            (study / "study.json").write_text(
                json.dumps(document, ensure_ascii=False), encoding="utf-8")
            self.assertIsNone(engine._capture_scope_failure(
                document, "https://www.amazon.com/product-reviews/B0"))

    def test_capture_requires_enabled_adapter_before_any_cdp_call(self):
        document = json.loads((self.study / "study.json").read_text(encoding="utf-8"))
        document["source_adapters"]["amazon"]["enabled"] = False
        (self.study / "study.json").write_text(json.dumps(document), encoding="utf-8")
        old_new = engine.cdp_new_page
        engine.cdp_new_page = lambda *args: self.fail("CDP must not be called")
        try:
            result = engine.capture_page(
                self.study, "https://www.amazon.com/product-reviews/B0",
                "http://127.0.0.1:9222", True)
        finally:
            engine.cdp_new_page = old_new
        self.assertEqual("adapter_disabled", result["status"])

    def test_challenge_page_stops_before_screenshot_or_candidate(self):
        class ChallengeClient(_FakeClient):
            def evaluate(self, expression):
                return {"title": "Robot Check", "url": "https://www.amazon.com/product-reviews/B0",
                        "text": "Enter the characters shown below"}

            def call(self, method, params=None):
                assert method != "Page.captureScreenshot", "challenge must stop before screenshots"
                return {}

        saved = (engine.cdp_new_page, engine._WebSocket, engine.CDPClient)
        engine.cdp_new_page = lambda base, url: "ws://127.0.0.1:9222/devtools/page/1"
        engine._WebSocket = lambda url: object()
        engine.CDPClient = ChallengeClient
        old_wait = engine.CAPTURE_CHALLENGE_WAIT_SECONDS
        engine.CAPTURE_CHALLENGE_WAIT_SECONDS = 0.0
        try:
            result = engine.capture_page(
                self.study, "https://www.amazon.com/product-reviews/B0",
                "http://127.0.0.1:9222", True)
        finally:
            engine.cdp_new_page, engine._WebSocket, engine.CDPClient = saved
            engine.CAPTURE_CHALLENGE_WAIT_SECONDS = old_wait
        self.assertEqual("challenge", result["status"])
        self.assertFalse((self.study / "01-sources/captures/index.jsonl").exists())


    def test_challenge_passively_cleared_within_wait_is_captured(self):
        class EvolvingClient(_FakeClient):
            calls = 0

            def evaluate(self, expression):
                EvolvingClient.calls += 1
                if EvolvingClient.calls == 1:
                    return {"title": "Robot Check",
                            "url": "https://www.amazon.com/product-reviews/B0",
                            "text": "Enter the characters shown below"}
                return super().evaluate(expression)

        saved = (engine.cdp_new_page, engine._WebSocket, engine.CDPClient)
        old_wait = engine.CAPTURE_CHALLENGE_WAIT_SECONDS
        engine.cdp_new_page = lambda base, url: "ws://127.0.0.1:9222/devtools/page/1"
        engine._WebSocket = lambda url: object()
        engine.CDPClient = EvolvingClient
        engine.CAPTURE_CHALLENGE_WAIT_SECONDS = 2.0
        try:
            result = engine.capture_page(
                self.study, "https://www.amazon.com/product-reviews/B0",
                "http://127.0.0.1:9222", True)
        finally:
            engine.cdp_new_page, engine._WebSocket, engine.CDPClient = saved
            engine.CAPTURE_CHALLENGE_WAIT_SECONDS = old_wait
        self.assertEqual("captured", result["status"])
        payload = json.loads(Path(result["capture"]).read_text(encoding="utf-8"))
        self.assertEqual("waited_then_passed", payload["governance"]["challenge_check"])


if __name__ == "__main__":
    unittest.main()
