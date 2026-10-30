from __future__ import annotations

import importlib.util
import json
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/askovo/scripts/askovo.py"
KIT_PATH = ROOT / "skills/askovo/scripts/sure_engine.py"

spec = importlib.util.spec_from_file_location("sure_engine_cdp_test", KIT_PATH)
sure_engine = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(sure_engine)


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(CLI), *args], check=False, capture_output=True, text=True)


def complete_design(target: Path) -> None:
    path = target / "study.json"
    study = json.loads(path.read_text(encoding="utf-8"))
    study["decision"].update({
        "owner": "Synthetic owner", "deadline": "2027-12-31",
        "options": ["Pilot", "Stop"], "minimum_evidence": ["Synthetic evidence"],
    })
    study["scope"].update({
        "target_users": ["Synthetic users"], "markets": ["synthetic"], "languages": ["en"],
        "source_time_window": {"start": "2026-01-01", "end": "2026-12-31"},
        "allowed_sources": ["amazon", "github"],
    })
    study["hypotheses"] = [{"id": "H1", "statement": "Synthetic hypothesis", "falsified_if": "Synthetic falsifier"}]
    study["stopping_rules"] = ["Stop after fixture"]
    study["restart_rules"] = ["Restart after redesign"]
    study["source_adapters"] = {"amazon": {"enabled": True}, "github": {"enabled": True}}
    path.write_text(json.dumps(study), encoding="utf-8")
    reasoning_path = target / "04-findings" / "product-reasoning.json"
    if reasoning_path.is_file():
        reasoning = json.loads(reasoning_path.read_text(encoding="utf-8"))
        for chain in reasoning.get("chains", []):
            chain["title"] = "Synthetic product reasoning"
            chain["next_test"] = "Run a synthetic validation"
            for node_name, node in chain.get("nodes", {}).items():
                node["statement"] = f"Synthetic {node_name} statement"
                node["rationale"] = f"Synthetic rationale for {node_name}"
        reasoning_path.write_text(json.dumps(reasoning), encoding="utf-8")


class CDPTermsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.study = Path(self._tmp.name) / "study"
        completed = run_cli("do", "家用摄像头评论", "--study", str(self.study), "--json")
        self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)
        complete_design(self.study)

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

    def test_collect_platform_forwards_run_id_to_cdp(self) -> None:
        with mock.patch.object(sure_engine, "collect_cdp", return_value={"status": "planned"}) as collector:
            result = sure_engine.collect_platform(
                self.study,
                "amazon",
                "camera",
                run_id="custom-cdp-run",
                cdp_url="http://127.0.0.1:9222",
                url="https://www.amazon.com/product-reviews/B0",
                ack_terms=True,
            )
        self.assertEqual("planned", result["status"])
        self.assertEqual("custom-cdp-run", collector.call_args.kwargs["run_id"])


class CDPBoundaryTests(unittest.TestCase):
    def test_target_url_matrix(self) -> None:
        sure_engine._validate_cdp_target("amazon", "https://www.amazon.com/product-reviews/B0")
        for url in (
            "file:///etc/passwd",
            "http://169.254.169.254/latest/meta-data",
            "https://amazon.com.evil.example/reviews",
            "https://www.amazon.com:8443/product-reviews/B0",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                sure_engine._validate_cdp_target("amazon", url)

    def test_debug_and_websocket_endpoints_stay_on_loopback(self) -> None:
        sure_engine._validate_cdp_base("http://127.0.0.1:9222")
        with self.assertRaises(ValueError):
            sure_engine._validate_cdp_base("http://192.168.1.2:9222")
        with self.assertRaises(ValueError):
            sure_engine._validate_cdp_ws_url("ws://127.0.0.1:9223/devtools/page/1", 9222)

    def test_redirected_page_creation_never_reaches_second_server(self) -> None:
        second_hits = []

        class Quiet(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:
                return

        class Metadata(Quiet):
            def do_GET(self) -> None:
                second_hits.append(self.path)
                payload = b"{}"
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        second = ThreadingHTTPServer(("127.0.0.1", 0), Metadata)

        class Redirect(Quiet):
            def do_PUT(self) -> None:
                self.send_response(405)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_GET(self) -> None:
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{second.server_port}/metadata")
                self.send_header("Content-Length", "0")
                self.end_headers()

        first = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
        threads = [
            threading.Thread(target=second.serve_forever, daemon=True),
            threading.Thread(target=first.serve_forever, daemon=True),
        ]
        for thread in threads:
            thread.start()
        try:
            with self.assertRaises(urllib.error.HTTPError) as caught:
                sure_engine.cdp_new_page(
                    f"http://127.0.0.1:{first.server_port}",
                    "https://www.amazon.com/product-reviews/B0",
                )
            self.assertEqual(302, caught.exception.code)
            self.assertEqual([], second_hits)
        finally:
            first.shutdown()
            second.shutdown()
            first.server_close()
            second.server_close()
            for thread in threads:
                thread.join(timeout=2)

    def test_x_and_youtube_do_not_enable_cdp(self) -> None:
        platforms = sure_engine.platform_index()
        self.assertFalse(platforms["x"].get("cdp", False))
        self.assertFalse(platforms["youtube"].get("cdp", False))


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
