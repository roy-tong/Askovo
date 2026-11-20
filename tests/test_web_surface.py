from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/askovo/scripts/askovo.py"
MCP = ROOT / "skills/askovo/scripts/askovo_mcp.py"
SAMPLE = ROOT / "examples/sample-study"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        check=False, capture_output=True, text=True, env=env,
    )


def run_mcp(*requests: dict) -> list[dict]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, str(MCP)],
        input="\n".join(json.dumps(request) for request in requests) + "\n",
        check=False, capture_output=True, text=True, timeout=120, env=env,
    )
    return [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]


class WebSurfaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="askovo-web-"))
        self.study = self.tmp / "study"
        shutil.copytree(SAMPLE, self.study)
        self.page = self.study / "06-report/web/index.html"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _deliver(self) -> dict:
        completed = run_cli("deliver", str(self.study), "--kind", "web")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def test_web_kind_writes_reading_surface(self) -> None:
        result = self._deliver()
        self.assertEqual(result["status"], "written")
        self.assertEqual(result["kind"], "web")
        self.assertTrue(self.page.is_file())
        html = self.page.read_text(encoding="utf-8")
        for token in ("事实", "自述", "推导", "我的判断", "数字比文字更新得快", "E5", "边界"):
            self.assertIn(token, html)

    def test_web_surface_is_self_contained(self) -> None:
        self._deliver()
        html = self.page.read_text(encoding="utf-8")
        self.assertNotIn("<script src", html)
        self.assertNotIn("<link ", html)
        self.assertNotIn('<img src="http', html)
        for url in re.findall(r'(?:src|href)="([^"]*)"', html):
            self.assertTrue(url.startswith("#"), url)

    def test_stale_numbers_are_flagged(self) -> None:
        evidence = self.study / "02-data/evidence.jsonl"
        reasoning = self.study / "04-findings/product-reasoning.json"
        past = time.time() - 3600
        os.utime(reasoning, (past, past))
        now = time.time()
        os.utime(evidence, (now, now))
        result = self._deliver()
        self.assertTrue(result["number_stale"])
        html = self.page.read_text(encoding="utf-8")
        self.assertIn("数字已更新，结论文字尚未重算", html)
        self.assertIn("--kind web", html)
        self.assertTrue(evidence.is_file())

    def test_without_reasoning_chain_the_page_still_renders(self) -> None:
        (self.study / "04-findings/product-reasoning.json").unlink()
        result = self._deliver()
        self.assertEqual(result["status"], "written")
        html = self.page.read_text(encoding="utf-8")
        self.assertIn("尚未建立七节点推理", html)
        self.assertIn("边界", html)

    def _add_second_chain(self, *, records: bool) -> None:
        path = self.study / "04-findings/product-reasoning.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        second = json.loads(json.dumps(payload["chains"][0]))
        second["id"] = "PR02"
        second["title"] = "LATEST-DECISION-PR02"
        second["nodes"]["scene"]["statement"] = "SCENE-FROM-LATEST-PR02"
        second["nodes"]["business"]["statement"] = "BUSINESS-FROM-LATEST-PR02"
        payload["chains"].append(second)
        if records:
            payload["decision_records"] = [
                {"record_id": "DR-OLD", "chain_id": "PR01", "version": 1,
                 "recorded_at": "2026-11-18T09:00:00+08:00",
                 "decision_maker": "reviewer", "decision": "old",
                 "next_action": "old", "chain_fingerprint": "old"},
                {"record_id": "DR-NEW", "chain_id": "PR02", "version": 2,
                 "recorded_at": "2026-11-19T09:00:00+08:00",
                 "decision_maker": "reviewer", "decision": "new",
                 "next_action": "new", "chain_fingerprint": "new"},
            ]
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def test_web_follows_the_newest_decision_record(self) -> None:
        self._add_second_chain(records=True)
        self._deliver()
        html = self.page.read_text(encoding="utf-8")
        headline = html.split('<section id="read">', 1)[0]
        self.assertIn("BUSINESS-FROM-LATEST-PR02", headline)
        chain_section = html.split('<section id="chain">', 1)[1].split("</section>", 1)[0]
        self.assertIn("SCENE-FROM-LATEST-PR02", chain_section)

    def test_web_does_not_expand_the_first_chain_without_a_decision(self) -> None:
        self._add_second_chain(records=False)
        self._deliver()
        html = self.page.read_text(encoding="utf-8")
        headline = html.split('<section id="read">', 1)[0]
        self.assertNotIn("BUSINESS-FROM-LATEST-PR02", headline)
        chain_section = html.split('<section id="chain">', 1)[1].split("</section>", 1)[0]
        self.assertNotIn("SCENE-FROM-LATEST-PR02", chain_section)
        self.assertIn("--chain", html)

    def _set_source_url(self, record_id: str, url: str) -> None:
        path = self.study / "02-data/evidence.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()]
        for row in rows:
            if row.get("record_id") == record_id:
                row["source_url"] = url
        path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
                        encoding="utf-8")

    def test_unsafe_source_urls_are_rendered_inert(self) -> None:
        for payload in ("javascript:alert(1)", "data:text/html,<script>alert(1)</script>",
                        "file:///etc/passwd", "//evil.example/x"):
            with self.subTest(payload=payload):
                self._set_source_url("R01", payload)
                self._deliver()
                html = self.page.read_text(encoding="utf-8")
                self.assertNotIn('<a href="javascript', html)
                self.assertNotIn('<a href="data:', html)
                self.assertNotIn('<a href="file:', html)
                self.assertNotIn('href="//evil.example', html)
                self.assertIn("来源链接已停用", html)

    def test_https_source_url_stays_clickable(self) -> None:
        self._set_source_url("R01", "https://example.com/post/1?a=1&b=2")
        self._deliver()
        html = self.page.read_text(encoding="utf-8")
        self.assertIn('href="https://example.com/post/1?a=1&amp;b=2"', html)
        self.assertIn('rel="noopener noreferrer"', html)

    def test_web_surface_declares_content_security_policy(self) -> None:
        self._deliver()
        html = self.page.read_text(encoding="utf-8")
        self.assertIn('http-equiv="Content-Security-Policy"', html)
        self.assertIn("default-src 'none'", html)
        self.assertIn("frame-ancestors 'none'", html)
        self.assertNotIn("<script", html)

    def test_mcp_deliver_accepts_web(self) -> None:
        responses = run_mcp({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {
                "name": "askovo_deliver",
                "arguments": {"study_dir": str(self.study), "kind": "web"},
            },
        })
        self.assertTrue(responses)
        payload = json.loads(responses[-1]["result"]["content"][0]["text"])
        self.assertEqual(payload["exit_code"], 0, payload)
        self.assertEqual(payload["result"]["status"], "written")
        self.assertEqual(payload["result"]["kind"], "web")


if __name__ == "__main__":
    unittest.main()
