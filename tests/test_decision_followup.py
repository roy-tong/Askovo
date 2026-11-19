#!/usr/bin/env python3
"""A-NEXT-2 decision -> delivery -> outcome receipt (PRD acceptance AN2-01..14).

A follow-up is an append-only, local record that keeps four states apart:
what was chosen, what was delivered, what was observed, and whether causality
is claimed. Nothing here promotes a chain status, writes a canonical artifact,
sends a notification, or turns a delivered artifact into an observed outcome.

Every fixture is a temporary copy of the synthetic sample study. No network,
no real delivery, no real notification.
"""
from __future__ import annotations

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

import decision_followup  # noqa: E402
import decision_review  # noqa: E402

CANONICAL_REF = "04-findings/product-reasoning.json"
AT = "2026-11-19T09:00:00+00:00"
AT2 = "2026-11-20T09:00:00+00:00"


def run_cli(*args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run([sys.executable, str(CLI), *args],
                          check=False, capture_output=True, text=True,
                          timeout=120, env=env)


class DecisionFollowupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="askovo-decision-followup-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.study = self.tmp / "study"
        shutil.copytree(SAMPLE, self.study)
        self.reasoning_path = self.study / CANONICAL_REF

    # ------------------------------------------------------------------ helpers
    def _record(self, **overrides):
        inputs = {
            "chain_id": "PR01",
            "by": "pm",
            "decision": "proceed with narrow pilot",
        }
        inputs.update(overrides)
        result = decision_review.record_decision(self.study, **inputs)
        return result["record"]

    def _bytes(self) -> bytes:
        return self.reasoning_path.read_bytes()

    def _chain_status(self) -> str:
        reasoning = json.loads(self.reasoning_path.read_text(encoding="utf-8"))
        for chain in reasoning["chains"]:
            if chain.get("id") == "PR01":
                return chain.get("status", "")
        raise AssertionError("chain PR01 missing")

    def _append(self, **overrides):
        inputs = {
            "decision_id": "DR-PR01-001",
            "choice_state": "accepted",
            "owner_ref": "pm",
            "source_ref": "note:kickoff",
            "at": AT,
        }
        inputs.update(overrides)
        return decision_followup.append_followup(self.study, **inputs)

    def _receipt(self, **overrides):
        inputs = {"at": AT}
        inputs.update(overrides)
        return decision_followup.build_receipt(self.study, "DR-PR01-001", **inputs)

    def _lines(self) -> int:
        path = decision_followup.followups_path(self.study)
        if not path.is_file():
            return 0
        return len([line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()])

    def _delivery_file(self, name: str = "send-receipt.json") -> str:
        target = self.study / "05-audit" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('{"channel": "email", "message_id": "fixture-1", "sent": false}\n',
                          encoding="utf-8")
        return "05-audit/" + name

    @staticmethod
    def _event(**overrides):
        event = {
            "subject_ref": "person:fixture-1",
            "event": "pilot_signup",
            "occurred_at": "2026-11-21T10:00:00+00:00",
            "source_ref": "05-audit/pilot-signup.json",
            "observation_window": {"start": "2026-11-19T00:00:00+00:00",
                                   "end": "2026-11-30T00:00:00+00:00"},
        }
        event.update(overrides)
        return event

    @staticmethod
    def _codes(container) -> list:
        codes = []
        for item in container or []:
            if isinstance(item, dict):
                codes.extend(item.get("problems") or [])
                if item.get("code"):
                    codes.append(item["code"])
        return codes

    # ---------------------------------------------------------------- AN2-01
    def test_an2_01_accepted_and_shipped_stay_separate_from_decision_snapshot(self):
        self._record()
        before = self._bytes()
        ref = self._delivery_file()
        result = self._append(choice_state="accepted", delivery_state="shipped",
                              delivery_refs=[ref])
        self.assertEqual(result["status"], "recorded")
        self.assertFalse(result["canonical_write"])
        self.assertEqual(self._bytes(), before)
        receipt = self._receipt()
        self.assertEqual(receipt["states"]["choice"], "accepted")
        self.assertEqual(receipt["states"]["delivery"], "shipped")
        self.assertEqual(receipt["states"]["outcome"], "unknown")
        self.assertEqual(receipt["snapshot_state"], "matches")
        snapshot = receipt["decision_snapshot"]
        self.assertEqual(snapshot["record_id"], "DR-PR01-001")
        self.assertEqual(snapshot["decision"], "proceed with narrow pilot")
        self.assertEqual(snapshot["chain_fingerprint"], receipt["decision_snapshot_hash"])
        self.assertEqual(receipt["delivery"]["evidence_state"], "OK")

    # ---------------------------------------------------------------- AN2-02
    def test_an2_02_rejected_and_deferred_keep_reason_and_owner_visible(self):
        self._record()
        rejected = self._append(choice_state="rejected", owner_ref="research-lead",
                                source_ref="note:2026-11-19-review",
                                note="pilot would expose user homes without a shutter")
        self.assertEqual(rejected["status"], "recorded")
        deferred = self._append(choice_state="deferred", owner_ref="pm",
                                source_ref="note:2026-11-19-review",
                                note="wait for privacy test result", at=AT2)
        self.assertEqual(deferred["status"], "recorded")
        receipt = self._receipt()
        self.assertEqual(receipt["states"]["choice"], "deferred")
        self.assertEqual(receipt["choice"]["owner_ref"], "pm")
        self.assertEqual(receipt["choice"]["reason"], "wait for privacy test result")
        timeline = receipt["timeline"]
        self.assertEqual([item["choice_state"] for item in timeline], ["rejected", "deferred"])
        self.assertEqual(timeline[0]["owner_ref"], "research-lead")
        self.assertIn("shutter", timeline[0]["note"])

    def test_an2_02b_rejected_without_note_is_rejected(self):
        self._record()
        with self.assertRaises(ValueError):
            self._append(choice_state="rejected", note="")
        self.assertEqual(self._lines(), 0)

    # ---------------------------------------------------------------- AN2-03
    def test_an2_03_shipped_delivery_never_promotes_chain_status(self):
        reasoning = json.loads(self.reasoning_path.read_text(encoding="utf-8"))
        for chain in reasoning["chains"]:
            if chain.get("id") == "PR01":
                chain["status"] = "needs-validation"
        self.reasoning_path.write_text(json.dumps(reasoning, ensure_ascii=False, indent=2) + "\n",
                                       encoding="utf-8")
        record = self._record()
        self.assertEqual(record["decision_state"]["chain_status"], "needs-validation")
        ref = self._delivery_file()
        self._append(delivery_state="shipped", delivery_refs=[ref])
        self.assertEqual(self._chain_status(), "needs-validation")
        receipt = self._receipt()
        self.assertEqual(receipt["decision_snapshot"]["decision_state"]["chain_status"],
                         "needs-validation")
        self.assertEqual(receipt["states"]["delivery"], "shipped")
        self.assertEqual(receipt["verification_effect"], "none")

    # ---------------------------------------------------------------- AN2-04
    def test_an2_04_observed_outcome_does_not_claim_causality(self):
        self._record()
        self._append(outcome_state="observed", outcome_events=[self._event()])
        receipt = self._receipt()
        self.assertEqual(receipt["states"]["outcome"], "observed")
        self.assertEqual(receipt["states"]["causality"], "not_claimed")
        self.assertEqual(len(receipt["outcome"]["events"]), 1)
        self.assertEqual(receipt["outcome"]["gaps"], [])
        self.assertIn("never establish", receipt["causality"]["note"])

    # ---------------------------------------------------------------- AN2-05
    def test_an2_05_incomplete_event_stays_out_of_formal_outcome(self):
        self._record()
        incomplete = {
            "subject_ref": "person:fixture-1",
            "event": "pilot_signup",
            "occurred_at": "2026-11-21T10:00:00+00:00",
        }
        result = self._append(outcome_state="observed", outcome_events=[incomplete])
        self.assertEqual(result["record"]["outcome_state"], "unknown")
        self.assertEqual(result["record"]["outcome_events"], [])
        codes = self._codes(result["record"]["outcome_gaps"])
        self.assertIn("OUTCOME_WINDOW_REQUIRED", codes)
        self.assertIn("OUTCOME_SOURCE_REQUIRED", codes)
        diagnostic_codes = [item["code"] for item in result["diagnostics"]]
        self.assertIn("OUTCOME_WITHOUT_EVENTS", diagnostic_codes)
        receipt = self._receipt()
        self.assertEqual(receipt["states"]["outcome"], "unknown")
        self.assertEqual(receipt["outcome"]["events"], [])
        self.assertTrue(receipt["outcome"]["gaps"])

    # ---------------------------------------------------------------- AN2-06
    def test_an2_06_duplicate_event_import_is_a_noop(self):
        self._record()
        self._append(choice_state="accepted")
        first = decision_followup.import_outcome_events(
            self.study, decision_id="DR-PR01-001", events=[self._event()], at=AT2)
        self.assertEqual(first["status"], "recorded")
        self.assertEqual(first["added_events"], 1)
        lines = self._lines()
        second = decision_followup.import_outcome_events(
            self.study, decision_id="DR-PR01-001", events=[self._event()],
            at="2026-11-21T09:00:00+00:00")
        self.assertEqual(second["status"], "unchanged")
        self.assertEqual(second["added_events"], 0)
        self.assertEqual(second["duplicate_events"], 1)
        self.assertEqual(self._lines(), lines)
        receipt = self._receipt()
        self.assertEqual(len(receipt["outcome"]["events"]), 1)

    # ---------------------------------------------------------------- AN2-07
    def test_an2_07_cross_product_run_id_without_binding_is_not_admitted(self):
        self._record()
        event = self._event(source_family="growovo", run_id="run-2026-11-21-001")
        result = self._append(outcome_state="observed", outcome_events=[event])
        self.assertEqual(result["record"]["outcome_state"], "unknown")
        self.assertEqual(result["record"]["outcome_events"], [])
        codes = self._codes(result["record"]["outcome_gaps"])
        self.assertIn("CROSS_PRODUCT_UNBOUND", codes)
        receipt = self._receipt()
        self.assertTrue(receipt["outcome"]["unbound"])
        self.assertEqual(receipt["outcome"]["events"], [])

    def test_an2_07b_bound_cross_product_event_is_admitted(self):
        self._record()
        event = self._event(source_family="growovo", run_id="run-2026-11-21-001",
                            binding_ref="growovo:run:run-2026-11-21-001",
                            binding_decision_id="DR-PR01-001")
        result = self._append(outcome_state="observed", outcome_events=[event])
        self.assertEqual(result["record"]["outcome_state"], "observed")
        self.assertEqual(len(result["record"]["outcome_events"]), 1)
        receipt = self._receipt()
        self.assertEqual(receipt["outcome"]["events"][0]["binding_state"], "bound")

    # ---------------------------------------------------------------- AN2-08
    def test_an2_08_growovo_send_receipt_is_delivery_evidence_only(self):
        self._record()
        before = self._bytes()
        ref = self._delivery_file("growovo-send-receipt.json")
        result = self._append(delivery_state="shipped", delivery_refs=[ref],
                              note="Growovo run receipt attached; no outcome claimed")
        self.assertEqual(result["record"]["delivery_evidence_state"], "OK")
        self.assertEqual(self._bytes(), before)
        self.assertEqual(self._chain_status(), "decided")
        receipt = self._receipt()
        self.assertEqual(receipt["delivery"]["refs"][0]["ref"], ref)
        self.assertEqual(receipt["states"]["outcome"], "unknown")
        self.assertEqual(receipt["states"]["causality"], "not_claimed")

    # ---------------------------------------------------------------- AN2-09
    def test_an2_09_chain_change_after_decision_marks_followup_stale(self):
        self._record()
        first = self._append(choice_state="accepted")
        self.assertEqual(first["record"]["snapshot_state"], "matches")
        first_line = decision_followup.followups_path(self.study).read_text(
            encoding="utf-8").splitlines()[0]
        reasoning = json.loads(self.reasoning_path.read_text(encoding="utf-8"))
        reasoning["chains"][0]["title"] = "Revised chain title after the decision"
        self.reasoning_path.write_text(json.dumps(reasoning, ensure_ascii=False, indent=2) + "\n",
                                       encoding="utf-8")
        second = self._append(choice_state="accepted", note="re-check after chain edit", at=AT2)
        self.assertEqual(second["record"]["snapshot_state"], "stale")
        second_codes = [item["code"] for item in second["diagnostics"]]
        self.assertIn("SNAPSHOT_HASH_MISMATCH", second_codes)
        self.assertNotEqual(second["record"]["current_chain_fingerprint"],
                            second["record"]["decision_snapshot_hash"])
        lines = decision_followup.followups_path(self.study).read_text(
            encoding="utf-8").splitlines()
        self.assertEqual(lines[0], first_line)
        receipt = self._receipt()
        self.assertEqual(receipt["snapshot_state"], "stale")
        self.assertIn("SNAPSHOT_HASH_MISMATCH", [item["code"] for item in receipt["diagnostics"]])

    # ---------------------------------------------------------------- AN2-10
    def test_an2_10_new_followup_never_rewrites_old_lines(self):
        self._record()
        self._append(choice_state="accepted")
        path = decision_followup.followups_path(self.study)
        first_bytes = path.read_bytes()
        self._append(choice_state="accepted", delivery_state="shipped",
                     delivery_refs=[self._delivery_file()], at=AT2)
        self.assertTrue(path.read_bytes().startswith(first_bytes))
        self.assertEqual(self._lines(), 2)

    # ---------------------------------------------------------------- AN2-11
    def test_an2_11_notification_defaults_to_local_only(self):
        self._record()
        result = self._append()
        notification = result["record"]["notification"]
        self.assertEqual(notification["state"], "local_todo_only")
        self.assertFalse(notification["authorized"])
        self.assertEqual(notification["outbound"], "none")
        authorized = self._append(notification_authorized=True, note="asked to notify",
                                  at=AT2)
        self.assertFalse(authorized["record"]["notification"]["authorized"])
        self.assertIn("NOTIFICATION_REF_REQUIRED",
                      [item["code"] for item in authorized["diagnostics"]])
        receipt = self._receipt()
        self.assertEqual(receipt["notification"]["outbound"], "none")
        self.assertFalse(receipt["notification"]["authorized"])

    def test_an2_11b_authorized_notification_still_has_no_outbound_channel(self):
        self._record()
        result = self._append(notification_authorized=True,
                              notification_ref="05-audit/approval.json")
        notification = result["record"]["notification"]
        self.assertEqual(notification["state"], "authorized_local_only")
        self.assertTrue(notification["authorized"])
        self.assertEqual(notification["outbound"], "none")
        self.assertIn("local todo", notification["note"])

    # ---------------------------------------------------------------- AN2-12
    def test_an2_12_missing_delivery_reference_is_broken_not_ok(self):
        self._record()
        result = self._append(delivery_state="shipped",
                              delivery_refs=["05-audit/missing-receipt.json"])
        self.assertIn("BROKEN_REFERENCE",
                      [item["code"] for item in result["diagnostics"]])
        self.assertNotEqual(result["record"]["delivery_evidence_state"], "OK")
        receipt = self._receipt()
        self.assertEqual(receipt["delivery"]["evidence_state"], "BROKEN_REFERENCE")
        self.assertIn("BROKEN_REFERENCE",
                      [item["code"] for item in receipt["diagnostics"]])

    def test_an2_12b_delivery_state_without_reference_is_flagged(self):
        self._record()
        result = self._append(delivery_state="shipped")
        self.assertIn("DELIVERY_REFERENCE_REQUIRED",
                      [item["code"] for item in result["diagnostics"]])
        self.assertEqual(result["record"]["delivery_evidence_state"], "NO_REFERENCE")

    # ---------------------------------------------------------------- AN2-13
    def test_an2_13_repeated_receipt_is_identical_and_read_only(self):
        self._record()
        self._append(delivery_state="shipped", delivery_refs=[self._delivery_file()],
                     outcome_state="observed", outcome_events=[self._event()])
        reasoning = self._bytes()
        followups = decision_followup.followups_path(self.study).read_bytes()
        first = self._receipt()
        second = self._receipt()
        self.assertEqual(first, second)
        self.assertEqual(self._bytes(), reasoning)
        self.assertEqual(decision_followup.followups_path(self.study).read_bytes(), followups)

    # ---------------------------------------------------------------- AN2-14
    def test_an2_14_four_states_move_independently(self):
        self._record()
        ref = self._delivery_file()
        self._append(choice_state="accepted")
        self._append(choice_state="accepted", delivery_state="shipped",
                     delivery_refs=[ref], at=AT2)
        self._append(choice_state="accepted", delivery_state="shipped",
                     delivery_refs=[ref], outcome_state="observed",
                     outcome_events=[self._event()], at="2026-11-22T09:00:00+00:00")
        self._append(choice_state="accepted", delivery_state="shipped",
                     delivery_refs=[ref], outcome_state="observed",
                     outcome_events=[self._event()], causality_state="designed",
                     note="pre-registered readout plan", at="2026-11-23T09:00:00+00:00")
        receipt = self._receipt()
        self.assertEqual(receipt["states"],
                         {"choice": "accepted", "delivery": "shipped",
                          "outcome": "observed", "causality": "designed"})
        timeline = receipt["timeline"]
        self.assertEqual(len(timeline), 4)
        self.assertEqual([item["delivery_state"] for item in timeline],
                         ["unknown", "shipped", "shipped", "shipped"])
        self.assertEqual([item["outcome_state"] for item in timeline],
                         ["unknown", "unknown", "observed", "observed"])
        self.assertEqual([item["causality_state"] for item in timeline],
                         ["not_claimed", "not_claimed", "not_claimed", "designed"])

    # ------------------------------------------------------------------ XN2
    def test_xn2_01_identical_append_is_idempotent(self):
        self._record()
        first = self._append()
        second = self._append()
        self.assertEqual(first["status"], "recorded")
        self.assertEqual(second["status"], "unchanged")
        self.assertEqual(first["followup_id"], second["followup_id"])
        self.assertEqual(self._lines(), 1)

    def test_xn2_02_receipt_without_followup_reports_missing_not_zero(self):
        self._record()
        before = self._bytes()
        receipt = self._receipt()
        self.assertEqual(self._bytes(), before)
        self.assertEqual(receipt["states"]["choice"], "not_recorded")
        self.assertEqual(receipt["states"]["delivery"], "unknown")
        self.assertEqual(receipt["states"]["outcome"], "unknown")
        self.assertEqual(receipt["choice"]["reason"], None)
        self.assertEqual(receipt["delivery"]["evidence_state"], "NO_REFERENCE")
        self.assertIn("FOLLOWUP_NOT_RECORDED",
                      [item["code"] for item in receipt["diagnostics"]])
        self.assertEqual(receipt["followup_count"], 0)

    def test_xn2_03_unknown_decision_is_refused(self):
        self._record()
        with self.assertRaises(ValueError):
            decision_followup.append_followup(
                self.study, decision_id="DR-PR01-999", choice_state="accepted",
                owner_ref="pm", source_ref="note:x")
        with self.assertRaises(ValueError):
            self._append(choice_state="approved")
        self.assertEqual(self._lines(), 0)

    def test_xn2_04_external_text_is_escaped_in_html(self):
        self._record()
        self._append(choice_state="rejected",
                     note='<script>alert("x")</script> & "quoted"')
        receipt = self._receipt()
        html = decision_followup.render_receipt_html(receipt)
        self.assertNotIn("<script>alert", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn('id="follow-up"', html)
        self.assertNotIn("https://", html.split("<style>")[0])
        markdown = decision_followup.render_receipt_md(receipt)
        self.assertIn("决策回执", markdown)

    def test_xn2_05_write_receipt_is_deterministic_and_local(self):
        self._record()
        self._append(choice_state="accepted")
        first = decision_followup.write_receipt(self.study, "DR-PR01-001", at=AT)
        json_first = Path(first["files"]["json"]).read_bytes()
        second = decision_followup.write_receipt(self.study, "DR-PR01-001", at=AT)
        self.assertEqual(first["files"], second["files"])
        self.assertEqual(Path(second["files"]["json"]).read_bytes(), json_first)
        self.assertFalse(first["canonical_write"])
        html = Path(first["files"]["html"]).read_text(encoding="utf-8")
        self.assertNotIn("http://", html)
        self.assertNotIn("https://", html)

    def test_xn2_06_list_reports_states_without_writing(self):
        self._record()
        self._append(choice_state="accepted")
        before = decision_followup.followups_path(self.study).read_bytes()
        listing = decision_followup.list_followups(self.study)
        self.assertEqual(listing["count"], 1)
        self.assertEqual(listing["followups"][0]["choice_state"], "accepted")
        self.assertEqual(decision_followup.followups_path(self.study).read_bytes(), before)

    def test_xn2_07_invalid_delivery_and_causality_are_labelled(self):
        self._record()
        result = self._append(delivery_state="sent-ish", causality_state="proven")
        self.assertEqual(result["record"]["delivery_state"], "unknown")
        self.assertEqual(result["record"]["causality_state"], "not_claimed")
        codes = [item["code"] for item in result["diagnostics"]]
        self.assertIn("DELIVERY_STATE_INVALID", codes)
        self.assertIn("CAUSALITY_STATE_INVALID", codes)

    def test_xn2_08_incomplete_review_is_flagged(self):
        self._record()
        result = self._append(reviewer="research-lead")
        self.assertIn("REVIEW_INCOMPLETE",
                      [item["code"] for item in result["diagnostics"]])
        self.assertEqual(result["record"]["reviewer"], "research-lead")
        self.assertEqual(result["record"]["reviewed_at"], "")

    def test_xn2_09_import_requires_prior_followup(self):
        self._record()
        with self.assertRaises(ValueError):
            decision_followup.import_outcome_events(
                self.study, decision_id="DR-PR01-001", events=[self._event()])

    def test_xn2_10_every_record_declares_no_effect(self):
        self._record()
        result = self._append(outcome_state="observed", outcome_events=[self._event()])
        self.assertEqual(result["effects"], decision_followup.EFFECTS)
        self.assertEqual(result["record"]["verification_effect"], "none")
        self.assertTrue(all(value == "none" for value in result["effects"].values()))

    # ------------------------------------------------------------------- CLI
    def test_cli_11_add_list_and_receipt(self):
        self._record()
        ref = self._delivery_file()
        added = run_cli("followup", "add", str(self.study),
                        "--decision", "DR-PR01-001",
                        "--choice", "accepted",
                        "--owner", "pm",
                        "--source", "note:kickoff",
                        "--delivery-state", "shipped",
                        "--delivery-ref", ref,
                        "--at", AT)
        self.assertEqual(added.returncode, 0, added.stderr)
        payload = json.loads(added.stdout)
        self.assertEqual(payload["status"], "recorded")
        self.assertEqual(payload["record"]["delivery_state"], "shipped")

        listing = run_cli("followup", "list", str(self.study))
        self.assertEqual(listing.returncode, 0, listing.stderr)
        self.assertEqual(json.loads(listing.stdout)["count"], 1)

        receipt = run_cli("followup", "receipt", str(self.study),
                          "--decision", "DR-PR01-001", "--markdown", "--at", AT)
        self.assertEqual(receipt.returncode, 0, receipt.stderr)
        self.assertIn("决策回执", receipt.stdout)

    def test_cli_12_import_events_end_to_end(self):
        self._record()
        self._append(choice_state="accepted")
        events_file = self.tmp / "events.json"
        events_file.write_text(json.dumps({"events": [self._event()]}, ensure_ascii=False),
                               encoding="utf-8")
        imported = run_cli("followup", "import", str(self.study),
                           "--decision", "DR-PR01-001",
                           "--events", str(events_file), "--at", AT2)
        self.assertEqual(imported.returncode, 0, imported.stderr)
        payload = json.loads(imported.stdout)
        self.assertEqual(payload["added_events"], 1)

        receipt = run_cli("followup", "receipt", str(self.study),
                          "--decision", "DR-PR01-001", "--json", "--at", AT)
        self.assertEqual(receipt.returncode, 0, receipt.stderr)
        body = json.loads(receipt.stdout)
        self.assertEqual(body["states"]["outcome"], "observed")
        self.assertEqual(body["states"]["causality"], "not_claimed")


if __name__ == "__main__":
    unittest.main()
