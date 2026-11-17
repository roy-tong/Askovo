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
        return {"title": "示例页面", "url": "https://example.com/page",
                "text": "用户说夜间误报很烦。\n她希望先判断再起床。"}

    def close(self):
        pass


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.study = Path(self.tmp.name) / "study"
        self.study.mkdir()
        (self.study / "study.json").write_text('{"study_id":"s1","title":"t"}', encoding="utf-8")

    def test_terms_are_required(self):
        result = engine.capture_page(self.study, "https://example.com", "http://127.0.0.1:9222", False)
        self.assertEqual("terms_required", result["status"])

    def test_url_must_be_http_and_credential_free(self):
        for url in ("file:///etc/passwd", "https://u:p@example.com"):
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
            result = engine.capture_page(self.study, "https://example.com/page",
                                         "http://127.0.0.1:9222", True, ocr=True)
        finally:
            engine.cdp_new_page, engine._WebSocket, engine.CDPClient, engine._ocr_with_vision = (
                old_new, old_ws, old_client, old_ocr)
        self.assertEqual("captured", result["status"])
        payload = json.loads(Path(result["capture"]).read_text(encoding="utf-8"))
        self.assertEqual("candidate", payload["evidence_status"])
        self.assertIn("夜间误报", payload["text"])
        self.assertEqual("OCR 文本", payload["ocr"]["text"])
        self.assertTrue(Path(payload["screenshot"]).is_file())
        self.assertTrue((self.study / "01-sources/captures/index.jsonl").is_file())

    # ------------------------------------------------------------------ #
    # P0.4 unified governance: one entry, one rule set. `capture` must not
    # become a second, laxer collection entrance than `collect`.
    # ------------------------------------------------------------------ #

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
            completed = run_cli("capture", str(study), "--url", "https://example.com/page",
                                "--ack-terms")
            self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual("design_gate_failed", payload["status"])
            self.assertIn("design", json.dumps(payload.get("next_step", "")))

    def test_capture_scope_blocks_hosts_the_study_never_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            study = self._sample_study(Path(directory) / "study")
            document = json.loads((study / "study.json").read_text(encoding="utf-8"))
            document["scope"]["allowed_sources"] = ["amazon"]
            (study / "study.json").write_text(
                json.dumps(document, ensure_ascii=False), encoding="utf-8")
            result = engine.capture_page(study, "https://www.reddit.com/r/somebody/thread",
                                         "http://127.0.0.1:9222", True)
            self.assertEqual("scope_blocked", result["status"])
            self.assertIn("allowed_sources", result["reason"])

    def test_capture_scope_allows_declared_platform_and_generic_web(self):
        with tempfile.TemporaryDirectory() as directory:
            study = self._sample_study(Path(directory) / "study")
            document = json.loads((study / "study.json").read_text(encoding="utf-8"))
            document["scope"]["allowed_sources"] = ["reddit"]
            (study / "study.json").write_text(
                json.dumps(document, ensure_ascii=False), encoding="utf-8")
            self.assertIsNone(engine._capture_scope_failure(
                json.loads((study / "study.json").read_text(encoding="utf-8")),
                "https://www.reddit.com/r/somebody/thread"))
            document["scope"]["allowed_sources"] = ["web"]
            (study / "study.json").write_text(
                json.dumps(document, ensure_ascii=False), encoding="utf-8")
            self.assertIsNone(engine._capture_scope_failure(
                json.loads((study / "study.json").read_text(encoding="utf-8")),
                "https://internal-intranet.example.org/wiki/page"))


if __name__ == "__main__":
    unittest.main()
