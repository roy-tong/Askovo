#!/usr/bin/env python3
"""A-04 Decision Brief + PRD acceptance projection (AC A19-A23).

Frozen acceptance tests for `askovo brief` and `askovo decide brief`. The brief
is a **read-only projection** of the canonical seven-node chain and
`decision_review`; it never edits them, never invents a probability, and never
lets a numeric fact through without its unit, window and source. A broken
reference or a drifted input marks the brief `stale`, which blocks formal
delivery and leaves only a diagnostic draft.

Everything runs offline on the synthetic sample study.
"""
from __future__ import annotations

import hashlib
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

SCHEMA = "askovo.decision-brief/1"
SECTIONS = (
    "question",
    "recommendation",
    "options",
    "evidence",
    "counter_evidence",
    "limitations",
    "rejected_options",
    "verification_actions",
    "prd_acceptance",
    "states",
)
CONTRACT_FIELDS = (
    "schema",
    "task_id",
    "study_id",
    "decision_status",
    "recommended_option_id",
    "options",
    "limitations",
    "verification_actions",
    "approval",
    "source_fingerprint",
    "generated_at",
    "canonical_ref",
)
DIMENSIONS = ("user", "task", "opportunity", "cost", "risk")


def run_cli(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    merged = dict(os.environ)
    merged.setdefault("ASKOVO_AUTHOR_SALT", "a-04-frozen-test-salt")
    if env:
        merged.update(env)
    return subprocess.run([sys.executable, str(CLI), *args],
                          capture_output=True, text=True, timeout=120, env=merged)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


class BriefHelpers:
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.study = self.dir / "study"
        shutil.copytree(SAMPLE, self.study)
        # The synthetic sample ships counter-evidence; a clean baseline keeps the
        # "challenged" assertion meaningful.
        self._edit_reasoning(self._drop_counter_evidence)

    # -- fixture plumbing -------------------------------------------------- #

    def reasoning_path(self) -> Path:
        return self.study / "04-findings" / "product-reasoning.json"

    def judgments_path(self) -> Path:
        return self.study / "04-findings" / "demand-judgments.json"

    def evidence_path(self) -> Path:
        return self.study / "02-data" / "evidence.jsonl"

    def reasoning(self) -> dict:
        return json.loads(self.reasoning_path().read_text(encoding="utf-8"))

    def _write_reasoning(self, payload: dict) -> None:
        self.reasoning_path().write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _edit_reasoning(self, mutate) -> None:
        payload = self.reasoning()
        mutate(payload)
        self._write_reasoning(payload)

    @staticmethod
    def _drop_counter_evidence(payload: dict) -> None:
        for chain in payload.get("chains") or []:
            chain["counter_evidence_ids"] = []

    def brief(self, *extra: str) -> tuple[subprocess.CompletedProcess, dict]:
        completed = run_cli("brief", str(self.study), *extra)
        try:
            return completed, json.loads(completed.stdout)
        except json.JSONDecodeError:
            return completed, {"raw": completed.stdout, "stderr": completed.stderr}

    def chain(self) -> dict:
        return (self.reasoning().get("chains") or [])[0]

    def markdown_path(self) -> Path:
        return self.study / "06-report" / "decision-brief.md"


class BriefContractTests(BriefHelpers, unittest.TestCase):

    def test_brief_carries_the_nine_sections(self) -> None:
        completed, document = self.brief()
        self.assertEqual(0, completed.returncode, document)
        for section in SECTIONS:
            self.assertIn(section, document, f"brief missing §2.3 section {section}")

    def test_brief_matches_the_prd_contract(self) -> None:
        _, document = self.brief()
        for field in CONTRACT_FIELDS:
            self.assertIn(field, document, f"contract field missing: {field}")
        self.assertEqual(SCHEMA, document["schema"])
        self.assertEqual("04-findings/product-reasoning.json", document["canonical_ref"])
        self.assertTrue(str(document["source_fingerprint"]).startswith("sha256:"))
        self.assertTrue(document["generated_at"])

    def test_options_are_two_to_five_with_uniform_dimensions(self) -> None:
        _, document = self.brief()
        options = document["options"]
        self.assertGreaterEqual(len(options), 2)
        self.assertLessEqual(len(options), 5)
        for option in options:
            self.assertEqual(set(DIMENSIONS), set(option["dimensions"]))
            self.assertEqual("chain_level", option["dimensions_basis"])
            self.assertTrue(option["id"])

    def test_option_ids_are_stable_and_unique(self) -> None:
        _, first = self.brief()
        _, second = self.brief()
        ids = [option["id"] for option in first["options"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids, [option["id"] for option in second["options"]])

    def test_four_states_are_independent(self) -> None:
        _, document = self.brief()
        states = document["states"]
        for key in ("decision_state", "delivery_state", "outcome_state", "causality_state"):
            self.assertIn(key, states)
        self.assertEqual("not_approved", states["decision_state"])
        self.assertEqual("not_claimed", states["causality_state"])
        self.assertNotEqual(states["decision_state"], states["outcome_state"])

    def test_limitations_cover_sample_and_commercial_gaps(self) -> None:
        _, document = self.brief()
        blob = json.dumps(document["limitations"], ensure_ascii=False)
        for marker in ("样本", "总体", "商业行为"):
            self.assertIn(marker, blob, f"limitations missing {marker}")

    def test_brief_is_read_only(self) -> None:
        targets = [self.reasoning_path(), self.judgments_path(), self.evidence_path()]
        before = [digest(path) for path in targets]
        completed, document = self.brief()
        self.assertEqual(0, completed.returncode, document)
        self.assertEqual(before, [digest(path) for path in targets],
                         "the brief must not rewrite canonical artifacts")

    def test_markdown_and_json_are_one_document(self) -> None:
        completed, document = self.brief("--format", "md")
        self.assertEqual(0, completed.returncode, document["raw"] if "raw" in document else document)
        markdown = self.markdown_path().read_text(encoding="utf-8")
        for heading in ("## 1.", "## 2.", "## 3.", "## 4.", "## 5.", "## 6.",
                        "## 7.", "## 8.", "## 9."):
            self.assertIn(heading, markdown, f"markdown missing {heading}")
        self.assertIn("recommendation", markdown)
        self.assertTrue((self.study / "06-report" / "decision-brief.json").is_file())


class BriefHoldTests(BriefHelpers, unittest.TestCase):
    """A19: no evidence still yields a Hold action, never a validated decision."""

    def setUp(self) -> None:
        super().setUp()
        # Keep the chain shape but strip every citation: nothing supports it.
        def strip(payload: dict) -> None:
            for chain in payload.get("chains") or []:
                chain["status"] = "hypothesis"
                chain["counter_evidence_ids"] = []
                for node in (chain.get("nodes") or {}).values():
                    node["status"] = "hypothesis"
                    node["evidence_ids"] = []

        self._edit_reasoning(strip)

    def test_no_evidence_still_holds_without_validating(self) -> None:
        completed, document = self.brief()
        self.assertEqual(0, completed.returncode, document)
        self.assertEqual("hold", document["recommendation"]["kind"])
        self.assertIsNone(document["recommended_option_id"])
        for option in document["options"]:
            self.assertNotEqual("recommended", option["status"])

    def test_hold_still_names_an_action_and_never_approves(self) -> None:
        _, document = self.brief()
        self.assertEqual("hold", document["decision_status"])
        self.assertTrue(document["verification_actions"],
                        "a hold without a next action is not acceptable")
        self.assertTrue(all(action.get("action") for action in document["verification_actions"]))
        self.assertFalse(document["approval"]["approved"])
        self.assertIsNone(document["approval"]["approved_by"])
        self.assertTrue(document["recommendation"]["not_approved"])


class BriefPrdAcceptanceTests(BriefHelpers, unittest.TestCase):
    """A20: node acceptance items match the PRD fields and stay traceable."""

    def test_checklist_uses_the_canonical_prd_fields(self) -> None:
        _, document = self.brief()
        checklist = document["prd_acceptance"]["checklist"]
        self.assertTrue(checklist)
        fields = {item["source_field"] for item in checklist}
        self.assertEqual({"acceptance_conditions", "acceptance_criteria"}, fields)
        chain = self.chain()
        expected = set(chain["nodes"]["feature"]["acceptance_conditions"]) | set(
            chain["nodes"]["product"]["acceptance_criteria"])
        self.assertEqual(expected, {item["statement"] for item in checklist})

    def test_checklist_items_are_traceable(self) -> None:
        _, document = self.brief()
        chain_id = self.chain()["id"]
        for item in document["prd_acceptance"]["checklist"]:
            self.assertIn(f"#chains/{chain_id}/nodes/", item["source_ref"])
            self.assertIn(item["source_node"], ("feature", "product"))
            self.assertIsInstance(item["evidence_ids"], list)
            self.assertEqual("unknown", item["implementation_status"],
                             "a research checklist item is never implementation-approved")

    def test_empty_checklist_is_undefined_not_done(self) -> None:
        def clear(payload: dict) -> None:
            node = payload["chains"][0]["nodes"]["feature"]
            node["acceptance_conditions"] = []
            payload["chains"][0]["nodes"]["product"]["acceptance_criteria"] = []

        self._edit_reasoning(clear)
        _, document = self.brief()
        self.assertEqual([], document["prd_acceptance"]["checklist"])
        self.assertTrue(document["prd_acceptance"]["undefined"])
        self.assertIn("尚未定义", document["prd_acceptance"]["note"])

    def test_non_goals_and_linked_issues_are_carried(self) -> None:
        _, document = self.brief()
        acceptance = document["prd_acceptance"]
        self.assertIn("Always-on autonomous patrol", acceptance["non_goals"])
        self.assertIsInstance(acceptance["linked_issues"], list)


class BriefChallengeTests(BriefHelpers, unittest.TestCase):
    """A21: a challenged decision is marked for re-review, never auto-overwritten."""

    def test_counter_evidence_marks_needs_re_review(self) -> None:
        def challenge(payload: dict) -> None:
            payload["chains"][0]["counter_evidence_ids"] = ["R05", "R07"]

        self._edit_reasoning(challenge)
        _, document = self.brief()
        self.assertTrue(document["needs_re_review"])
        self.assertEqual("needs_review", document["decision_status"])
        self.assertIsNotNone(document["challenge"])
        self.assertEqual(["R05", "R07"], document["challenge"]["counter_evidence_ids"])
        self.assertTrue(document["challenge"]["why"])
        self.assertTrue(document["counter_evidence"],
                        "a challenged brief must show the counter-evidence, not just count it")

    def test_clean_decision_is_not_challenged(self) -> None:
        _, document = self.brief()
        self.assertFalse(document["needs_re_review"])
        self.assertNotEqual("needs_review", document["decision_status"])
        self.assertEqual([], document["counter_evidence"])

    def test_challenge_keeps_the_previous_recommendation(self) -> None:
        def challenge(payload: dict) -> None:
            payload["chains"][0]["counter_evidence_ids"] = ["R05"]

        self._edit_reasoning(challenge)
        _, document = self.brief()
        self.assertTrue(document["challenge"]["previous_recommendation"],
                        "a re-review must show what it is challenging")
        self.assertIn("needs_re_review", json.dumps(document))


class BriefNumberTests(BriefHelpers, unittest.TestCase):
    """A22: every number keeps its unit, window and source."""

    @staticmethod
    def _estimate(**overrides) -> dict:
        estimate = {
            "metric": "paid pilot reservations",
            "population_definition": "Eligible remote owners invited to the pilot",
            "time_window": "2026-01-01..2026-12-31",
            "unit": "reservations",
            "method": "counted from the pilot signup export",
            "formula": "count(reservations)",
            "assumptions": ["Signup is not payment"],
            "value": 120,
            "source_ref": "R04",
            "status": "observed",
        }
        estimate.update(overrides)
        return estimate

    def _set_estimates(self, *estimates: dict) -> None:
        self._edit_reasoning(
            lambda payload: payload["chains"][0]["nodes"]["business"].__setitem__(
                "market_estimates", list(estimates)))

    def test_numbers_carry_unit_window_and_source(self) -> None:
        self._set_estimates(self._estimate())
        _, document = self.brief()
        entry = [item for item in document["numbers"]
                 if item["metric"] == "paid pilot reservations"][0]
        self.assertEqual(120, entry["value"])
        self.assertEqual("reservations", entry["unit"])
        self.assertEqual("2026-01-01..2026-12-31", entry["time_window"])
        self.assertEqual("R04", entry["source_ref"])
        self.assertEqual([], document["fabrication"]["numbers_without_provenance"])

    def test_number_without_unit_is_withheld(self) -> None:
        self._set_estimates(self._estimate(unit=""))
        _, document = self.brief()
        entry = [item for item in document["numbers"]
                 if item["metric"] == "paid pilot reservations"][0]
        self.assertIsNone(entry["value"], "a number without its unit must not be emitted")
        self.assertTrue(entry["unavailable_reason"])
        self.assertIn("paid pilot reservations",
                      document["fabrication"]["numbers_without_provenance"])

    def test_number_without_source_is_withheld(self) -> None:
        self._set_estimates(self._estimate(source_ref=""))
        _, document = self.brief()
        entry = [item for item in document["numbers"]
                 if item["metric"] == "paid pilot reservations"][0]
        self.assertIsNone(entry["value"])
        self.assertTrue(entry["unavailable_reason"])

    def test_unknown_numbers_stay_null_not_zero(self) -> None:
        _, document = self.brief()
        for entry in document["numbers"]:
            if entry["value"] is None:
                self.assertTrue(entry["unavailable_reason"],
                                "null must be explained, never silently read as 0")


class BriefFabricationTests(BriefHelpers, unittest.TestCase):
    """A23: no invented interviews or conversion rates."""

    def test_no_invented_interviews_or_rates(self) -> None:
        _, document = self.brief()
        facts = document["research_facts"]
        self.assertIsNone(facts["interviews_conducted"])
        self.assertIsNone(facts["conversion_rate"])
        self.assertEqual([], document["fabrication"]["invented_facts"])
        self.assertGreater(document["fabrication"]["checked_numbers"], 0)

    def test_markdown_never_claims_conducted_interviews(self) -> None:
        self.brief("--format", "md")
        markdown = self.markdown_path().read_text(encoding="utf-8")
        for pattern in ("共访谈", "访谈了", "已完成访谈", "转化率为", "转化率是"):
            self.assertNotIn(pattern, markdown, f"fabricated research fact: {pattern}")

    def test_heuristic_score_is_never_a_probability(self) -> None:
        _, document = self.brief()
        recommendation = document["recommendation"]
        self.assertFalse(recommendation["calibrated"])
        if recommendation.get("heuristic_score") is not None:
            self.assertIsInstance(recommendation["heuristic_score"], (int, float))
            self.assertLessEqual(recommendation["heuristic_score"], 1.0)
            self.assertGreaterEqual(recommendation["heuristic_score"], 0.0)
        self.assertNotIsInstance(recommendation.get("confidence"), (int, float),
                                 "confidence must not become a fabricated probability")


class BriefStaleTests(BriefHelpers, unittest.TestCase):
    """The stale gate blocks formal delivery and keeps a diagnostic draft."""

    def test_broken_reference_marks_stale(self) -> None:
        def break_ref(payload: dict) -> None:
            payload["chains"][0]["nodes"]["scene"]["evidence_ids"] = ["R404-missing"]

        self._edit_reasoning(break_ref)
        completed, document = self.brief()
        self.assertEqual(1, completed.returncode, document)
        self.assertEqual("stale", document["artifact_status"])
        self.assertEqual("STALE_SOURCE", document["reason_code"])
        self.assertTrue(document["diagnostic_only"])
        self.assertEqual("blocked", document["states"]["delivery_state"])
        self.assertTrue(document["stale_reasons"])
        self.assertEqual("BROKEN_REFERENCE", document["stale_reasons"][0]["detail_code"])
        self.assertNotIn("code", document["stale_reasons"][0],
                         "the contract vocabulary belongs on `reason_code`, not on a detail")

    def test_stale_brief_names_the_next_action(self) -> None:
        def break_ref(payload: dict) -> None:
            payload["chains"][0]["counter_evidence_ids"] = ["R404-missing"]

        self._edit_reasoning(break_ref)
        completed, document = self.brief()
        self.assertEqual(1, completed.returncode, document)
        self.assertTrue(document["next_required_action"])
        self.assertIn("review", document["next_required_action"])

    def test_clean_brief_is_partial_not_stale(self) -> None:
        completed, document = self.brief()
        self.assertEqual(0, completed.returncode, document)
        self.assertEqual("partial", document["artifact_status"])
        self.assertEqual("ARTIFACT_PARTIAL", document["reason_code"])
        self.assertFalse(document["diagnostic_only"])
        self.assertEqual([], document["stale_reasons"])

    def test_stale_still_renders_a_diagnostic_draft(self) -> None:
        def break_ref(payload: dict) -> None:
            payload["chains"][0]["nodes"]["scene"]["evidence_ids"] = ["R404-missing"]

        self._edit_reasoning(break_ref)
        self.brief("--format", "md")
        markdown = self.markdown_path().read_text(encoding="utf-8")
        self.assertIn("诊断草稿", markdown)
        self.assertIn("stale", markdown)


class BriefDriftTests(BriefHelpers, unittest.TestCase):
    """D4: a same-id content change is input drift, not a fresh brief."""

    def _rewrite_first_record(self, text_value: str) -> None:
        rows = [json.loads(line) for line in
                self.evidence_path().read_text(encoding="utf-8").splitlines() if line.strip()]
        rows[0]["text"] = text_value
        self.evidence_path().write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
            encoding="utf-8")

    def test_same_id_content_change_is_input_drift(self) -> None:
        reviewed = run_cli("review", str(self.study), "--json")
        # `askovo review` exits 1 when audit items fail (a valid research status);
        # what matters here is that it recorded the fingerprints.
        self.assertIn(reviewed.returncode, (0, 1), reviewed.stdout + reviewed.stderr)
        self.assertTrue(
            ((json.loads((self.study / "05-audit" / "decision-review.json")
                          .read_text(encoding="utf-8")).get("input_fingerprints") or {})
             .get("evidence")),
            "the review must record evidence fingerprints")
        self._rewrite_first_record("TAMPERED: the record now says the opposite.")
        completed, document = self.brief()
        self.assertEqual(1, completed.returncode, document)
        self.assertEqual("stale", document["artifact_status"])
        self.assertEqual("STALE_SOURCE", document["reason_code"])
        self.assertEqual("blocked", document["delivery_state"])
        self.assertTrue(document["diagnostic_only"])
        codes = {reason["detail_code"] for reason in document["stale_reasons"]}
        self.assertIn("INPUT_DRIFT", codes,
                      f"a same-id content change must be INPUT_DRIFT, got {codes}")
        # C-01 §3: the top-level code is the registry one; INPUT_DRIFT is a detail.
        self.assertEqual("STALE_SOURCE", document["reason_code"])
        self.assertTrue(document["input_drift"],
                        "the same-id-content-change distinction must stay visible")

    def test_unreferenced_new_evidence_is_not_drift(self) -> None:
        reviewed = run_cli("review", str(self.study), "--json")
        self.assertIn(reviewed.returncode, (0, 1), reviewed.stdout + reviewed.stderr)
        with self.evidence_path().open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "record_id": "R99", "context_key": "synthetic-mobile-check",
                "user_role": "unreferenced", "scene_trigger": "unknown",
                "task_outcome": "unknown", "current_substitute": "unknown",
                "friction_cost": "unknown", "consequence": "unknown",
                "evidence_level": "E1", "evidence_basis": "added after review; not cited",
                "corpus_role": "open_scene", "source_family": "interview",
                "source_ref": "synthetic-unreferenced", "normalized_text_hash": "sha256:x",
                "text": "An unreferenced record.", "claim_type": "need",
                "evidence_form": "self_report",
            }, ensure_ascii=False) + "\n")
        completed, document = self.brief()
        self.assertEqual(0, completed.returncode, document)
        self.assertEqual("partial", document["artifact_status"],
                         "adding an uncited record is not drift")


class BriefFreeTextNumberTests(BriefHelpers, unittest.TestCase):
    """D5: free text copied into the brief is scanned for unprovenanced numbers."""

    def test_free_text_numbers_are_redacted_and_recorded(self) -> None:
        def inject(payload: dict) -> None:
            business = payload["chains"][0]["nodes"]["business"]
            business["cost_drivers"] = ["Monthly infrastructure burn is $50,000 with 37% margin"]
            business["non_goals"] = ["Reach 1,200 paying accounts in year one"]
            business["statement"] = "Run a $50,000 paid pilot before any launch decision"
            payload["chains"][0]["nodes"]["product"]["rationale"] = (
                "A $50,000 pilot proves willingness to pay at 37% margin")

        self._edit_reasoning(inject)
        _, document = self.brief()
        rendered = json.dumps(document["options"], ensure_ascii=False)
        for token in ("$50,000", "37%", "1,200"):
            self.assertNotIn(token, rendered,
                             f"{token} must not be copied without provenance")
        self.assertNotIn("$50,000", json.dumps(document["recommendation"], ensure_ascii=False))
        findings = document["fabrication"]["unverified_numbers"]
        self.assertTrue(findings, "every redacted field must be recorded")
        fields = {item["field"] for item in findings}
        self.assertTrue({"business.cost_drivers", "business.non_goals",
                         "business.statement"} <= fields,
                        f"unexpected fields: {sorted(fields)}")
        for item in findings:
            self.assertTrue(item["numbers"])
            self.assertTrue(item["excerpt"])


class BriefDecideIntegrationTests(BriefHelpers, unittest.TestCase):
    """A-02's `decide brief` now returns the A-04 document, not a stub."""

    def test_decide_brief_uses_the_same_builder(self) -> None:
        workspace = self.dir / "decide-workspace"
        task_path = self.dir / "task.json"
        task = {
            "schema": "askovo.decision-task/1",
            "question": "下一版该先修哪些问题？",
            "product": {"kind": "github_repository", "repo": "owner/repo"},
            "decision_type": "prioritize_features",
            "audience": {"description": "开发者", "confidence": "declared"},
            "source_scope": {"issues": True, "discussions": False, "updated_since": "2026-08-01"},
            "authorization": {"approved_by": "owner", "allowed_sources": ["github"],
                              "max_records": 200},
            "deadline": "2026-12-01",
            "delivery": {"primary": "decision_brief", "secondary": []},
        }
        task_path.write_text(json.dumps(task, ensure_ascii=False), encoding="utf-8")
        started = run_cli("decide", "start", "--workspace", str(workspace),
                          "--input", str(task_path), "--study", str(self.study))
        self.assertEqual(0, started.returncode, started.stdout + started.stderr)
        task_id = json.loads(started.stdout)["task_id"]
        completed = run_cli("decide", "brief", task_id, "--workspace", str(workspace),
                            "--format", "json")
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        document = json.loads(completed.stdout)
        self.assertEqual(SCHEMA, document["schema"])
        for field in ("artifact_status", "reason_code", "gaps", "decision_state",
                      "boundary", "canonical_refs"):
            self.assertIn(field, document, f"A-02 field missing: {field}")
        self.assertIn("product-reasoning.json", json.dumps(document["canonical_refs"]))


if __name__ == "__main__":
    unittest.main()
