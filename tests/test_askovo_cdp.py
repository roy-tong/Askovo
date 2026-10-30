from __future__ import annotations

import importlib.util
import json
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/askovo/scripts/askovo.py"
KIT_PATH = ROOT / "skills/askovo/scripts/sure_engine.py"

spec = importlib.util.spec_from_file_location("sure_engine_cdp_test", KIT_PATH)
sure_engine = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(sure_engine)


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(CLI), *args], check=False, capture_output=True, text=True)


class CDPTermsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.study = Path(self._tmp.name) / "study"
        completed = run_cli("do", "家用摄像头评论", "--study", str(self.study), "--json")
        self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)

    def test_cdp_requires_explicit_terms_ack(self) -> None:
        completed = run_cli(
            "collect", str(self.study), "--platform", "amazon", "--query", "camera",
            "--cdp-url", "http://127.0.0.1:9222", "--url", "https://www.amazon.com/product-reviews/B0",
        )
        self.assertEqual(4, completed.returncode)
        self.assertIn("terms_required", completed.stdout)

    def test_cdp_dry_run_plans_without_network(self) -> None:
        completed = run_cli(
            "collect", str(self.study), "--platform", "amazon", "--query", "camera",
            "--cdp-url", "http://127.0.0.1:9222", "--url", "https://www.amazon.com/product-reviews/B0",
            "--ack-terms", "--dry-run",
        )
        self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)
        payload = json.loads(completed.stdout)
        self.assertEqual("planned", payload["status"])
        self.assertEqual("cdp", payload["transport"])

    def test_cdp_is_not_allowed_for_api_platforms(self) -> None:
        completed = run_cli(
            "collect", str(self.study), "--platform", "github", "--query", "camera",
            "--cdp-url", "http://127.0.0.1:9222", "--url", "https://github.com",
            "--ack-terms",
        )
        self.assertEqual(4, completed.returncode)
        self.assertIn("cdp_not_allowed", completed.stdout)


class WebSocketFrameTests(unittest.TestCase):
    def test_client_masks_text_and_reads_server_frame(self) -> None:
        client_sock, server_sock = socket.socketpair()
        self.addCleanup(client_sock.close)
        self.addCleanup(server_sock.close)
        ws = object.__new__(sure_engine._WebSocket)
        ws.sock = client_sock
        captured = {}

        def server() -> None:
            first, second = server_sock.recv(2)
            length = second & 0x7F
            if length == 126:
                length = int.from_bytes(server_sock.recv(2), "big")
            mask = server_sock.recv(4)
            payload = server_sock.recv(length)
            captured["text"] = bytes(b ^ mask[i % 4] for i, b in enumerate(payload)).decode()
            message = b'{"id":1,"result":{}}'
            server_sock.sendall(bytes([0x81, len(message)]) + message)

        thread = threading.Thread(target=server)
        thread.start()
        ws.send_text('{"id":1,"method":"Runtime.enable"}')
        reply = ws.recv_text()
        thread.join(timeout=5)
        self.assertIn("Runtime.enable", captured["text"])
        self.assertEqual({"id": 1, "result": {}}, json.loads(reply))

    def test_extractor_has_challenge_and_review_selectors(self) -> None:
        self.assertIn("challenge_page", sure_engine.CDP_EXTRACTOR)
        self.assertIn("data-hook", sure_engine.CDP_EXTRACTOR)


if __name__ == "__main__":
    unittest.main()
