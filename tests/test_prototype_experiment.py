from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/askovo/scripts/askovo.py"
SCRIPTS = ROOT / "skills/askovo/scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import prototype_experiment  # noqa: E402


class PrototypeExperimentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "prototype"

    def spec(self, maximum=5):
        return {
            "schema": "askovo.prototype-experiment/1", "experiment_id": "prototype-demo",
            "hypothesis": {"statement": "Target users complete the safety check unaided.",
                           "falsification_condition": "Most observed participants cannot complete it unaided."},
            "registered_by": "research-owner", "registered_at": "2026-11-24T00:00:00Z",
            "population": "Synthetic opted-in target users", "planned_sample_per_arm": 3,
            "window": {"start": "2026-11-24T00:00:00Z", "end": "2026-11-30T00:00:00Z"},
            "comparability": {"same_task_set": True, "same_acceptance_rubric": True,
                              "same_budget": True, "controlled_variables": ["Prototype"], "known_differences": []},
            "consent_notice": "Synthetic local observation only", "max_participants": maximum,
            "tasks": [{"task_id": "complete-check", "instruction": "Complete the safety check",
                       "success_criteria": "The correct check is saved without assistance"}],
        }

    def observation(self, **changes):
        row = {
            "observation_id": "obs-1", "participant_ref": "participant-1",
            "task_id": "complete-check", "attempt": 1,
            "observed_at": "2026-11-25T10:00:00Z", "success": True,
            "duration_seconds": 42.5, "assistance_required": False, "error_count": 0,
            "source_ref": "local-observation:obs-1", "consent_ref": "consent-1",
            "observed_by": "named-observer",
        }
        row.update(changes)
        return row

    def test_observations_are_deduplicated_and_aggregated_by_task(self):
        prototype_experiment.create(self.spec(), self.root)
        first = prototype_experiment.import_observations(
            self.root, [self.observation()], imported_by="research-owner")
        second = prototype_experiment.import_observations(
            self.root, [self.observation()], imported_by="research-owner")
        self.assertEqual(1, first["added"])
        self.assertEqual(1, second["duplicates"])
        report = prototype_experiment.status(self.root)
        task = report["tasks"][0]
        self.assertEqual(1, task["participants"])
        self.assertEqual(1, task["successes"])
        self.assertEqual(1, task["success_rate"])
        self.assertEqual(42.5, task["median_duration_seconds"])
        self.assertEqual(0, task["assistance_required"])
        self.assertEqual("descriptive_only", report["causal_status"])

    def test_consent_window_and_registered_task_are_enforced(self):
        prototype_experiment.create(self.spec(), self.root)
        for changes in ({"consent_ref": ""}, {"observed_at": "2026-12-01T00:00:00Z"},
                        {"task_id": "unregistered"}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    prototype_experiment.import_observations(
                        self.root, [self.observation(**changes)], imported_by="research-owner")
        self.assertEqual(0, prototype_experiment.status(self.root)["totals"]["observations"])

    def test_participant_limit_is_enforced(self):
        prototype_experiment.create(self.spec(maximum=1), self.root)
        prototype_experiment.import_observations(
            self.root, [self.observation()], imported_by="research-owner")
        with self.assertRaisesRegex(ValueError, "participant limit"):
            prototype_experiment.import_observations(
                self.root, [self.observation(observation_id="obs-2", participant_ref="participant-2")],
                imported_by="research-owner")

    def test_registered_spec_drift_is_rejected(self):
        prototype_experiment.create(self.spec(), self.root)
        path = self.root / prototype_experiment.SPEC_NAME
        changed = json.loads(path.read_text(encoding="utf-8"))
        changed["population"] = "Post-hoc population"
        path.write_text(json.dumps(changed), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "fingerprint mismatch"):
            prototype_experiment.status(self.root)

    def test_shared_export_preserves_task_outcome_boundary(self):
        prototype_experiment.create(self.spec(), self.root)
        prototype_experiment.import_observations(
            self.root, [self.observation()], imported_by="research-owner")
        document = prototype_experiment.export_experiment(self.root, "2.24.0")
        self.assertEqual("ovo.experiment-contract/1", document["schema"])
        self.assertEqual("single_arm", document["design"]["experiment_type"])
        self.assertEqual("none", document["design"]["assignment"])
        self.assertEqual("inconclusive", document["outcome"]["status"])
        self.assertEqual("descriptive_association", document["outcome"]["causality"])
        self.assertEqual(1, len(document["observations"]))
        self.assertNotIn("participant-1", json.dumps(document))
        self.assertEqual(document["design_sha256"], prototype_experiment.shared_design_hash(document))

    def test_mvp_behavior_separates_first_value_and_registered_repeat_window(self):
        spec = self.spec()
        spec["validation_mode"] = "mvp_behavior"
        spec["repeat_window_hours"] = 24
        prototype_experiment.create(spec, self.root)
        rows = [
            self.observation(observation_id="p1-first", participant_ref="p1", observed_at="2026-11-25T10:00:00Z"),
            self.observation(observation_id="p1-repeat", participant_ref="p1", attempt=2,
                             observed_at="2026-11-26T11:00:00Z"),
            self.observation(observation_id="p2-first", participant_ref="p2", observed_at="2026-11-25T10:00:00Z"),
            self.observation(observation_id="p3-failed", participant_ref="p3", success=False),
        ]
        prototype_experiment.import_observations(self.root, rows, imported_by="research-owner")
        report = prototype_experiment.status(self.root)
        self.assertEqual(3, report["mvp"]["participants"])
        self.assertEqual(2, report["mvp"]["activated_participants"])
        self.assertEqual(1, report["mvp"]["retained_participants"])
        self.assertEqual(0.5, report["mvp"]["retention_rate_among_activated"])
        document = prototype_experiment.export_experiment(self.root, "2.24.0")
        metric_ids = {row["metric_id"] for row in document["observations"]}
        self.assertIn("activation_rate", metric_ids)
        self.assertIn("retention_rate", metric_ids)
        self.assertNotIn('"p1"', json.dumps(document))

    def test_repeat_before_registered_window_does_not_count_as_retention(self):
        spec = self.spec()
        spec["validation_mode"] = "mvp_behavior"
        spec["repeat_window_hours"] = 24
        prototype_experiment.create(spec, self.root)
        prototype_experiment.import_observations(self.root, [
            self.observation(observation_id="p1-first", observed_at="2026-11-25T10:00:00Z"),
            self.observation(observation_id="p1-too-early", attempt=2,
                             observed_at="2026-11-25T11:00:00Z"),
        ], imported_by="research-owner")
        report = prototype_experiment.status(self.root)
        self.assertEqual(1, report["mvp"]["activated_participants"])
        self.assertEqual(0, report["mvp"]["retained_participants"])
        self.assertEqual(0, report["mvp"]["retention_rate_among_activated"])

    def test_mvp_without_observations_keeps_rates_unknown(self):
        spec = self.spec()
        spec["validation_mode"] = "mvp_behavior"
        spec["repeat_window_hours"] = 24
        prototype_experiment.create(spec, self.root)
        report = prototype_experiment.status(self.root)
        self.assertIsNone(report["mvp"]["activation_rate"])
        self.assertIsNone(report["mvp"]["retention_rate_among_activated"])

    def test_cli_create_import_status_and_export(self):
        spec = Path(self.tmp.name) / "prototype.json"
        observations = Path(self.tmp.name) / "observations.jsonl"
        out = Path(self.tmp.name) / "experiment.json"
        spec.write_text(json.dumps(self.spec()), encoding="utf-8")
        observations.write_text(json.dumps(self.observation()) + "\n", encoding="utf-8")
        commands = [
            ["create", "--spec", str(spec), "--out", str(self.root)],
            ["import", "--dir", str(self.root), "--file", str(observations), "--by", "research-owner"],
            ["status", "--dir", str(self.root)],
            ["export", "--dir", str(self.root), "--out", str(out)],
        ]
        for action in commands:
            result = subprocess.run([
                sys.executable, str(CLI), "experiment", "prototype", action[0], *action[1:],
            ], text=True, capture_output=True)
            self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        self.assertEqual("ovo.experiment-contract/1", json.loads(out.read_text())["schema"])


if __name__ == "__main__":
    unittest.main()
