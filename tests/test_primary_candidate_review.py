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

import capture_plan  # noqa: E402
import experiment_export  # noqa: E402
import primary_candidate_review  # noqa: E402

AT = "2026-11-19T09:00:00+00:00"


class PrimaryCandidateReviewTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="askovo-primary-review-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.study = self.tmp / "study"
        shutil.copytree(SAMPLE, self.study)
        plan = capture_plan.build_plan(
            self.study, "PR01",
            objective="Test whether users complete the safety check unaided",
            methods=["task_observation"],
            target_participants={
                "segment": "Synthetic mobile-check households",
                "criteria": "Opted in, experienced a blind-spot check",
                "count": 6,
            },
            consent={
                "boundary": "Synthetic fixture: no real participants",
                "recording": "none",
                "withdrawal": "stop at any time",
                "data_handling": "local only",
            },
            stop_conditions=["Participant withdraws consent"],
            triggers=["Any real recording request"],
            window={"start": "2026-11-20", "end": "2026-12-04"},
            at=AT,
        )
        plan = capture_plan.submit_for_review(plan, actor="Ana", at=AT)
        plan = capture_plan.record_review(
            plan, reviewer="Li Hua", decision="approve", at=AT)
        plan = capture_plan.authorize(
            plan, authorized_by="Ana", authorized_at=AT,
            authorization_ref="approval-1")
        stored = capture_plan.store_plan(
            plan, self.study / "04-findings/capture-plans" / plan["plan_id"])
        self.plan_path = Path(stored["path"])
        plan = capture_plan.start_collection(
            plan, actor="Ana", at="2026-11-20T08:00:00Z")
        plan = capture_plan.import_candidates(plan, [{
            "candidate_id": "candidate-1",
            "context_key": plan["context_key"],
            "behavior_ref": "observed: participant completed the full safety check without assistance",
            "alternative_behavior": "asked another person for help",
            "consequence": "completed the intended task independently",
            "counter_evidence": "",
            "user_voice": "I completed the whole safety check without needing any help",
            "note": "Synthetic primary research candidate",
            "source_ref": "fixture://primary-research/1",
            "collected_at": "2026-11-21T09:00:00Z",
            "consent_ref": "consent-1",
            "participant_ref": "participant-1",
        }], at="2026-11-21T09:00:00Z")
        capture_plan.save_plan(plan, self.plan_path)
        self.plan = plan
        self.candidate_id = "candidate-1"

    def evidence(self):
        path = self.study / "02-data/evidence.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()]

    def review(self, **overrides):
        inputs = {
            "by": "Li Hua", "decision": "accept", "observation": "statement",
            "reason": "Checked the exact participant statement against the notes",
            "at": "2026-11-22T09:00:00Z",
        }
        inputs.update(overrides)
        return primary_candidate_review.review_candidate(
            self.plan_path, self.candidate_id, **inputs)

    def test_accept_writes_reviewed_evidence_without_authoring_judgment(self):
        before = (self.study / "04-findings/demand-judgments.json").read_bytes()
        result = self.review()
        self.assertEqual("accepted", result["status"])
        records = [row for row in self.evidence()
                   if row.get("source_family") == "primary_research"]
        self.assertEqual(1, len(records))
        record = records[0]
        self.assertEqual("E1", record["evidence_level"])
        self.assertEqual("Li Hua", record["reviewed_by"])
        self.assertEqual("consent-1", record["consent_ref"])
        self.assertEqual(self.plan["authorization"]["scope_hash"],
                         record["primary_authorization_scope_hash"])
        updated = capture_plan.load_plan(self.plan_path)
        self.assertEqual("accepted", updated["candidates"][0]["state"])
        self.assertEqual(before, (self.study / "04-findings/demand-judgments.json").read_bytes())

    def test_reject_never_writes_evidence(self):
        before = len(self.evidence())
        result = self.review(decision="reject", reason="Insufficient source context")
        self.assertEqual("rejected", result["status"])
        self.assertEqual(before, len(self.evidence()))
        updated = capture_plan.load_plan(self.plan_path)
        self.assertEqual("rejected", updated["candidates"][0]["state"])
        self.assertFalse(updated["candidates"][0]["usable"])

    def test_repeat_accept_is_idempotent(self):
        first = self.review()
        count = len(self.evidence())
        second = self.review()
        self.assertFalse(first["already_accepted"])
        self.assertTrue(second["already_accepted"])
        self.assertEqual(count, len(self.evidence()))

    def test_changed_candidate_cannot_be_accepted(self):
        self.plan["candidates"][0]["user_voice"] = "Changed after import"
        capture_plan.save_plan(self.plan, self.plan_path)
        with self.assertRaises(primary_candidate_review.PrimaryReviewError) as caught:
            self.review()
        self.assertEqual("CANDIDATE_CHANGED", caught.exception.reason_code)

    def test_accepted_practice_becomes_eligible_experiment_observation(self):
        self.review(observation="practice")
        records = self.evidence()
        spec = {
            "hypothesis": {
                "statement": "Users can complete the safety check without assistance.",
                "falsification_condition": "Eligible participants cannot complete the task unaided.",
            },
            "design": {
                "experiment_type": "single_arm",
                "unit_of_analysis": "participant",
                "population": "Synthetic opted-in mobile-check households",
                "assignment": "none",
                "arms": [{"arm_id": "concept", "role": "treatment",
                          "description": "Current prototype", "planned_sample_size": 6}],
                "primary_metrics": [{"metric_id": "unaided_completion",
                                     "definition": "Observed unaided task completion.",
                                     "unit": "boolean", "direction": "increase"}],
                "comparability": {
                    "same_task_set": True, "same_acceptance_rubric": True,
                    "same_budget": True, "controlled_variables": ["Prototype"],
                    "known_differences": [],
                },
            },
            "external_actions": True,
            "registered_by": "Ana",
            "registered_at": "2026-11-19T08:00:00Z",
            "observation_bindings": {
                "candidate-1": {"arm_id": "concept", "metric_id": "unaided_completion",
                                "value_number": 1},
            },
            "outcome": {
                "status": "supports_hypothesis", "causality": "descriptive_association",
                "evidence_refs": ["candidate-1"], "evaluated_by": "Ana",
                "evaluated_at": "2026-11-22T10:00:00Z", "notes": "Single-case descriptive result.",
            },
        }
        got = experiment_export.from_capture_plan(
            capture_plan.load_plan(self.plan_path), spec, "2.24.0",
            evidence_records=records, study_dir=self.study)
        observation = got["observations"][0]
        self.assertTrue(observation["eligible"])
        self.assertEqual("observed", observation["evidence_grade"])
        self.assertEqual("supports_hypothesis", got["outcome"]["status"])

    def test_cli_reject_uses_same_review_path(self):
        result = subprocess.run([
            sys.executable, str(CLI), "capture", "plan", "review-candidate",
            "--plan", str(self.plan_path), "--candidate", self.candidate_id,
            "--decision", "reject", "--by", "Li Hua", "--reason", "Not eligible",
            "--at", "2026-11-22T09:00:00Z",
        ], text=True, capture_output=True)
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        updated = capture_plan.load_plan(self.plan_path)
        self.assertEqual("rejected", updated["candidates"][0]["state"])


if __name__ == "__main__":
    unittest.main()
