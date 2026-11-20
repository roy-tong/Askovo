#!/usr/bin/env python3
"""A-NEXT-1 contextual evidence capture plan (PRD acceptance AN1-01..14).

A plan is a bounded, authorized collection brief derived from one chain's
``next_test``. It is never evidence, never changes a verdict, and imports
notes only as candidates with ``evidence_level=None``. Every fixture is a
temporary copy of the synthetic sample study; nothing touches the network.

Acceptance tests also sample the shared XN2 contract: idempotent writes,
same-id/different-hash conflicts, honest missing values, escaped external text,
deterministic rendering, and no canonical mutation.
"""
from __future__ import annotations

import csv
import io
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
SCRIPTS = ROOT / "skills/askovo/scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import capture_plan  # noqa: E402

CANONICAL_REF = "04-findings/product-reasoning.json"
AT = "2026-11-19T09:00:00+00:00"


def run_cli(*args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run([sys.executable, str(CLI), *args],
                          check=False, capture_output=True, text=True,
                          timeout=120, env=env)


class CapturePlanTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="askovo-capture-plan-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.study = self.tmp / "study"
        shutil.copytree(SAMPLE, self.study)
        self.reasoning = json.loads(
            (self.study / CANONICAL_REF).read_text(encoding="utf-8"))
        self.chain = self.reasoning["chains"][0]

    # ------------------------------------------------------------------ helpers
    def _build(self, **overrides):
        inputs = {
            "methods": ["interview", "survey"],
            "target_participants": {
                "segment": "Synthetic mobile-check households",
                "criteria": "Opted in, experienced a blind-spot check",
                "count": 6,
            },
            "consent": {
                "boundary": "Synthetic fixture: no real participants",
                "recording": "none",
                "withdrawal": "stop at any time",
                "data_handling": "local only",
            },
            "stop_conditions": ["Participant withdraws consent"],
            "triggers": ["Any real recording request"],
            "window": {"start": "2026-11-20", "end": "2026-12-04"},
            "at": AT,
        }
        inputs.update(overrides)
        return capture_plan.build_plan(self.study, "PR01", **inputs)

    def _authorized(self, **overrides):
        plan = self._build(**overrides)
        plan = capture_plan.submit_for_review(plan, actor="Ana", at=AT)
        plan = capture_plan.record_review(
            plan, reviewer="Li Hua", decision="approve", at=AT,
            note="scope is bounded")
        return capture_plan.authorize(
            plan, authorized_by="Ana", authorized_at=AT,
            authorization_ref="approval-1")

    @staticmethod
    def _candidate(**overrides):
        payload = {
            "context_key": "synthetic-mobile-check",
            "behavior_ref": "observed: checked the yard camera from phone",
            "alternative_behavior": "walked over to look",
            "consequence": "missed a delivery window",
            "counter_evidence": ["one participant found the camera enough"],
            "user_voice": "I checked twice, then just walked over",
            "note": "Synthetic fixture candidate",
            "source_ref": "fixture://interview/1",
            "collected_at": AT,
            "consent_ref": "consent-1",
        }
        payload.update(overrides)
        return payload

    # ------------------------------------------------------------ AN1-01..14
    def test_an1_01_plan_traces_chain_nodes_gaps_next_test(self):
        plan = self._build()
        self.assertEqual(plan["schema"], "askovo.evidence-capture-plan/1")
        self.assertEqual(plan["chain_id"], "PR01")
        self.assertEqual(plan["demand_judgment_id"], "D01")
        self.assertEqual(plan["context_key"], "synthetic-mobile-check")
        self.assertEqual(plan["study_ref"], "study.json")
        source = plan["source"]
        self.assertEqual(source["chain_ref"],
                         "04-findings/product-reasoning.json#chains/PR01")
        self.assertEqual(source["next_test"], self.chain["next_test"])
        self.assertEqual(source["gaps"], self.chain["gaps"])
        self.assertEqual(sorted(source["node_states"]),
                         ["business", "feature", "need", "pain", "product",
                          "scene", "user"])
        self.assertEqual(source["node_states"]["scene"]["status"],
                         self.chain["nodes"]["scene"]["status"])
        self.assertTrue(source["chain_hash"].startswith("sha256:"))
        self.assertEqual(plan["state"], "draft")
        self.assertEqual(plan["verdict_effect"], "none")

    def test_an1_02_interview_and_survey_share_the_same_objective(self):
        plan = self._build(objective="Test the privacy-rejection path")
        guide = capture_plan.render_interview_guide(plan)
        survey = capture_plan.render_survey_draft(plan)
        for rendered in (guide, survey):
            self.assertIn("Test the privacy-rejection path", rendered)
            self.assertIn(plan["research_question"], rendered)
        plan_md = capture_plan.render_plan_md(plan)
        self.assertIn("Test the privacy-rejection path", plan_md)

    def test_an1_03_alt_behaviour_consequence_and_counter_evidence_kept(self):
        plan = self._build()
        guide = capture_plan.render_interview_guide(plan)
        survey = capture_plan.render_survey_draft(plan)
        for rendered in (guide, survey):
            self.assertIn("alternative_behavior", rendered)
            self.assertIn("consequence", rendered)
            self.assertIn("counter_evidence", rendered)
        authorized = self._authorized()
        updated = capture_plan.import_candidates(
            authorized, [self._candidate()], at=AT)
        record = updated["candidates"][0]
        self.assertEqual(record["alternative_behavior"], "walked over to look")
        self.assertEqual(record["consequence"], "missed a delivery window")
        self.assertEqual(record["counter_evidence"],
                         ["one participant found the camera enough"])
        self.assertIn("walked over to look",
                      capture_plan.render_plan_md(updated))

    def test_an1_04_missing_stop_conditions_or_consent_blocks_authorization(self):
        plan = self._build(stop_conditions=[], consent={})
        plan = capture_plan.submit_for_review(plan, actor="Ana", at=AT)
        plan = capture_plan.record_review(
            plan, reviewer="Li Hua", decision="approve", at=AT)
        with self.assertRaises(capture_plan.CapturePlanError) as caught:
            capture_plan.authorize(plan, authorized_by="Ana", authorized_at=AT)
        self.assertEqual(caught.exception.reason_code, "AUTHORIZATION_BLOCKED")
        self.assertIn("stop_conditions", caught.exception.missing)
        self.assertIn("consent.boundary", caught.exception.missing)
        self.assertEqual(plan["state"], "needs_review")
        self.assertEqual(plan["authorization"]["status"], "none")

    def test_an1_05_trigger_change_after_authorization_requires_reauthorization(self):
        plan = self._authorized()
        old_scope = plan["authorization"]["scope_hash"]
        revised = capture_plan.revise_plan(
            plan, {"triggers": ["Any recording request", "Minor participant"]},
            actor="Ana", at=AT, note="tighten trigger")
        self.assertEqual(revised["authorization"]["status"], "superseded")
        self.assertEqual(revised["state"], "needs_review")
        self.assertTrue(revised["requires_reauthorization"])
        self.assertEqual(revised["plan_version"], "2")
        self.assertEqual(revised["authorization"]["scope_hash"], old_scope)
        self.assertNotEqual(capture_plan.scope_hash(revised), old_scope)
        with self.assertRaises(capture_plan.CapturePlanError) as caught:
            capture_plan.import_candidates(revised, [self._candidate()])
        self.assertEqual(caught.exception.reason_code, "AUTHORIZATION_REQUIRED")

    def test_an1_06_missing_behavior_ref_is_marked_behavior_unknown(self):
        authorized = self._authorized()
        updated = capture_plan.import_candidates(
            authorized, [self._candidate(behavior_ref="")], at=AT)
        record = updated["candidates"][0]
        self.assertEqual(record["behavior_ref"], "")
        self.assertTrue(record["behavior_unknown"])
        self.assertIn("behavior_unknown", capture_plan.render_plan_md(updated))

    def test_an1_07_candidates_never_carry_an_evidence_level(self):
        authorized = self._authorized()
        updated = capture_plan.import_candidates(
            authorized, [self._candidate()], at=AT)
        record = updated["candidates"][0]
        self.assertIsNone(record["evidence_level"])
        self.assertEqual(record["state"], "candidate")
        self.assertEqual(updated["verdict_effect"], "none")
        self.assertEqual(updated["effects"]["evidence"], "none")
        with self.assertRaises(capture_plan.CapturePlanError) as caught:
            capture_plan.import_candidates(
                authorized, [self._candidate(evidence_level="E3")], at=AT)
        self.assertEqual(caught.exception.reason_code,
                         "EVIDENCE_LEVEL_FORBIDDEN")

    def test_an1_08_context_missing_or_mismatched_candidates_are_rejected(self):
        authorized = self._authorized()
        with self.assertRaises(capture_plan.CapturePlanError) as caught:
            capture_plan.import_candidates(
                authorized, [self._candidate(context_key="")], at=AT)
        self.assertEqual(caught.exception.reason_code, "CONTEXT_MISSING")
        with self.assertRaises(capture_plan.CapturePlanError) as caught:
            capture_plan.import_candidates(
                authorized, [self._candidate(context_key="other-context")],
                at=AT)
        self.assertEqual(caught.exception.reason_code, "CONTEXT_MISMATCH")
        self.assertEqual(authorized["candidates"], [])

    def test_an1_09_duplicate_import_is_a_counted_no_op(self):
        authorized = self._authorized()
        first = capture_plan.import_candidates(
            authorized, [self._candidate()], at=AT)
        second = capture_plan.import_candidates(
            first, [self._candidate()], at=AT)
        self.assertEqual(len(second["candidates"]), 1)
        self.assertEqual(second["last_import"]["added"], 0)
        self.assertEqual(second["last_import"]["duplicates"], 1)
        third = capture_plan.import_candidates(
            second, [self._candidate(candidate_id="cand-explicit")], at=AT)
        self.assertEqual(len(third["candidates"]), 1)
        self.assertEqual(third["last_import"]["duplicates"], 1)

    def test_an1_10_named_review_is_retained_verbatim(self):
        plan = self._build()
        plan = capture_plan.submit_for_review(plan, actor="Ana", at=AT,
                                              note="ready")
        with self.assertRaises(capture_plan.CapturePlanError):
            capture_plan.record_review(
                plan, reviewer="  ", decision="approve", at=AT)
        plan = capture_plan.record_review(
            plan, reviewer="Li Hua", decision="approve", at=AT,
            note="scope and stops are adequate", ref="review-doc-1")
        review = plan["review"][0]
        self.assertEqual(review["reviewer"], "Li Hua")
        self.assertEqual(review["decision"], "approve")
        self.assertEqual(review["at"], AT)
        self.assertEqual(review["note"], "scope and stops are adequate")
        self.assertEqual(review["ref"], "review-doc-1")
        self.assertEqual(plan["change_log"][-1]["action"], "review_approve")
        authorized = capture_plan.authorize(
            plan, authorized_by="Ana", authorized_at=AT)
        self.assertEqual(authorized["state"], "authorized")

    def test_an1_11_positive_interviews_do_not_upgrade_the_verdict(self):
        authorized = self._authorized()
        candidates = [
            self._candidate(behavior_ref=f"observed: positive case {index}",
                            user_voice="it worked")
            for index in range(3)
        ]
        updated = capture_plan.import_candidates(
            authorized, candidates, at=AT)
        self.assertEqual(len(updated["candidates"]), 3)
        self.assertTrue(all(c["evidence_level"] is None
                            for c in updated["candidates"]))
        self.assertEqual(updated["verdict_effect"], "none")
        self.assertEqual(updated["effects"]["verdict"], "none")
        self.assertEqual(updated["state"], "candidates_ready")
        self.assertIn("不代表证据", capture_plan.render_plan_md(updated))

    def test_an1_12_counter_evidence_keeps_the_frozen_snapshot(self):
        before_bytes = (self.study / CANONICAL_REF).read_bytes()
        authorized = self._authorized()
        snapshot_hash = authorized["source"]["chain_hash"]
        next_test = authorized["source"]["next_test"]
        updated = capture_plan.record_counter_evidence(
            authorized,
            {"ref": "R05", "summary": "Privacy concern outweighed value",
             "source_ref": "02-data/evidence.jsonl#R05"},
            at=AT, note="contradicts pilot premise")
        self.assertEqual(updated["source"]["chain_hash"], snapshot_hash)
        self.assertEqual(updated["source"]["next_test"], next_test)
        self.assertEqual(len(updated["counter_evidence"]), 1)
        self.assertEqual(updated["counter_evidence"][0]["source_chain_hash"],
                         snapshot_hash)
        self.assertEqual(updated["verdict_effect"], "none")
        self.assertEqual((self.study / CANONICAL_REF).read_bytes(), before_bytes)

    def test_an1_13_withdrawn_authorization_stops_further_use(self):
        authorized = self._authorized()
        imported = capture_plan.import_candidates(
            authorized, [self._candidate()], at=AT)
        withdrawn = capture_plan.withdraw_authorization(
            imported, actor="Ana", reason="consent boundary changed", at=AT)
        self.assertEqual(withdrawn["state"], "cancelled")
        self.assertEqual(withdrawn["authorization"]["status"], "withdrawn")
        self.assertFalse(withdrawn["candidates"][0]["usable"])
        with self.assertRaises(capture_plan.CapturePlanError) as caught:
            capture_plan.import_candidates(
                withdrawn, [self._candidate(behavior_ref="other")], at=AT)
        self.assertEqual(caught.exception.reason_code,
                         "AUTHORIZATION_WITHDRAWN")

    def test_an1_14_external_text_is_escaped_not_executed(self):
        plan = self._build(
            objective='<script>alert("objective")</script> & more',
            stop_conditions=["<img src=x onerror=alert(1)>"])
        plan = capture_plan.submit_for_review(plan, actor="Ana", at=AT)
        plan = capture_plan.record_review(
            plan, reviewer="Li Hua", decision="approve", at=AT)
        plan = capture_plan.authorize(plan, authorized_by="Ana",
                                      authorized_at=AT)
        plan = capture_plan.import_candidates(plan, [self._candidate(
            note="<script>steal()</script>",
            user_voice="<b>not bold</b>")], at=AT)
        for rendered in (capture_plan.render_plan_md(plan),
                         capture_plan.render_interview_guide(plan),
                         capture_plan.render_survey_draft(plan)):
            self.assertNotIn("<script>", rendered)
            self.assertNotIn("<img", rendered)
            self.assertIn("&lt;script&gt;", rendered)
            self.assertIn("&amp; more", rendered)

    # ------------------------------------------------------------ XN2 samples
    def test_xn2_build_is_deterministic_and_idempotent(self):
        first = self._build()
        second = self._build()
        self.assertEqual(capture_plan.plan_hash(first),
                         capture_plan.plan_hash(second))
        out = self.tmp / "plans"
        created = capture_plan.store_plan(first, out)
        self.assertEqual(created["status"], "created")
        unchanged = capture_plan.store_plan(second, out)
        self.assertEqual(unchanged["status"], "unchanged")
        self.assertEqual(
            (out / "capture-plan.json").read_text(encoding="utf-8"),
            json.dumps(first, ensure_ascii=False, indent=2) + "\n")

    def test_xn2_same_version_different_content_is_a_conflict(self):
        plan = self._build()
        out = self.tmp / "plans"
        capture_plan.store_plan(plan, out)
        conflicting = self._build(objective="A different objective")
        with self.assertRaises(capture_plan.CapturePlanError) as caught:
            capture_plan.store_plan(conflicting, out)
        self.assertEqual(caught.exception.reason_code, "PLAN_VERSION_CONFLICT")
        bumped = self._build(objective="A different objective",
                             plan_version="2")
        self.assertEqual(capture_plan.store_plan(bumped, out)["status"],
                         "created")

    def test_xn2_write_plan_is_stable_and_complete(self):
        plan = self._build()
        first = capture_plan.write_plan(plan, self.tmp / "out")
        first_bytes = {name: Path(path).read_bytes()
                       for name, path in first.items()}
        second = capture_plan.write_plan(plan, self.tmp / "out")
        self.assertEqual(sorted(first), sorted(second))
        for name, path in second.items():
            self.assertEqual(Path(path).read_bytes(), first_bytes[name])
        template = capture_plan.candidate_template()
        rows = list(csv.DictReader(io.StringIO(template["csv"])))
        self.assertEqual(template["columns"], list(capture_plan.CANDIDATE_COLUMNS))
        self.assertEqual(rows, [])

    def test_xn2_candidate_csv_cells_are_injection_guarded(self):
        guarded = capture_plan._csv_cell("=cmd|' /C calc'!A0")
        self.assertEqual(guarded, "'=cmd|' /C calc'!A0")
        self.assertEqual(capture_plan._csv_cell("ordinary text"), "ordinary text")

    def test_cli_capture_plan_end_to_end(self):
        out = self.tmp / "cli-plan"
        built = run_cli(
            "capture", "plan", "build", str(self.study), "--chain", "PR01",
            "--out", str(out), "--objective", "Test the bounded pilot",
            "--stop", "Participant withdraws consent",
            "--consent-boundary", "Synthetic fixture only",
            "--participant-segment", "Synthetic households",
            "--participant-criteria", "Opted in",
            "--participant-count", "6",
            "--window-start", "2026-11-20", "--window-end", "2026-12-04",
            "--at", AT)
        self.assertEqual(built.returncode, 0, built.stderr + built.stdout)
        payload = json.loads(built.stdout)
        self.assertEqual(payload["status"], "built")
        self.assertEqual(payload["state"], "draft")
        plan_path = payload["path"]
        self.assertTrue(Path(plan_path).exists())
        for name in ("plan_md", "interview_guide", "survey_draft",
                     "candidate_csv", "candidate_json"):
            self.assertTrue(Path(payload["files"][name]).exists(), name)

        again = run_cli("capture", "plan", "build", str(self.study),
                        "--chain", "PR01", "--out", str(out),
                        "--objective", "Test the bounded pilot",
                        "--stop", "Participant withdraws consent",
                        "--consent-boundary", "Synthetic fixture only",
                        "--participant-segment", "Synthetic households",
                        "--participant-criteria", "Opted in",
                        "--participant-count", "6",
                        "--window-start", "2026-11-20",
                        "--window-end", "2026-12-04", "--at", AT)
        self.assertEqual(again.returncode, 0, again.stderr + again.stdout)
        self.assertEqual(json.loads(again.stdout)["status"], "unchanged")

        submit = run_cli("capture", "plan", "submit", plan_path,
                         "--actor", "Ana", "--at", AT)
        self.assertEqual(submit.returncode, 0, submit.stderr + submit.stdout)
        review = run_cli("capture", "plan", "review", plan_path,
                         "--reviewer", "Li Hua", "--decision", "approve",
                         "--note", "bounded", "--at", AT)
        self.assertEqual(review.returncode, 0, review.stderr + review.stdout)
        authorize = run_cli("capture", "plan", "authorize", plan_path,
                            "--by", "Ana", "--ref", "approval-1", "--at", AT)
        self.assertEqual(authorize.returncode, 0,
                         authorize.stderr + authorize.stdout)
        self.assertEqual(json.loads(authorize.stdout)["state"], "authorized")

        candidates_path = self.tmp / "candidates.json"
        candidates_path.write_text(json.dumps(
            [self._candidate()], ensure_ascii=False), encoding="utf-8")
        imported = run_cli("capture", "plan", "import", plan_path,
                           "--candidates", str(candidates_path), "--at", AT)
        self.assertEqual(imported.returncode, 0,
                         imported.stderr + imported.stdout)
        imported_payload = json.loads(imported.stdout)
        self.assertEqual(imported_payload["state"], "candidates_ready")
        self.assertEqual(imported_payload["added"], 1)
        stored = json.loads(Path(plan_path).read_text(encoding="utf-8"))
        self.assertIsNone(stored["candidates"][0]["evidence_level"])

        rendered = run_cli("capture", "plan", "render", plan_path,
                           "--out", str(self.tmp / "render-again"))
        self.assertEqual(rendered.returncode, 0,
                         rendered.stderr + rendered.stdout)
        self.assertTrue((self.tmp / "render-again" / "capture-plan.md").exists())

        shown = run_cli("capture", "plan", "show", plan_path)
        self.assertEqual(shown.returncode, 0, shown.stderr + shown.stdout)
        self.assertEqual(json.loads(shown.stdout)["plan"]["plan_id"],
                         payload["plan_id"])


if __name__ == "__main__":
    unittest.main()
