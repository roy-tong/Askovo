from __future__ import annotations

import copy
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

AT = "2026-11-19T09:00:00+00:00"


class ExperimentExportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="askovo-experiment-export-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.study = self.tmp / "study"
        shutil.copytree(SAMPLE, self.study)
        self.plan = capture_plan.build_plan(
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

    def design(self) -> dict:
        return {
            "hypothesis": {
                "statement": "Users can complete the safety check without assistance.",
                "falsification_condition": "Most eligible participants cannot complete the task unaided.",
            },
            "design": {
                "experiment_type": "single_arm",
                "unit_of_analysis": "participant",
                "population": "Synthetic opted-in mobile-check households",
                "assignment": "none",
                "arms": [{
                    "arm_id": "concept",
                    "role": "treatment",
                    "description": "Current safety-check prototype",
                    "planned_sample_size": 6,
                }],
                "primary_metrics": [{
                    "metric_id": "unaided_completion",
                    "definition": "Participant completes the safety check without assistance.",
                    "unit": "boolean",
                    "direction": "increase",
                }],
                "comparability": {
                    "same_task_set": True,
                    "same_acceptance_rubric": True,
                    "same_budget": True,
                    "controlled_variables": ["Prototype version", "Task instructions"],
                    "known_differences": [],
                },
            },
            "external_actions": False,
            "registered_by": "Ana",
            "registered_at": "2026-11-19T08:00:00Z",
        }

    def test_export_binds_capture_plan_and_design(self) -> None:
        got = experiment_export.from_capture_plan(self.plan, self.design(), "2.24.0")
        self.assertEqual("ovo.experiment-contract/1", got["schema"])
        self.assertEqual("askovo", got["origin_product"])
        self.assertEqual("2.24.0", got["origin_version"])
        self.assertEqual(self.plan["plan_id"], got["experiment_id"])
        self.assertEqual("registered", got["state"])
        self.assertEqual([], got["observations"])
        self.assertEqual("not_evaluated", got["outcome"]["status"])
        self.assertEqual(got["design_sha256"],
                         experiment_export.design_hash(got))

    def test_missing_hypothesis_is_an_explicit_gap(self) -> None:
        spec = self.design()
        spec.pop("hypothesis")
        with self.assertRaises(experiment_export.ExperimentExportError) as caught:
            experiment_export.from_capture_plan(self.plan, spec, "2.24.0")
        self.assertEqual("DESIGN_REQUIRED", caught.exception.reason_code)

    def test_external_research_needs_current_authorization(self) -> None:
        spec = self.design()
        spec["external_actions"] = True
        with self.assertRaises(experiment_export.ExperimentExportError) as caught:
            experiment_export.from_capture_plan(self.plan, spec, "2.24.0")
        self.assertEqual("AUTHORIZATION_REQUIRED", caught.exception.reason_code)

    def test_unreviewed_candidate_cannot_support_outcome(self) -> None:
        plan = capture_plan.submit_for_review(self.plan, actor="Ana", at=AT)
        plan = capture_plan.record_review(
            plan, reviewer="Li Hua", decision="approve", at=AT)
        plan = capture_plan.authorize(
            plan, authorized_by="Ana", authorized_at=AT,
            authorization_ref="approval-1")
        plan = capture_plan.start_collection(plan, actor="Ana", at="2026-11-20T08:00:00Z")
        plan = capture_plan.import_candidates(plan, [{
            "context_key": self.plan["context_key"],
            "behavior_ref": "observed: completed the check",
            "alternative_behavior": "asked for help",
            "consequence": "completed independently",
            "counter_evidence": "",
            "user_voice": "I finished it without help",
            "note": "Synthetic candidate",
            "source_ref": "fixture://observation/1",
            "collected_at": "2026-11-21T09:00:00Z",
            "consent_ref": "consent-1",
            "participant_ref": "participant-1",
        }], at="2026-11-21T09:00:00Z")
        spec = self.design()
        candidate_id = plan["candidates"][0]["candidate_id"]
        spec["observation_bindings"] = {
            candidate_id: {"arm_id": "concept", "metric_id": "unaided_completion"}
        }
        spec["outcome"] = {
            "status": "supports_hypothesis",
            "causality": "descriptive_association",
            "evidence_refs": [candidate_id],
            "evaluated_by": "Ana",
            "evaluated_at": "2026-11-21T10:00:00Z",
            "notes": "Attempted premature conclusion",
        }
        with self.assertRaises(experiment_export.ExperimentExportError) as caught:
            experiment_export.from_capture_plan(plan, spec, "2.24.0")
        self.assertEqual("EVIDENCE_NOT_ELIGIBLE", caught.exception.reason_code)
        spec.pop("outcome")
        got = experiment_export.from_capture_plan(plan, spec, "2.24.0")
        self.assertFalse(got["observations"][0]["eligible"])
        self.assertEqual("reported", got["observations"][0]["evidence_grade"])

    def test_cli_writes_new_shared_contract(self) -> None:
        stored = capture_plan.store_plan(self.plan, self.tmp / "plan")
        spec_path = self.tmp / "design.json"
        spec_path.write_text(json.dumps(self.design()), encoding="utf-8")
        out = self.tmp / "experiment.json"
        result = subprocess.run([
            sys.executable, str(CLI), "capture", "plan", "export-experiment",
            "--plan", stored["path"], "--design", str(spec_path),
            "--out", str(out),
        ], text=True, capture_output=True)
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        payload = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual("ovo.experiment-contract/1", payload["schema"])
        second = subprocess.run([
            sys.executable, str(CLI), "capture", "plan", "export-experiment",
            "--plan", stored["path"], "--design", str(spec_path),
            "--out", str(out),
        ], text=True, capture_output=True)
        self.assertEqual(1, second.returncode)


if __name__ == "__main__":
    unittest.main()
