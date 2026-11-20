#!/usr/bin/env python3
"""Candidate capture -> named review -> evidence -> analysis/business projection.

All page/CDP/OCR operations are mocked and every study is a temporary copy of
the synthetic sample. No network, real collection, or sample-output mutation.
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
# append (never insert): scripts/ contains askovo.py, which would otherwise
# shadow the repository's root package for test modules imported after this one.
if str(CLI.parent) not in sys.path:
    sys.path.append(str(CLI.parent))

import capture_review  # noqa: E402
import sure_engine  # noqa: E402


def run_cli(*args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run([sys.executable, str(CLI), *args],
                          check=False, capture_output=True, text=True, timeout=120, env=env)


def _mocked_capture(
        study: Path,
        url: str = "https://www.amazon.com/product-reviews/B0",
        ocr_text: str = "OCR：AUTO_GO_IS_NOT_A_BUSINESS_CONCLUSION") -> str:
    """Produce a genuine candidate through capture_page with mocked CDP + OCR."""
    document = json.loads((study / "study.json").read_text(encoding="utf-8"))
    document.setdefault("scope", {})["allowed_sources"] = ["amazon"]
    document["source_adapters"] = {"amazon": {"enabled": True}}
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

    saved = (sure_engine.cdp_new_page, sure_engine._WebSocket,
             sure_engine.CDPClient, sure_engine._ocr_with_vision)
    sure_engine.cdp_new_page = lambda base, url: "ws://127.0.0.1:9222/devtools/page/1"
    sure_engine._WebSocket = lambda url: object()
    sure_engine.CDPClient = _FakeClient
    sure_engine._ocr_with_vision = lambda path: {"engine": "fake", "text": ocr_text, "error": ""}
    try:
        result = sure_engine.capture_page(
            study, url, "http://127.0.0.1:9222", True, ocr=True, wait_seconds=0)
    finally:
        (sure_engine.cdp_new_page, sure_engine._WebSocket,
         sure_engine.CDPClient, sure_engine._ocr_with_vision) = saved
    assert result["status"] == "captured", result
    return result["capture_id"]


class ReviewCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.study = Path(tmp.name) / "study"
        shutil.copytree(SAMPLE, self.study)

    def records(self) -> list:
        return [json.loads(line)
                for line in (self.study / "02-data/evidence.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()]

    def accept(self, capture_id: str, **kwargs):
        kwargs.setdefault("by", "验收员")
        kwargs.setdefault("evidence_level", "E1")
        return capture_review.accept(self.study, capture_id, **kwargs)


class CaptureAcceptTests(ReviewCase):
    def test_accept_registers_normalized_evidence_with_all_backlinks(self) -> None:
        capture_id = _mocked_capture(self.study)
        result = self.accept(capture_id)
        self.assertEqual("accepted", result["status"])
        added = [r for r in self.records() if r["record_id"] == f"cap-{capture_id}"]
        self.assertEqual(1, len(added))
        record = added[0]
        self.assertEqual("E1", record["evidence_level"])
        self.assertEqual("capture", record["source_family"])
        self.assertEqual(f"01-sources/captures/{capture_id}.json", record["source_ref"])
        self.assertEqual(capture_id, record["capture_id"])
        self.assertEqual("https://www.amazon.com/product-reviews/B0", record["source_url"])
        self.assertEqual(f"01-sources/captures/{capture_id}.png", record["capture_screenshot_ref"])
        self.assertIn("夜间误报", record["text"])
        self.assertIn("AUTO_GO_IS_NOT_A_BUSINESS_CONCLUSION", record["capture_ocr_text"])
        self.assertTrue(record["capture_text_sha256"])
        self.assertTrue(record["capture_ocr_text_sha256"])
        self.assertTrue(record["capture_screenshot_sha256"])
        self.assertEqual("reviewed", record["human_review_status"])
        self.assertEqual("named_human_accept", record["review_confirmation"])
        self.assertEqual("验收员", record["reviewed_by"])
        self.assertTrue(record["reviewed_at"])
        self.assertIn("验收员", record["evidence_basis"])
        payload = json.loads(
            (self.study / "01-sources/captures" / f"{capture_id}.json").read_text(encoding="utf-8"))
        self.assertEqual("accepted", payload["evidence_status"])
        self.assertEqual("验收员", payload["review"]["reviewed_by"])
        self.assertEqual(record["reviewed_at"], payload["review"]["reviewed_at"])
        trail = (self.study / "01-sources/captures/review-trail.jsonl").read_text(encoding="utf-8")
        self.assertIn(capture_id, trail)
        self.assertIn("screenshot_sha256", trail)
        plan = (self.study / "01-sources/source-plan.csv").read_text(encoding="utf-8")
        self.assertIn("capture", plan)

    def test_accept_is_idempotent_and_verifies_the_join(self) -> None:
        capture_id = _mocked_capture(self.study)
        first = self.accept(capture_id)
        self.assertFalse(first["already_accepted"])
        again = self.accept(capture_id, by="另一位")
        self.assertTrue(again["already_accepted"])
        self.assertEqual(1, len([r for r in self.records() if r["record_id"] == f"cap-{capture_id}"]))
        records = [r for r in self.records() if r["record_id"] != f"cap-{capture_id}"]
        (self.study / "02-data/evidence.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
        with self.assertRaises(capture_review.CaptureReviewError) as ctx:
            self.accept(capture_id, by="第三人")
        self.assertEqual("INTERNAL_ERROR", ctx.exception.reason_code)

    def test_accept_requires_a_named_human_and_derives_the_level(self) -> None:
        capture_id = _mocked_capture(self.study)
        before = (self.study / "02-data/evidence.jsonl").read_bytes()
        with self.assertRaises(capture_review.CaptureReviewError) as ctx:
            capture_review.accept(self.study, capture_id, by="", evidence_level="E1")
        self.assertEqual("AUTH_REQUIRED", ctx.exception.reason_code)
        for level in ("E3", "E4+", "E5"):
            with self.assertRaises(capture_review.CaptureReviewError) as ctx:
                self.accept(capture_id, evidence_level=level)
            self.assertEqual("POLICY_DENIED", ctx.exception.reason_code)
        self.assertEqual(before, (self.study / "02-data/evidence.jsonl").read_bytes())
        # The reviewer no longer self-assigns a level: omitting --evidence-level is
        # valid, and "one voiced page statement" derives E1.
        result = capture_review.accept(self.study, capture_id, by="验收员")
        self.assertEqual("accepted", result["status"])
        self.assertEqual("E1", result["evidence_level"])
        self.assertEqual("", result["requested_evidence_level"])
        self.assertFalse(result["level_capped"])
        self.assertTrue(result["level_basis"])
        self.assertEqual("askovo-level-derivation/1", result["level_derivation_version"])

    def test_self_reported_high_level_is_capped_by_the_derivation(self) -> None:
        capture_id = _mocked_capture(self.study)
        result = self.accept(capture_id, evidence_level="E2")  # no --observation practice
        self.assertEqual("accepted", result["status"])
        self.assertEqual("E2", result["requested_evidence_level"])
        self.assertEqual("E1", result["evidence_level"])
        self.assertTrue(result["level_capped"])
        record = next(r for r in self.records() if r["record_id"] == f"cap-{capture_id}")
        self.assertEqual("E1", record["evidence_level"])
        self.assertEqual("E2", record["requested_evidence_level"])
        checked = run_cli("check", str(self.study), "--stage", "evidence", "--format", "json")
        self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)

    def test_practice_observation_reaches_e2_only_from_human_read_page_text(self) -> None:
        practice_id = _mocked_capture(
            self.study, url="https://www.amazon.com/product-reviews/B001")
        practice = self.accept(practice_id, evidence_level="E2", observation="practice")
        self.assertEqual("E2", practice["evidence_level"])
        self.assertFalse(practice["level_capped"])
        self.assertIn("practice", practice["level_basis"])
        ocr_id = _mocked_capture(
            self.study, url="https://www.amazon.com/product-reviews/B002")
        ocr = self.accept(ocr_id, evidence_level="E2", observation="practice",
                          from_text="ocr")
        self.assertEqual("E1", ocr["evidence_level"])
        self.assertTrue(ocr["level_capped"])
        self.assertIn("OCR", ocr["level_basis"])
        context_id = _mocked_capture(
            self.study, url="https://www.amazon.com/product-reviews/B003")
        context = self.accept(context_id, evidence_level="E1", observation="context")
        self.assertEqual("E0", context["evidence_level"])
        self.assertTrue(context["level_capped"])

    def test_concept_test_record_is_the_only_route_to_e3(self) -> None:
        capture_id = _mocked_capture(self.study)
        concept = self.study / "concept-test.json"
        concept.write_text(json.dumps({
            "stimulus": "新的夜间告警设置页",
            "sample_size": 12,
            "response_metric": "5 点购买意向均值",
            "result": "4.1",
        }, ensure_ascii=False), encoding="utf-8")
        result = self.accept(capture_id, evidence_level="E3", concept_test=concept)
        self.assertEqual("E3", result["evidence_level"])
        self.assertFalse(result["level_capped"])
        record = next(r for r in self.records() if r["record_id"] == f"cap-{capture_id}")
        self.assertIn("E3 concept test", record["evidence_basis"])
        checked = run_cli("check", str(self.study), "--stage", "evidence", "--format", "json")
        self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)
        incomplete = self.study / "concept-test-incomplete.json"
        incomplete.write_text(json.dumps({"stimulus": "x", "sample_size": 3}, ensure_ascii=False),
                              encoding="utf-8")
        second_id = _mocked_capture(
            self.study, url="https://www.amazon.com/product-reviews/B009")
        with self.assertRaises(capture_review.CaptureReviewError) as ctx:
            self.accept(second_id, evidence_level="E3", concept_test=incomplete)
        self.assertEqual("INPUT_REQUIRED", ctx.exception.reason_code)

    def test_hand_edited_level_fails_the_derivation_audit(self) -> None:
        capture_id = _mocked_capture(self.study)
        self.accept(capture_id, evidence_level="E1")
        rows = self.records()
        for row in rows:
            if row["record_id"] == f"cap-{capture_id}":
                row["evidence_level"] = "E2"
        (self.study / "02-data/evidence.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        record = next(r for r in self.records() if r["record_id"] == f"cap-{capture_id}")
        errors = capture_review.validate_evidence_record(self.study, record)
        self.assertTrue(errors)
        self.assertIn("does not match the derived level", " ".join(errors))
        checked = run_cli("check", str(self.study), "--stage", "evidence", "--format", "json")
        self.assertEqual(1, checked.returncode, checked.stdout + checked.stderr)

    def test_unreviewed_candidate_is_not_analyzed_and_manual_ocr_row_fails_audit(self) -> None:
        capture_id = _mocked_capture(self.study)
        record_id = f"cap-{capture_id}"
        before = (self.study / "02-data/evidence.jsonl").read_bytes()
        analyzed = run_cli("analyze", str(self.study), "--question", "夜间误报")
        self.assertEqual(0, analyzed.returncode, analyzed.stdout + analyzed.stderr)
        analysis = json.loads((self.study / "04-findings/analysis.json").read_text(encoding="utf-8"))
        self.assertNotIn(record_id, json.dumps(analysis, ensure_ascii=False))
        denied = run_cli("capture", "accept", str(self.study), "--capture", capture_id,
                         "--evidence-level", "E1")
        self.assertEqual(1, denied.returncode, denied.stdout + denied.stderr)
        self.assertEqual("AUTH_REQUIRED", json.loads(denied.stdout)["reason_code"])
        self.assertEqual(before, (self.study / "02-data/evidence.jsonl").read_bytes())
        generic = run_cli("import", str(self.study),
                          str(self.study / "01-sources/captures" / f"{capture_id}.json"),
                          "--source-family", "paste", "--evidence-level", "E1")
        self.assertEqual(1, generic.returncode, generic.stdout + generic.stderr)
        self.assertEqual("POLICY_DENIED", json.loads(generic.stdout)["reason_code"])
        self.assertEqual(before, (self.study / "02-data/evidence.jsonl").read_bytes())

        # Even a hand-appended row cannot bypass the reviewed-source evidence gate.
        fake = dict(self.records()[0])
        fake.update({
            "record_id": record_id, "source_family": "capture",
            "source_ref": f"01-sources/captures/{capture_id}.json",
            "source_url": "https://www.amazon.com/product-reviews/B0",
            "normalized_text_hash": "sha256:unreviewed-ocr",
            "capture_id": capture_id, "text": "OCR 自动结论", "evidence_level": "E1",
        })
        for key in list(fake):
            if key != "capture_id" and (
                    key.startswith("review") or key.startswith("capture_")
                    or key == "human_review_status"):
                fake.pop(key, None)
        with (self.study / "02-data/evidence.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(fake, ensure_ascii=False) + "\n")
        checked = run_cli("check", str(self.study), "--stage", "evidence", "--format", "json")
        self.assertEqual(1, checked.returncode, checked.stdout + checked.stderr)
        self.assertIn("reviewed capture provenance", checked.stdout)
        self.assertIn("not accepted", checked.stdout)

    def test_reject_marks_candidate_and_never_writes_evidence(self) -> None:
        capture_id = _mocked_capture(self.study)
        before = (self.study / "02-data/evidence.jsonl").read_text(encoding="utf-8")
        result = capture_review.reject(
            self.study, capture_id, by="验收员", reason="页面是营销文案，不是用户声音")
        self.assertEqual("rejected", result["status"])
        self.assertEqual(before, (self.study / "02-data/evidence.jsonl").read_text(encoding="utf-8"))
        payload = json.loads(
            (self.study / "01-sources/captures" / f"{capture_id}.json").read_text(encoding="utf-8"))
        self.assertEqual("rejected", payload["evidence_status"])
        with self.assertRaises(capture_review.CaptureReviewError):
            self.accept(capture_id, by="迟到的审核")

    def test_list_reports_candidate_status(self) -> None:
        capture_id = _mocked_capture(self.study)
        listed = capture_review.list_candidates(self.study)
        entry = next(item for item in listed["captures"] if item["capture_id"] == capture_id)
        self.assertEqual("candidate", entry["evidence_status"])
        self.accept(capture_id)
        entry = next(item for item in capture_review.list_candidates(self.study)["captures"]
                     if item["capture_id"] == capture_id)
        self.assertEqual("accepted", entry["evidence_status"])


class CaptureReviewCliTests(ReviewCase):
    def test_cli_accept_and_list_roundtrip(self) -> None:
        capture_id = _mocked_capture(self.study)
        completed = run_cli("capture", "accept", str(self.study),
                            "--capture", capture_id, "--by", "CLI 验收员",
                            "--evidence-level", "E1")
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual("accepted", payload["status"])
        self.assertEqual(f"cap-{capture_id}", payload["evidence_record_id"])
        listed = run_cli("capture", "list", str(self.study))
        self.assertEqual(0, listed.returncode, listed.stdout + listed.stderr)
        self.assertIn(capture_id, listed.stdout)

    def test_cli_capture_keeps_governance_for_disallowed_host(self) -> None:
        document = json.loads((self.study / "study.json").read_text(encoding="utf-8"))
        document["scope"]["allowed_sources"] = ["amazon"]
        (study_path := self.study / "study.json").write_text(
            json.dumps(document, ensure_ascii=False), encoding="utf-8")
        completed = run_cli("capture", "page", str(self.study), "--url",
                            "https://www.reddit.com/r/x", "--ack-terms")
        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertEqual("cdp_not_allowed", json.loads(completed.stdout)["status"])


class CaptureGoldenChainTests(ReviewCase):
    def test_reviewed_capture_reaches_analysis_and_human_linked_business_plan(self) -> None:
        capture_id = _mocked_capture(self.study)
        record_id = f"cap-{capture_id}"
        reasoning_path = self.study / "04-findings/product-reasoning.json"
        judgments_path = self.study / "04-findings/demand-judgments.json"
        reasoning_before = reasoning_path.read_bytes()
        judgments_before = judgments_path.read_bytes()
        reasoning = json.loads(reasoning_before)
        context_key = reasoning["chains"][0]["context_key"]
        business_statement = reasoning["chains"][0]["nodes"]["business"]["statement"]

        self.accept(capture_id, evidence_level="E2", observation="practice",
                    context_key=context_key)
        # Acceptance itself authors neither a judgment nor a seven-node conclusion.
        self.assertEqual(reasoning_before, reasoning_path.read_bytes())
        self.assertEqual(judgments_before, judgments_path.read_bytes())

        analyzed = run_cli("analyze", str(self.study), "--question", "夜间误报")
        self.assertEqual(0, analyzed.returncode, analyzed.stdout + analyzed.stderr)
        analysis = json.loads((self.study / "04-findings/analysis.json").read_text(encoding="utf-8"))
        self.assertEqual(1, analysis["by_platform"].get("web"))
        self.assertIn(record_id, {item["record_id"] for item in analysis["question_matches"]})
        self.assertNotIn("AUTO_GO_IS_NOT_A_BUSINESS_CONCLUSION", json.dumps(analysis))
        self.assertEqual(reasoning_before, reasoning_path.read_bytes())
        self.assertEqual(judgments_before, judgments_path.read_bytes())

        projected = run_cli("deliver", str(self.study), "--kind", "analysis")
        self.assertEqual(0, projected.returncode, projected.stdout + projected.stderr)
        analysis_report = (self.study / "06-report/analysis.md").read_text(encoding="utf-8")
        self.assertIn(record_id, analysis_report)
        self.assertIn("https://www.amazon.com/product-reviews/B0", analysis_report)
        self.assertIn(f"01-sources/captures/{capture_id}.json", analysis_report)

        delivered = run_cli("deliver", str(self.study), "--kind", "plan")
        self.assertEqual(0, delivered.returncode, delivered.stdout + delivered.stderr)
        plan_path = self.study / "06-report/plan.md"
        plan = plan_path.read_text(encoding="utf-8")
        self.assertIn(record_id, plan)
        self.assertIn("https://www.amazon.com/product-reviews/B0", plan)
        self.assertIn(f"01-sources/captures/{capture_id}.png", plan)
        self.assertIn("验收员", plan)
        self.assertIn(business_statement, plan)
        self.assertNotIn("AUTO_GO_IS_NOT_A_BUSINESS_CONCLUSION", plan)
        self.assertEqual(reasoning_before, reasoning_path.read_bytes())
        self.assertEqual(judgments_before, judgments_path.read_bytes())

        # A separate human semantic step registers the reviewed E2 record in the
        # existing judgment and problem-side nodes. No OCR-generated node is added.
        judgments = json.loads(judgments_before)
        judgments[0].setdefault("problem_evidence_ids", []).append(record_id)
        judgments_path.write_text(json.dumps(judgments, ensure_ascii=False, indent=2) + "\n",
                                  encoding="utf-8")
        reasoning = json.loads(reasoning_before)
        for node_name in ("scene", "pain", "need"):
            reasoning["chains"][0]["nodes"][node_name]["evidence_ids"].append(record_id)
        reasoning_path.write_text(json.dumps(reasoning, ensure_ascii=False, indent=2) + "\n",
                                  encoding="utf-8")
        checked = run_cli("check", str(self.study), "--stage", "full", "--format", "json")
        self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)
        delivered = run_cli("deliver", str(self.study), "--kind", "plan")
        self.assertEqual(0, delivered.returncode, delivered.stdout + delivered.stderr)
        linked_plan = plan_path.read_text(encoding="utf-8")
        self.assertIn(record_id, linked_plan)
        self.assertIn(business_statement, linked_plan)
        self.assertNotIn("AUTO_GO_IS_NOT_A_BUSINESS_CONCLUSION", linked_plan)
        self.assertEqual(business_statement,
                         json.loads(reasoning_path.read_text(encoding="utf-8"))
                         ["chains"][0]["nodes"]["business"]["statement"])


class ProcurementPreflightTests(ReviewCase):
    def test_paid_api_and_licensed_provider_routes_stop_without_transaction(self) -> None:
        for platform in ("x", "app_store"):
            with self.subTest(platform=platform):
                completed = run_cli("collect", str(self.study), "--platform", platform,
                                    "--query", "synthetic", "--dry-run")
                self.assertEqual(3, completed.returncode, completed.stdout + completed.stderr)
                payload = json.loads(completed.stdout)
                self.assertEqual("BLOCKED_USER_INPUT", payload["terminal_state"])
                self.assertEqual("INPUT_REQUIRED", payload["reason_code"])
                self.assertTrue(payload["requires_procurement"])
                self.assertFalse(payload["transaction_executed"])
                self.assertTrue(payload["user_action"])
                routes = {item["route"] for item in payload["alternative_routes"]}
                self.assertIn("authorized_export_or_paste", routes)
                self.assertIn("local_screenshot_transcription", routes)
                if platform == "x":
                    # x is CDP-enabled: the user-session visible-page route is a
                    # legitimate alternative to its paid API.
                    self.assertIn("authorized_visible_page_cdp", routes)
                else:
                    self.assertNotIn("authorized_visible_page_cdp", routes)

    def test_delivery_contract_keeps_business_outcome_separate(self) -> None:
        contract = json.loads((ROOT / "docs/delivery-contract.json").read_text(encoding="utf-8"))
        self.assertFalse(contract["core"]["report_only"])
        self.assertEqual(["do", "defer", "do_not_do"], contract["core"]["decision_options"])
        adopted = next(item for item in contract["decision_outcomes"] if item["id"] == "decision_adopted")
        self.assertTrue(adopted["requires_separate_evidence"])
        self.assertFalse(adopted["implied_by_delivery"])
        procurement = contract["procurement"]["when_paid_api_licensed_provider_or_purchase_is_required"]
        self.assertEqual("BLOCKED_USER_INPUT", procurement["terminal_state"])
        self.assertEqual("INPUT_REQUIRED", procurement["reason_code"])
        self.assertFalse(procurement["transaction_executed"])
        self.assertFalse(contract["candidate_inputs"]["ocr"]["automatic_product_or_business_conclusion"])


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
        added = [r for r in self.records() if r["source_family"] == "paste"]
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
        self.assertEqual(0, len([r for r in self.records() if r["source_family"] == "paste"]))


if __name__ == "__main__":
    unittest.main()
