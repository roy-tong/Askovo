#!/usr/bin/env python3
"""A-05 single-judgment evidence page (PRD acceptance A-P0-01..14).

Frozen acceptance tests for `askovo page` and
`skills/askovo/scripts/evidence_page.py`. The page is an **L0 read-only
projection** of `04-findings/product-reasoning.json` plus the evidence and
review artifacts it cites: it never edits the canonical chain, never registers
evidence, never approves a decision, and never sends anything. Counter evidence
and `needs_re_review` are review signals, not an automatic verdict.

Everything runs offline on the synthetic sample study.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/askovo/scripts/askovo.py"
SAMPLE = ROOT / "examples/sample-study"
SCRIPTS = ROOT / "skills/askovo/scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import evidence_page  # noqa: E402

CANONICAL_REF = "04-findings/product-reasoning.json"
REVIEW_REF = "05-audit/decision-review.json"
SNAPSHOT_DIR = "04-findings/deltas/decision-snapshots"


def copy_sample(test: unittest.TestCase) -> Path:
    target = Path(tempfile.mkdtemp(prefix="askovo-page-"))
    test.addCleanup(shutil.rmtree, target, True)
    destination = target / "study"
    shutil.copytree(SAMPLE, destination)
    return destination


def build(study: Path, chain: str = "", node: str = "") -> dict:
    return evidence_page.build_evidence_page(
        study, chain, node, now="2026-11-19T10:00:00+08:00")


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(CLI), *args],
                          cwd=str(ROOT), capture_output=True, text=True)


class SamplePageTest(unittest.TestCase):
    """A-P0-01..06: the seven-node navigation and the evidence projection."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.page = build(SAMPLE)

    def test_01_default_scene_navigation(self) -> None:
        page = self.page
        self.assertEqual(page["schema"], "askovo.evidence-page/1")
        self.assertTrue(page["read_only"])
        self.assertEqual(page["node"]["id"], "scene")
        self.assertEqual(page["navigation"]["position"], "1/7")
        self.assertEqual([item["id"] for item in page["navigation"]["nodes"]],
                         ["scene", "user", "pain", "need", "feature", "product", "business"])
        self.assertEqual([item["current"] for item in page["navigation"]["nodes"]].count(True), 1)

    def test_02_supporting_evidence(self) -> None:
        supporting = self.page["supporting"]
        self.assertEqual([entry["record_id"] for entry in supporting], ["R01", "R02"])
        self.assertTrue(all(entry["exists"] for entry in supporting))
        self.assertTrue(all(entry["registered_as"] == "node.evidence_ids" for entry in supporting))

    def test_03_counter_evidence_deduped(self) -> None:
        counter = self.page["counter"]
        self.assertEqual([entry["record_id"] for entry in counter], ["R05", "R07"])
        supporting_ids = {entry["record_id"] for entry in self.page["supporting"]}
        self.assertFalse(supporting_ids & {entry["record_id"] for entry in counter})
        for entry in counter:
            self.assertTrue(entry["registered_on_chain"])
            self.assertTrue(entry["registered_in_judgment"])
            self.assertFalse(entry["overlaps_with_supporting"])

    def test_04_reasoning_edges(self) -> None:
        reasoning = self.page["reasoning"]
        self.assertIn("alert", reasoning["statement"])
        self.assertTrue(reasoning["rationale"])
        self.assertTrue(reasoning["alternatives"])
        self.assertTrue(reasoning["assumptions"])
        self.assertTrue(all(isinstance(item, str) for item in reasoning["assumptions"]))

    def test_05_gaps_and_falsification(self) -> None:
        gaps = self.page["gaps"]
        self.assertEqual(len(gaps["chain"]), 4)
        self.assertTrue(gaps["judgment"])
        self.assertTrue(self.page["falsification"]["chain_next_test"])
        hypotheses = self.page["falsification"]["hypotheses"]
        self.assertEqual([item["id"] for item in hypotheses], ["H1"])
        self.assertTrue(hypotheses[0]["falsified_if"])

    def test_06_review_required_state(self) -> None:
        page = self.page
        self.assertTrue(page["decision"]["needs_re_review"])
        self.assertEqual(page["decision"]["counter_evidence_ids"], ["R05", "R07"])
        self.assertEqual(page["state"], "review_required")
        summary = evidence_page.render_summary(page)
        self.assertIn("需要", summary)
        self.assertIn("R05, R07", summary)


class StaleAndArtifactTest(unittest.TestCase):
    """A-P0-07..10: broken references, drift, snapshots and decision records."""

    def test_07_broken_reference_sets_stale(self) -> None:
        study = copy_sample(self)
        path = study / CANONICAL_REF
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["chains"][0]["nodes"]["scene"]["evidence_ids"].append("R99")
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        page = build(study)
        self.assertEqual(page["state"], "stale")
        codes = {item.get("detail_code") for item in page["states"]}
        self.assertIn("BROKEN_REFERENCE", codes)
        details = " ".join(item.get("detail", "") for item in page["states"])
        self.assertIn("R99", details)
        self.assertIn("R99", page["missing"])

    def test_08_input_drift_sets_stale(self) -> None:
        study = copy_sample(self)
        review = study / REVIEW_REF
        review.parent.mkdir(parents=True, exist_ok=True)
        review.write_text(json.dumps({
            "input_fingerprints": {"evidence": {"R01": "sha256:old"}},
        }, ensure_ascii=False), encoding="utf-8")

        page = build(study)
        self.assertEqual(page["state"], "stale")
        codes = {item.get("detail_code") for item in page["states"]}
        self.assertIn("INPUT_DRIFT", codes)

    def test_09_decision_snapshots_listed(self) -> None:
        study = copy_sample(self)
        directory = study / SNAPSHOT_DIR
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "DS-001.json").write_text(json.dumps({
            "decision_id": "DS-001",
            "approved_at": "2026-11-10T09:00:00+08:00",
            "approved_by": "Roy",
            "chosen_option": "option-A",
            "version": "2",
            "needs_re_review_at_approval": False,
            "current_review_status": "needs_re_review",
        }, ensure_ascii=False), encoding="utf-8")

        page = build(study)
        items = page["snapshots"]["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["decision_id"], "DS-001")
        self.assertEqual(items[0]["chosen_option"], "option-A")
        self.assertEqual(items[0]["current_review_status"], "needs_re_review")

    def test_10_decision_records_listed(self) -> None:
        study = copy_sample(self)
        path = study / CANONICAL_REF
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["decision_records"] = [{
            "record_id": "DR-001",
            "chain_id": "PR01",
            "version": 1,
            "parent_version": None,
            "recorded_at": "2026-11-10T09:00:00+08:00",
            "decision_maker": "Roy",
            "decision": "option-A",
            "next_action": "run the bounded pilot",
            "chain_fingerprint": "sha256:abc",
        }]
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        page = build(study)
        self.assertTrue(page["decision_records"]["available"])
        self.assertEqual(page["decision_records"]["count"], 1)
        self.assertEqual(page["decision_records"]["records"][0]["record_id"], "DR-001")


class HtmlAndStateTest(unittest.TestCase):
    """A-P0-11..14: escaping, empty state, unknown node, CLI surface."""

    def test_11_html_escapes_untrusted_text(self) -> None:
        study = copy_sample(self)
        path = study / CANONICAL_REF
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["chains"][0]["nodes"]["scene"]["statement"] = "<script>alert(1)</script>"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        html = evidence_page.render_html(build(study))
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script", html)
        self.assertNotIn("<img", html)
        self.assertNotIn("<link", html)
        self.assertNotIn('href="http', html)

    def test_12_empty_study_state(self) -> None:
        study = Path(tempfile.mkdtemp(prefix="askovo-empty-"))
        self.addCleanup(shutil.rmtree, study, True)
        (study / "study.json").write_text(json.dumps({
            "study_id": "empty-study", "title": "Empty",
        }), encoding="utf-8")

        page = build(study)
        self.assertEqual(page["state"], "empty")
        summary = evidence_page.render_summary(page)
        self.assertIn("支撑证据：未登记", summary)
        html = evidence_page.render_html(page)
        self.assertNotIn("PASS", html)
        self.assertIn("这不等于“无风险”", html)
        self.assertIn("页面不据此下通过结论", html)

    def test_13_unknown_node_state(self) -> None:
        page = build(SAMPLE, node="hook")
        self.assertEqual(page["state"], "partial")
        codes = {item["code"] for item in page["states"]}
        self.assertIn("FIELD_UNREGISTERED", codes)
        self.assertEqual(page["navigation"]["position"], "")

    def test_14_cli_json_and_html_refusal(self) -> None:
        result = run_cli("page", "examples/sample-study", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["schema"], "askovo.evidence-page/1")
        self.assertEqual(payload["html_path"], "")

        directory = Path(tempfile.mkdtemp(prefix="askovo-cli-"))
        self.addCleanup(shutil.rmtree, directory, True)
        target = directory / "page.html"
        first = run_cli("page", "examples/sample-study", "--html", str(target))
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertTrue(target.is_file())
        self.assertIn("L0 只读", target.read_text(encoding="utf-8"))

        second = run_cli("page", "examples/sample-study", "--html", str(target))
        self.assertEqual(second.returncode, 2)
        self.assertIn("OUTPUT_EXISTS", second.stdout)


class ChainSelectionAndQualificationTest(unittest.TestCase):
    """A-05: the page follows the decision and re-applies the evidence gate."""

    @staticmethod
    def _add_second_chain(study: Path, *, records: bool) -> None:
        path = study / CANONICAL_REF
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

    def test_15_page_follows_the_newest_decision_record(self) -> None:
        study = copy_sample(self)
        self._add_second_chain(study, records=True)
        page = build(study)
        self.assertEqual("PR02", page["chain"]["id"])
        self.assertEqual("decision", page["chain"]["selection"])
        self.assertEqual("SCENE-FROM-LATEST-PR02", page["reasoning"]["statement"])

    def test_16_several_chains_without_decision_are_empty(self) -> None:
        study = copy_sample(self)
        self._add_second_chain(study, records=False)
        page = build(study)
        self.assertEqual("empty", page["state"])
        self.assertEqual("", page["chain"]["id"])
        details = " ".join(item.get("detail", "") for item in page["states"])
        self.assertIn("--chain", details)
        self.assertNotEqual("Supervised mobile verification for fixed-camera blind spots",
                            page["reasoning"]["statement"])

    def test_17_unqualified_evidence_never_counts_as_support(self) -> None:
        study = copy_sample(self)
        path = study / "02-data" / "evidence.jsonl"
        rows = [json.loads(line) for line in
                path.read_text(encoding="utf-8").splitlines() if line.strip()]
        for row in rows:
            if row.get("record_id") == "R01":
                row["evidence_level"] = "NOT-REGISTERED"
        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                        encoding="utf-8")

        page = build(study)
        entry = next(item for item in page["supporting"] if item["record_id"] == "R01")
        self.assertFalse(entry["qualified"])
        faults = [item for item in page["faults"] if item["code"] == "EVIDENCE_UNQUALIFIED"]
        self.assertEqual(["R01"], [item["record_id"] for item in faults])
        self.assertEqual("partial", page["state"])
        html = evidence_page.render_html(page)
        self.assertIn("未通过证据资格门", html)


if __name__ == "__main__":
    unittest.main()
