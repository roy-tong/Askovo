#!/usr/bin/env python3
"""Human review of capture candidates: accept -> evidence, reject, paste import.

The golden chain is capture/paste -> human review -> evidence.jsonl -> the
existing analyze/chain pipeline. Candidates never promote themselves.
"""
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
# append (never insert): scripts/ contains askovo.py, which would shadow the
# repository's root `askovo` package for test modules imported after this one.
if str(CLI.parent) not in sys.path:
    sys.path.append(str(CLI.parent))

import capture_review  # noqa: E402
import sure_engine  # noqa: E402


def run_cli(*args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run([sys.executable, str(CLI), *args],
                          check=False, capture_output=True, text=True, timeout=120, env=env)


def _mocked_capture(study: Path, url: str = "https://example.com/visible-page") -> str:
    """Produce a genuine candidate through capture_page with a mocked CDP."""
    document = json.loads((study / "study.json").read_text(encoding="utf-8"))
    document.setdefault("scope", {})["allowed_sources"] = ["web"]
    (study / "study.json").write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    class _FakeClient:
        def __init__(self, ws):
            self.ws = ws

        def call(self, method, params=None):
            if method == "Page.captureScreenshot":
                return {"data": "aGVsbG8="}
            return {}

        def evaluate(self, expression):
            return {"title": "示例页面", "url": url,
                    "text": "用户说：夜间误报很烦，希望先判断再起床。\n她现在关掉了全部推送。"}

        def close(self):
            pass

    saved = (sure_engine.cdp_new_page, sure_engine._WebSocket, sure_engine.CDPClient)
    sure_engine.cdp_new_page = lambda base, url: "ws://127.0.0.1:9222/devtools/page/1"
    sure_engine._WebSocket = lambda url: object()
    sure_engine.CDPClient = _FakeClient
    try:
        result = sure_engine.capture_page(study, url, "http://127.0.0.1:9222", True)
    finally:
        sure_engine.cdp_new_page, sure_engine._WebSocket, sure_engine.CDPClient = saved
    assert result["status"] == "captured", result
    return Path(result["capture"]).stem


class ReviewCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.study = Path(tmp.name) / "study"
        shutil.copytree(SAMPLE, self.study)


class CaptureAcceptTests(ReviewCase):
    def test_accept_registers_evidence_with_backlinks(self) -> None:
        capture_id = _mocked_capture(self.study)
        result = capture_review.accept(self.study, capture_id, by="验收员")
        self.assertEqual("accepted", result["status"])
        records = [
            json.loads(line)
            for line in (self.study / "02-data/evidence.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        added = [r for r in records if r["record_id"] == f"cap-{capture_id}"]
        self.assertEqual(1, len(added))
        record = added[0]
        self.assertEqual("E1", record["evidence_level"])
        self.assertEqual("capture", record["source_family"])
        self.assertIn("captures/" + capture_id, record["source_ref"])
        self.assertEqual(capture_id, record["capture_id"])
        self.assertIn("夜间误报", record["text"])
        self.assertIn("验收员", record["evidence_basis"])
        payload = json.loads(
            (self.study / "01-sources/captures" / f"{capture_id}.json").read_text(encoding="utf-8"))
        self.assertEqual("accepted", payload["evidence_status"])
        self.assertEqual("验收员", payload["review"]["reviewed_by"])
        trail = (self.study / "01-sources/captures/review-trail.jsonl").read_text(encoding="utf-8")
        self.assertIn(capture_id, trail)
        plan = (self.study / "01-sources/source-plan.csv").read_text(encoding="utf-8")
        self.assertIn("capture", plan)

    def test_accept_is_idempotent_and_verifies_the_join(self) -> None:
        capture_id = _mocked_capture(self.study)
        first = capture_review.accept(self.study, capture_id, by="验收员")
        self.assertFalse(first["already_accepted"])
        again = capture_review.accept(self.study, capture_id, by="另一位")
        self.assertTrue(again["already_accepted"])
        records = [
            json.loads(line)
            for line in (self.study / "02-data/evidence.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(1, len([r for r in records if r["record_id"] == f"cap-{capture_id}"]))
        # A capture marked accepted whose evidence record vanished is an error,
        # not a silent re-registration.
        records = [r for r in records if r["record_id"] != f"cap-{capture_id}"]
        (self.study / "02-data/evidence.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
        with self.assertRaises(capture_review.CaptureReviewError) as ctx:
            capture_review.accept(self.study, capture_id, by="第三人")
        self.assertEqual("INTERNAL_ERROR", ctx.exception.reason_code)

    def test_accept_requires_named_human_and_respects_level_cap(self) -> None:
        capture_id = _mocked_capture(self.study)
        with self.assertRaises(capture_review.CaptureReviewError) as ctx:
            capture_review.accept(self.study, capture_id, by="")
        self.assertEqual("AUTH_REQUIRED", ctx.exception.reason_code)
        for level in ("E3", "E4+", "E5"):
            with self.assertRaises(capture_review.CaptureReviewError) as ctx:
                capture_review.accept(self.study, capture_id, by="验收员", evidence_level=level)
            self.assertEqual("POLICY_DENIED", ctx.exception.reason_code)
        self.assertFalse((self.study / "02-data/evidence.jsonl").read_text(encoding="utf-8").endswith("cap-"))

    def test_reject_marks_candidate_and_never_writes_evidence(self) -> None:
        capture_id = _mocked_capture(self.study)
        before = (self.study / "02-data/evidence.jsonl").read_text(encoding="utf-8")
        result = capture_review.reject(self.study, capture_id, by="验收员", reason="页面是营销文案，不是用户声音")
        self.assertEqual("rejected", result["status"])
        self.assertEqual(before, (self.study / "02-data/evidence.jsonl").read_text(encoding="utf-8"))
        payload = json.loads(
            (self.study / "01-sources/captures" / f"{capture_id}.json").read_text(encoding="utf-8"))
        self.assertEqual("rejected", payload["evidence_status"])
        with self.assertRaises(capture_review.CaptureReviewError):
            capture_review.accept(self.study, capture_id, by="迟到的审核")

    def test_list_reports_candidate_status(self) -> None:
        capture_id = _mocked_capture(self.study)
        listed = capture_review.list_candidates(self.study)
        entry = next(item for item in listed["captures"] if item["capture_id"] == capture_id)
        self.assertEqual("candidate", entry["evidence_status"])
        capture_review.accept(self.study, capture_id, by="验收员")
        entry = next(
            item for item in capture_review.list_candidates(self.study)["captures"]
            if item["capture_id"] == capture_id)
        self.assertEqual("accepted", entry["evidence_status"])


class CaptureReviewCliTests(ReviewCase):
    def test_cli_accept_and_reject_roundtrip(self) -> None:
        capture_id = _mocked_capture(self.study)
        completed = run_cli("capture", "accept", str(self.study),
                            "--capture", capture_id, "--by", "CLI 验收员")
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual("accepted", payload["status"])
        self.assertEqual(f"cap-{capture_id}", payload["evidence_record_id"])
        listed = run_cli("capture", "list", str(self.study))
        self.assertEqual(0, listed.returncode, listed.stdout + listed.stderr)
        self.assertIn(capture_id, listed.stdout)

    def test_cli_capture_keeps_working_with_url_form_and_governance(self) -> None:
        document = json.loads((self.study / "study.json").read_text(encoding="utf-8"))
        document["scope"]["allowed_sources"] = ["amazon"]
        (self.study / "study.json").write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        completed = run_cli("capture", "page", str(self.study), "--url",
                            "https://www.reddit.com/r/x", "--ack-terms")
        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertEqual("scope_blocked", json.loads(completed.stdout)["status"])


class PasteImportReviewTests(ReviewCase):
    def _paste(self, name: str, text: str) -> Path:
        path = self.study.parent / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_import_assigns_reviewed_level_and_declares_family(self) -> None:
        pasted = self._paste("paste.txt", "用户说：我宁可手动看回放，也不想被夜间误报吵醒。\n已经关掉了推送通知。\n")
        completed = run_cli("import", str(self.study), str(pasted),
                            "--source-family", "paste", "--evidence-level", "E1")
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        records = [
            json.loads(line)
            for line in (self.study / "02-data/evidence.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        added = [r for r in records if r["source_family"] == "paste"]
        self.assertEqual(1, len(added))
        self.assertEqual("E1", added[0]["evidence_level"])
        plan = (self.study / "01-sources/source-plan.csv").read_text(encoding="utf-8")
        self.assertIn("paste", plan)
        checked = run_cli("check", str(self.study), "--stage", "evidence", "--format", "json")
        self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)

    def test_import_refuses_levels_a_paste_cannot_support(self) -> None:
        pasted = self._paste("paid.txt", "有人说他付了钱。\n")
        completed = run_cli("import", str(self.study), str(pasted),
                            "--source-family", "paste", "--evidence-level", "E5")
        self.assertEqual(1, completed.returncode)
        payload = json.loads(completed.stdout)
        self.assertEqual("POLICY_DENIED", payload["reason_code"])
        records = [
            json.loads(line)
            for line in (self.study / "02-data/evidence.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(0, len([r for r in records if r["source_family"] == "paste"]))


if __name__ == "__main__":
    unittest.main()
