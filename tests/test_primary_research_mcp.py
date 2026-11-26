from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from skills.askovo.scripts import askovo_mcp, capture_plan


class PrimaryResearchMcpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def survey_spec(self):
        return {
            "schema": "askovo.survey-experiment/1", "survey_id": "mcp-survey",
            "title": "MCP survey", "context_key": "mcp-context",
            "consent_notice": "local test", "registered_by": "owner",
            "registered_at": "2026-11-24T00:00:00Z", "max_responses": 2,
            "questions": [{"question_id": "q1", "text": "What happened?",
                           "kind": "text", "required": True}],
        }

    def test_tool_manifest_exposes_local_research_but_not_serve_or_human_review(self):
        tool = next(row for row in askovo_mcp.TOOLS
                    if row["name"] == "askovo_primary_research")
        actions = tool["inputSchema"]["properties"]["action"]["enum"]
        self.assertIn("survey_create", actions)
        self.assertIn("landing_export", actions)
        self.assertIn("landing_deploy", actions)
        self.assertIn("screening_invitations", actions)
        self.assertFalse(any("serve" in action for action in actions))
        self.assertNotIn("askovo_primary_review", {row["name"] for row in askovo_mcp.TOOLS})

    def test_mcp_survey_create_status_and_candidate_export(self):
        spec = self.root / "survey.json"
        spec.write_text(json.dumps(self.survey_spec()), encoding="utf-8")
        directory = self.root / "survey-run"
        created = askovo_mcp._run_tool("askovo_primary_research", {
            "action": "survey_create", "spec": str(spec), "out": str(directory),
        })
        self.assertEqual(0, created["exit_code"], created)
        status = askovo_mcp._run_tool("askovo_primary_research", {
            "action": "survey_status", "dir": str(directory),
        })
        self.assertEqual(0, status["result"]["responses"])
        out = self.root / "candidates.json"
        exported = askovo_mcp._run_tool("askovo_primary_research", {
            "action": "survey_export_candidates", "dir": str(directory), "out": str(out),
        })
        self.assertEqual(0, exported["exit_code"], exported)
        self.assertEqual([], json.loads(out.read_text(encoding="utf-8")))

    def test_mcp_landing_create_and_shared_export(self):
        spec = self.root / "landing.json"
        spec.write_text(json.dumps({
            "schema": "askovo.landing-experiment/1", "experiment_id": "mcp-landing",
            "hypothesis": {"statement": "B beats A", "falsification_condition": "B does not beat A"},
            "registered_by": "owner", "registered_at": "2026-11-24T00:00:00Z",
            "conversion_definition": "registration", "consent_notice": "local test",
            "max_exposures": 2,
            "population": "local fixture", "planned_sample_per_arm": 1,
            "window": {"start": "2020-01-01T00:00:00Z", "end": "2030-01-01T00:00:00Z"},
            "comparability": {"same_task_set": True, "same_acceptance_rubric": True,
                              "same_budget": False, "controlled_variables": [],
                              "known_differences": ["budget unknown"]},
            "variants": [
                {"arm_id": "control", "role": "control", "title": "A", "body": "A", "cta_label": "Go"},
                {"arm_id": "treatment", "role": "treatment", "title": "B", "body": "B", "cta_label": "Go"},
            ],
        }), encoding="utf-8")
        directory = self.root / "landing-run"
        created = askovo_mcp._run_tool("askovo_primary_research", {
            "action": "landing_create", "spec": str(spec), "out": str(directory),
        })
        self.assertEqual(0, created["exit_code"], created)
        design = self.root / "design.json"
        design.write_text(json.dumps({
            "population": "local fixture", "planned_sample_per_arm": 1,
            "window": {"start": "2020-01-01T00:00:00Z", "end": "2030-01-01T00:00:00Z"},
            "comparability": {"same_task_set": True, "same_acceptance_rubric": True,
                              "same_budget": False, "controlled_variables": [],
                              "known_differences": ["budget unknown"]},
        }), encoding="utf-8")
        out = self.root / "experiment.json"
        exported = askovo_mcp._run_tool("askovo_primary_research", {
            "action": "landing_export", "dir": str(directory),
            "design": str(design), "out": str(out),
        })
        self.assertEqual(0, exported["exit_code"], exported)
        self.assertEqual("ovo.experiment-contract/1",
                         json.loads(out.read_text(encoding="utf-8"))["schema"])

    def test_mcp_prototype_create_import_status_and_export(self):
        spec = self.root / "prototype.json"
        spec.write_text(json.dumps({
            "schema": "askovo.prototype-experiment/1", "experiment_id": "mcp-prototype",
            "hypothesis": {"statement": "Users complete the task", "falsification_condition": "They cannot"},
            "registered_by": "owner", "registered_at": "2026-11-24T00:00:00Z",
            "population": "local fixture", "planned_sample_per_arm": 1, "max_participants": 2,
            "window": {"start": "2026-11-24T00:00:00Z", "end": "2026-11-30T00:00:00Z"},
            "comparability": {"same_task_set": True, "same_acceptance_rubric": True,
                              "same_budget": True, "controlled_variables": [], "known_differences": []},
            "consent_notice": "local test",
            "tasks": [{"task_id": "task-1", "instruction": "Complete it", "success_criteria": "Saved correctly"}],
        }), encoding="utf-8")
        directory = self.root / "prototype-run"
        created = askovo_mcp._run_tool("askovo_primary_research", {
            "action": "prototype_create", "spec": str(spec), "out": str(directory),
        })
        self.assertEqual(0, created["exit_code"], created)
        observations = self.root / "prototype-observations.jsonl"
        observations.write_text(json.dumps({
            "observation_id": "obs-1", "participant_ref": "p1", "task_id": "task-1",
            "observed_at": "2026-11-25T10:00:00Z", "success": True,
            "duration_seconds": 30, "assistance_required": False, "error_count": 0,
            "source_ref": "local:obs-1", "consent_ref": "consent-1", "observed_by": "observer",
        }) + "\n", encoding="utf-8")
        imported = askovo_mcp._run_tool("askovo_primary_research", {
            "action": "prototype_import", "dir": str(directory),
            "file": str(observations), "by": "owner",
        })
        self.assertEqual(0, imported["exit_code"], imported)
        status = askovo_mcp._run_tool("askovo_primary_research", {
            "action": "prototype_status", "dir": str(directory),
        })
        self.assertEqual(1, status["result"]["totals"]["observations"])
        out = self.root / "prototype-experiment.json"
        exported = askovo_mcp._run_tool("askovo_primary_research", {
            "action": "prototype_export", "dir": str(directory), "out": str(out),
        })
        self.assertEqual(0, exported["exit_code"], exported)
        self.assertEqual("ovo.experiment-contract/1", json.loads(out.read_text())["schema"])

    def test_mcp_participant_screening_export(self):
        study = self.root / "study"
        shutil.copytree(Path(__file__).resolve().parents[1] / "examples/sample-study", study)
        plan = capture_plan.build_plan(
            study, "PR01", objective="Interview users", methods=["interview"],
            target_participants={"segment": "PM", "criteria": "Own a decision", "count": 1},
            consent={"boundary": "local test", "recording": "none",
                     "withdrawal": "any time", "data_handling": "local"},
            stop_conditions=["withdraw"], triggers=[],
            window={"start": "2026-11-24", "end": "2026-11-30"}, at="2026-11-24T00:00:00Z")
        stored = capture_plan.store_plan(plan, self.root / "plan")["path"]
        review = self.root / "screening.json"
        review.write_text(json.dumps([{
            "participant_ref": "p1", "source_ref": "local-1", "eligible": True,
            "evidence_refs": ["note-1"], "consent_state": "accepted", "reason": "Qualified",
        }]), encoding="utf-8")
        out = self.root / "roster.json"
        result = askovo_mcp._run_tool("askovo_primary_research", {
            "action": "screening_export", "plan": stored, "file": str(review),
            "by": "owner", "out": str(out),
        })
        self.assertEqual(0, result["exit_code"], result)
        self.assertEqual(1, json.loads(out.read_text())["summary"]["research_ready"])

    def test_skill_contains_primary_research_paths(self):
        text = (Path(__file__).resolve().parents[1] /
                "skills/askovo/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("experiment survey", text)
        self.assertIn("experiment landing", text)
        self.assertIn("experiment prototype", text)
        self.assertIn("capture plan screen", text)
        self.assertIn("review-candidate", text)


if __name__ == "__main__":
    unittest.main()
