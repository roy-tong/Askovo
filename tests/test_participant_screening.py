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
SCRIPTS = ROOT / "skills/askovo/scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import capture_plan  # noqa: E402
import participant_screening  # noqa: E402


class ParticipantScreeningTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="askovo-screening-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.study = self.tmp / "study"
        shutil.copytree(ROOT / "examples/sample-study", self.study)
        self.plan = capture_plan.build_plan(
            self.study, "PR01", objective="Interview target users",
            methods=["interview"],
            target_participants={"segment": "Product managers", "criteria": "Own a current product decision", "count": 2},
            consent={"boundary": "Synthetic local screening", "recording": "none",
                     "withdrawal": "withdraw at any time", "data_handling": "local only"},
            stop_conditions=["Withdrawn consent"], triggers=[], window={"start": "2026-11-24", "end": "2026-11-30"},
            at="2026-11-24T00:00:00Z")

    def review(self, **changes):
        row = {"participant_ref": "participant-1", "source_ref": "local-candidate-1",
               "eligible": True, "evidence_refs": ["screening-note-1"],
               "consent_state": "accepted", "reason": "Owns the decision and consented"}
        row.update(changes)
        return row

    def test_eligibility_and_consent_have_separate_readiness(self):
        got = participant_screening.build(self.plan, [
            self.review(),
            self.review(participant_ref="participant-2", consent_state="pending"),
            self.review(participant_ref="participant-3", consent_state="declined"),
        ], reviewed_by="research-owner", reviewed_at="2026-11-25T00:00:00Z")
        self.assertEqual(3, got["summary"]["reviewed"])
        self.assertEqual(3, got["summary"]["eligible"])
        self.assertEqual(1, got["summary"]["research_ready"])
        self.assertEqual(1, got["summary"]["pending_consent"])
        self.assertEqual(1, got["summary"]["not_ready_declined"])
        self.assertFalse(got["recruitment_executed"])
        self.assertEqual("PR01", got["chain_id"])

    def test_eligible_participant_needs_evidence(self):
        with self.assertRaisesRegex(ValueError, "evidence_refs"):
            participant_screening.build(self.plan, [self.review(evidence_refs=[])],
                                        reviewed_by="research-owner")

    def test_withdrawn_participant_is_not_research_ready(self):
        got = participant_screening.build(self.plan, [self.review(consent_state="withdrawn")],
                                          reviewed_by="research-owner")
        self.assertFalse(got["participants"][0]["research_ready"])
        self.assertEqual(1, got["summary"]["not_ready_withdrawn"])

    def test_conflicting_duplicate_participant_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "conflict"):
            participant_screening.build(self.plan, [self.review(), self.review(eligible=False)],
                                        reviewed_by="research-owner")

    def test_cli_writes_roster_without_mutating_plan(self):
        plan_path = capture_plan.store_plan(self.plan, self.tmp / "stored")["path"]
        before = Path(plan_path).read_bytes()
        reviews = self.tmp / "reviews.json"
        reviews.write_text(json.dumps([self.review()]), encoding="utf-8")
        out = self.tmp / "roster.json"
        result = subprocess.run([
            sys.executable, str(CLI), "capture", "plan", "screen", "--plan", plan_path,
            "--file", str(reviews), "--by", "research-owner", "--out", str(out),
        ], text=True, capture_output=True)
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        self.assertEqual(1, json.loads(out.read_text())["summary"]["research_ready"])
        self.assertEqual(before, Path(plan_path).read_bytes())
        second = subprocess.run([
            sys.executable, str(CLI), "capture", "plan", "screen", "--plan", plan_path,
            "--file", str(reviews), "--by", "research-owner", "--out", str(out),
        ], text=True, capture_output=True)
        self.assertNotEqual(0, second.returncode)
    def test_cli_issues_private_invitations_without_distribution(self):
        plan_path = capture_plan.store_plan(self.plan, self.tmp / "stored")["path"]
        roster = self.tmp / "roster.json"
        roster.write_text(json.dumps(participant_screening.build(
            self.plan, [self.review()], reviewed_by="research-owner")), encoding="utf-8")
        before = Path(plan_path).read_bytes()
        out = self.tmp / "invitations.json"
        result = subprocess.run([
            sys.executable, str(CLI), "capture", "plan", "invitations", "--plan", plan_path,
            "--file", str(roster), "--experiment-id", "landing-demo", "--out", str(out),
        ], text=True, capture_output=True)
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        payload = json.loads(out.read_text())
        self.assertEqual(1, len(payload["invitations"]))
        self.assertEqual(0, payload["external_actions"])
        self.assertEqual(before, Path(plan_path).read_bytes())


if __name__ == "__main__":
    unittest.main()
