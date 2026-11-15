#!/usr/bin/env python3
"""A-03 issue -> user task / demand structuring: machine candidates and human acceptance.

Frozen acceptance tests for `askovo issues` (PRD 01-Askovo §3 A-03, AC A13-A18).
Everything runs offline against synthetic GitHub issue exports: no network, no API
call, no candidate may enter the canonical chain without a named human accepting
it. The machine candidate carries exactly the thirteen PRD fields; the semantic
rules (same author, request vs. behavior, unverified, deleted source, counter
evidence, private content) are enforced in code and frozen here.
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

# PRD §3 A-03, verbatim: the thirteen machine-candidate fields.
CANDIDATE_FIELDS = (
    "issue_ref",
    "author_ref",
    "created_at",
    "updated_at",
    "user_task",
    "trigger",
    "current_workaround",
    "failure_consequence",
    "requested_feature",
    "severity_candidate",
    "source_quote_span",
    "confidence_basis",
    "representativeness_warning",
)
CLAIM_KINDS = ("bug_reproduction", "subjective_complaint", "feature_request",
               "observed_behavior", "unknown")


def run_cli(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    merged = dict(os.environ)
    merged.setdefault("ASKOVO_AUTHOR_SALT", "a-03-frozen-test-salt")
    if env:
        merged.update(env)
    return subprocess.run([sys.executable, str(CLI), "issues", *args],
                          capture_output=True, text=True, timeout=120, env=merged)


def issue(number: int, title: str, body: str, *, author: str = "u1", **overrides) -> dict:
    """One GitHub issue-export row (the shape `gh issue list --json` produces)."""
    record = {
        "id": 10000 + number,
        "number": number,
        "title": title,
        "body": body,
        "state": "open",
        "html_url": f"https://github.com/owner/repo/issues/{number}",
        "user": {"login": author, "type": "User"},
        "author_association": "NONE",
        "created_at": "2026-09-01T10:00:00Z",
        "updated_at": "2026-09-02T10:00:00Z",
        "labels": [],
        "comments": [],
        "visibility": "public",
    }
    record.update(overrides)
    return record


class IssueHelpers:
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.study = self.dir / "study"
        shutil.copytree(SAMPLE, self.study)

    # -- fixture plumbing -------------------------------------------------- #

    def write_export(self, rows: list[dict], name: str = "issues.jsonl") -> Path:
        path = self.dir / name
        path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
                        encoding="utf-8")
        return path

    def import_issues(self, rows: list[dict], *extra: str, name: str = "issues.jsonl"):
        path = self.write_export(rows, name=name)
        completed = run_cli("import", str(self.study), "--file", str(path),
                            "--authorized-by", "research-lead", *extra)
        return completed, self._payload(completed)

    def extract(self, *extra: str):
        completed = run_cli("extract", str(self.study), *extra)
        return completed, self._payload(completed)

    def _payload(self, completed: subprocess.CompletedProcess) -> dict:
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError:
            return {"raw": completed.stdout, "stderr": completed.stderr}

    def candidates_doc(self) -> dict:
        return json.loads(
            (self.study / "04-findings" / "issue-candidates.json").read_text(encoding="utf-8"))

    def candidates(self) -> list[dict]:
        return self.candidates_doc()["candidates"]

    def candidate(self, issue_number: int) -> dict:
        for item in self.candidates():
            if str(issue_number) in str(item.get("issue_ref")):
                return item
        raise AssertionError(f"no candidate for issue {issue_number}: "
                             + json.dumps([c.get("issue_ref") for c in self.candidates()]))

    def evidence_records(self) -> list[dict]:
        path = self.study / "02-data" / "evidence.jsonl"
        if not path.is_file():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()]

    def judgments(self) -> list[dict]:
        path = self.study / "04-findings" / "demand-judgments.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []

    def study_text(self) -> str:
        """Every byte under the study, for "private content never spread" checks."""
        chunks: list[str] = []
        for path in sorted(self.study.rglob("*")):
            if path.is_file() and path.suffix in (".json", ".jsonl", ".md", ".csv", ".txt"):
                try:
                    chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
                except OSError:
                    continue
        return "\n".join(chunks)


class IssueImportTests(IssueHelpers, unittest.TestCase):

    def test_import_requires_a_named_authorizer(self) -> None:
        path = self.write_export([issue(1, "cannot parse logs", "Nested JSON logs fail.")])
        completed = run_cli("import", str(self.study), "--file", str(path))
        self.assertEqual(4, completed.returncode, completed.stdout + completed.stderr)
        body = self._payload(completed)
        self.assertEqual("AUTH_REQUIRED", body["reason_code"])
        self.assertFalse((self.study / "02-data" / "normalized.jsonl").exists(),
                         "an unauthorized import must not write normalized records")

    def test_import_is_idempotent_and_keeps_one_snapshot(self) -> None:
        rows = [issue(1, "cannot parse logs", "Nested JSON logs fail."),
                issue(2, "multiline traces", "Multiline stack traces break alerts.")]
        first, first_payload = self.import_issues(rows)
        self.assertEqual(0, first.returncode, first_payload)
        self.assertEqual(2, first_payload["added"])
        second, second_payload = self.import_issues(rows)
        self.assertEqual(0, second.returncode, second_payload)
        self.assertEqual(0, second_payload["added"], "a repeated import must not duplicate records")
        normalized = [line for line in
                      (self.study / "02-data" / "normalized.jsonl").read_text(encoding="utf-8").splitlines()
                      if line.strip()]
        self.assertEqual(2, len(normalized))

    def test_private_visibility_is_never_exported(self) -> None:
        rows = [issue(1, "public issue", "Nested JSON logs fail to parse."),
                issue(2, "private security report", "INTERNAL-ONLY: customer Acme pays 10k/month.",
                      visibility="private")]
        completed, payload = self.import_issues(rows)
        self.assertEqual(0, completed.returncode, payload)
        self.assertEqual(1, payload["skipped_private"])
        self.assertNotIn("Acme pays 10k", self.study_text(),
                         "private issue bodies must not reach any study artifact")

    def test_private_note_is_redacted_from_public_exports(self) -> None:
        rows = [issue(1, "cannot parse logs", "Nested JSON logs fail to parse.",
                      private_note="INTERNAL: escalation from Acme, 10k MRR at risk")]
        completed, payload = self.import_issues(rows)
        self.assertEqual(0, completed.returncode, payload)
        self.assertEqual(1, payload["added"])
        completed, payload = self.extract()
        self.assertEqual(0, completed.returncode, payload)
        self.assertTrue(self.candidates(), "the public issue must still yield a candidate")
        self.assertNotIn("10k MRR", self.study_text())

    def test_selection_bias_is_explicit_for_filtered_windows(self) -> None:
        rows = [issue(1, "cannot parse logs", "Nested JSON logs fail to parse.",
                      labels=[{"name": "bug"}])]
        completed, payload = self.import_issues(
            rows, "--since", "2026-08-01", "--label", "bug")
        self.assertEqual(0, completed.returncode, payload)
        self.extract()
        doc = self.candidates_doc()
        self.assertTrue(doc["selection_bias"], "a filtered sample must state its selection bias")
        self.assertIn("2026-08-01", doc["selection_bias"])
        self.assertIn("bug", doc["selection_bias"])

    def test_snapshot_hash_and_rights_survive_a_deleted_source(self) -> None:
        rows = [issue(1, "cannot parse logs", "Nested JSON logs fail to parse.",
                      state="deleted", deleted_at="2026-10-01T00:00:00Z")]
        completed, payload = self.import_issues(rows)
        self.assertEqual(0, completed.returncode, payload)
        manifest_path = Path(payload["manifest"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        snapshot = manifest["snapshots"][0]
        self.assertTrue(snapshot["sha256"].startswith("sha256:"))
        self.assertEqual(str(Path(payload["snapshot"]).resolve()), snapshot["path"])
        self.assertTrue(manifest["acquisition_basis"])
        self.assertTrue(manifest["retention_rule"])
        self.assertIn("deleted", json.dumps(manifest).lower(),
                      "a deleted source must be recorded, not silently dropped")


    def test_live_source_is_not_reported_as_deleted(self) -> None:
        rows = [issue(1, "cannot parse logs", "Nested JSON logs fail to parse.")]
        self.import_issues(rows)
        self.extract()
        self.assertEqual("snapshot", self.candidates()[0]["source_availability"],
                         "an existing source must not be reported as snapshot only")


class IssueExtractionTests(IssueHelpers, unittest.TestCase):

    def _import_four_claim_kinds(self) -> None:
        rows = [
            issue(1, "parser crashes on nested JSON",
                  "Steps to reproduce:\n```\naskovo parse x.json\n```\nTraceback: ValueError",
                  author="reporter", labels=[{"name": "bug"}]),
            issue(2, "slow and ugly", "Honestly the dashboard is slow and ugly. I just do not like it.",
                  author="complainer"),
            issue(3, "add dark mode", "请加一个深色模式按钮，晚上看着累。", author="requester"),
            issue(4, "weekly manual retry",
                  "We retry by hand every week because nested logs fail to parse.",
                  author="operator"),
        ]
        completed, payload = self.import_issues(rows)
        self.assertEqual(0, completed.returncode, payload)
        completed, payload = self.extract()
        self.assertEqual(0, completed.returncode, payload)

    def test_candidate_carries_all_thirteen_prd_fields(self) -> None:
        self._import_four_claim_kinds()
        for candidate in self.candidates():
            for field in CANDIDATE_FIELDS:
                self.assertIn(field, candidate, f"{candidate.get('issue_ref')} missing {field}")

    def test_claim_kinds_stay_four_distinct_values(self) -> None:
        self._import_four_claim_kinds()
        kinds = {candidate["claim_kind"] for candidate in self.candidates()}
        self.assertEqual({"bug_reproduction", "subjective_complaint", "feature_request",
                          "observed_behavior"}, kinds)
        for candidate in self.candidates():
            self.assertIn(candidate["claim_kind"], CLAIM_KINDS)
            self.assertNotIn("type", candidate,
                             "a single `type` field would collapse the four claim kinds")

    def test_quote_span_is_an_exact_slice_of_the_source_text(self) -> None:
        self._import_four_claim_kinds()
        for candidate in self.candidates():
            span = candidate["source_quote_span"]
            self.assertIsInstance(span, dict)
            self.assertEqual(candidate["source_text"][span["start"]:span["end"]], span["text"])

    def test_same_author_ten_issues_is_one_observed_user(self) -> None:
        rows = [issue(number, f"nested log parse failure {number}",
                      "Nested JSON logs fail to parse; we retry by hand every week.",
                      author="prolific")
                for number in range(1, 11)]
        completed, payload = self.import_issues(rows)
        self.assertEqual(0, completed.returncode, payload)
        completed, payload = self.extract()
        self.assertEqual(0, completed.returncode, payload)
        doc = self.candidates_doc()
        observation = doc["observation"]
        self.assertEqual(10, observation["record_count"])
        self.assertEqual(1, observation["observed_users"],
                         "ten issues from one login are still one observed user")
        self.assertEqual({"github:prolific": 10}, observation["records_per_author"])
        self.assertEqual(10, observation["max_records_per_author"])
        self.assertIn("not", observation["identity_basis_note"].lower())

    def test_same_issue_many_comments_is_one_user(self) -> None:
        comments = [{"user": {"login": f"commenter{n}"}, "body": f"same here ({n})",
                     "created_at": "2026-09-03T00:00:00Z"} for n in range(12)]
        rows = [issue(1, "nested log parse failure",
                      "Nested JSON logs fail to parse; we retry by hand every week.",
                      author="reporter", comments=comments)]
        self.import_issues(rows)
        self.extract()
        doc = self.candidates_doc()
        observation = doc["observation"]
        self.assertEqual(12, observation["comment_count"])
        self.assertEqual(1, observation["observed_users"],
                         "comments on one issue are context, not independent users")

    def test_distinct_logins_are_not_proven_distinct_people(self) -> None:
        rows = [issue(number, "nested log parse failure",
                      "Nested JSON logs fail to parse; we retry by hand every week.",
                      author=f"user{number}")
                for number in (1, 2, 3)]
        self.import_issues(rows)
        self.extract()
        observation = self.candidates_doc()["observation"]
        self.assertEqual(3, observation["observed_users"])
        self.assertEqual("login_only", observation["identity_basis"])
        self.assertIn("not proven distinct", observation["identity_basis_note"])

    def test_maintainer_feedback_is_listed_separately(self) -> None:
        rows = [
            issue(1, "nested log parse failure",
                  "Nested JSON logs fail to parse; we retry by hand every week.", author="user1"),
            issue(2, "nested log parse failure",
                  "Confirmed, we will look at the parser.", author="maintainer",
                  author_association="MEMBER"),
        ]
        self.import_issues(rows)
        self.extract()
        doc = self.candidates_doc()
        self.assertTrue(doc["maintainer_feedback"], "maintainer feedback must be listed separately")
        self.assertEqual(1, doc["observation"]["maintainer_records"])
        self.assertEqual(1, doc["observation"]["observed_users"],
                         "a maintainer is not an independent user observation")
        maintainer = [c for c in doc["candidates"] if c["maintainer_feedback"]]
        self.assertEqual(1, len(maintainer))
        self.assertEqual("github:maintainer", maintainer[0]["author_ref"])

    def test_duplicate_issues_merge_theme_but_keep_every_source(self) -> None:
        rows = [issue(number, "nested log parse failure",
                      "Nested JSON logs fail to parse; we retry by hand every week.",
                      author=f"user{number}")
                for number in (1, 2, 3)]
        self.import_issues(rows)
        self.extract()
        candidates = self.candidates()
        self.assertEqual(1, len(candidates), "duplicate issues merge into one theme candidate")
        self.assertEqual(3, len(candidates[0]["source_refs"]))
        self.assertEqual(3, len(set(candidates[0]["source_refs"])))
        self.assertEqual(3, candidates[0]["support_count"])

    def test_login_case_and_whitespace_are_one_observed_user(self) -> None:
        """D2: GitHub logins are case-insensitive; variants are one person."""
        identical = "Nested JSON logs fail to parse; we retry by hand every week."
        rows = [issue(1, "nested log parse failure", identical,
                      user={"login": "Alice", "id": 501}),
                issue(2, "nested log parse failure", identical,
                      user={"login": "alice", "id": 501}),
                issue(3, "nested log parse failure", identical,
                      user={"login": "  alice  ", "id": 501})]
        self.import_issues(rows)
        self.extract()
        doc = self.candidates_doc()
        self.assertEqual(1, doc["observation"]["observed_users"],
                         "login case and surrounding whitespace must not create users")
        self.assertEqual(3, doc["observation"]["record_count"])
        self.assertEqual({"github:alice": 3}, doc["observation"]["records_per_author"])
        self.assertEqual(1, len(doc["candidates"]))
        self.assertEqual("github:alice", doc["candidates"][0]["author_ref"])

    def test_stable_user_id_survives_a_login_rename(self) -> None:
        """D2: the snapshot keeps GitHub's stable user id, which is the identity key."""
        rows = [issue(1, "nested log parse failure",
                      "Nested JSON logs fail to parse; we retry by hand every week.",
                      user={"login": "Alice", "id": 501})]
        self.import_issues(rows)
        normalized = [json.loads(line) for line in
                      (self.study / "02-data" / "normalized.jsonl")
                      .read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(501, (normalized[0].get("issue") or {}).get("user_id"),
                         "the snapshot must keep the stable user id")

    def test_extraction_is_deterministic(self) -> None:
        self._import_four_claim_kinds()
        first = self.candidates_doc()
        completed, payload = self.extract()
        self.assertEqual(0, completed.returncode, payload)
        second = self.candidates_doc()
        self.assertEqual(first["digest"], second["digest"])
        self.assertEqual([c["id"] for c in first["candidates"]],
                         [c["id"] for c in second["candidates"]])


class IssueSemanticGateTests(IssueHelpers, unittest.TestCase):

    def test_feature_request_alone_is_never_strong_demand(self) -> None:
        rows = [issue(1, "add dark mode", "请加一个深色模式按钮。", author="requester")]
        self.import_issues(rows)
        self.extract()
        candidate = self.candidates()[0]
        self.assertEqual("feature_request", candidate["claim_kind"])
        self.assertEqual("unknown", candidate["severity_candidate"],
                         "a feature request is not a severity")
        self.assertEqual("none", candidate["demand_claim"],
                         "a request alone cannot carry a demand claim")
        self.assertEqual("insufficient", candidate["disposition"])
        self.assertEqual("E1", candidate["evidence_cap"],
                         "a request caps at E1 (stated desire), never E2+ behavior")

    def test_requested_feature_does_not_become_the_user_task(self) -> None:
        rows = [issue(1, "add dark mode", "请加一个深色模式按钮。", author="requester")]
        self.import_issues(rows)
        self.extract()
        candidate = self.candidates()[0]
        self.assertTrue(candidate["requested_feature"])
        self.assertEqual("unknown", candidate["user_task"],
                         "a request is not a user task; keep the task unknown")

    def test_observed_behavior_outranks_a_request(self) -> None:
        rows = [issue(1, "add dark mode",
                      "请加一个深色模式按钮。另外我们每周手动重试解析，因为嵌套日志会失败。",
                      author="requester")]
        self.import_issues(rows)
        self.extract()
        candidate = self.candidates()[0]
        self.assertEqual("observed_behavior", candidate["claim_kind"])
        self.assertTrue(candidate["current_workaround"])

    def test_no_reproducible_text_stays_unverified(self) -> None:
        rows = [issue(1, "something is off", "", author="vague")]
        self.import_issues(rows)
        self.extract()
        candidate = self.candidates()[0]
        self.assertEqual("unverified", candidate["confidence_basis"])
        self.assertIsNone(candidate["source_quote_span"],
                          "no quotable text means no quoted span, never an invented one")
        self.assertEqual("unknown", candidate["severity_candidate"])
        self.assertEqual("unknown", candidate["claim_kind"])

    def test_bug_label_without_reproduction_is_not_bug_reproduction(self) -> None:
        rows = [issue(1, "it is broken sometimes", "It feels broken sometimes I guess.",
                      author="vague", labels=[{"name": "bug"}])]
        self.import_issues(rows)
        self.extract()
        self.assertNotEqual("bug_reproduction", self.candidates()[0]["claim_kind"],
                            "a bug label is not a reproduction")

    def test_reproduction_text_raises_the_confidence_basis(self) -> None:
        rows = [issue(1, "parser crashes",
                      "Steps to reproduce:\n1. run askovo parse\n```\nTraceback: ValueError\n```",
                      author="reporter")]
        self.import_issues(rows)
        self.extract()
        candidate = self.candidates()[0]
        self.assertEqual("bug_reproduction", candidate["claim_kind"])
        self.assertEqual("reproducible_text", candidate["confidence_basis"])
        self.assertEqual("E2", candidate["evidence_cap"])

    def test_one_counter_evidence_is_not_drowned_by_support(self) -> None:
        rows = [issue(number, "nested log parse failure",
                      "Nested JSON logs fail to parse; we retry by hand every week.",
                      author=f"supporter{number}")
                for number in (1, 2, 3, 4, 5)]
        rows.append(issue(9, "nested log parse failure",
                          "This does not happen for us; nested logs parse fine and we would not pay.",
                          author="skeptic"))
        self.import_issues(rows)
        self.extract()
        candidate = [c for c in self.candidates() if c["counter_count"]][0]
        self.assertEqual(5, candidate["support_count"])
        self.assertEqual(1, candidate["counter_count"])
        self.assertFalse(candidate["majority_wins"])
        self.assertEqual("challenged", candidate["disposition"],
                         "one counter-evidence must never be outvoted by support count")
        self.assertTrue(candidate["counter_evidence"])


class IssueAcceptanceTests(IssueHelpers, unittest.TestCase):

    def _ready_candidate(self) -> str:
        rows = [issue(1, "nested log parse failure",
                      "Nested JSON logs fail to parse; we retry by hand every week.",
                      author="operator")]
        completed, payload = self.import_issues(rows)
        self.assertEqual(0, completed.returncode, payload)
        completed, payload = self.extract()
        self.assertEqual(0, completed.returncode, payload)
        return self.candidates()[0]["id"]

    def test_accept_requires_a_named_human(self) -> None:
        candidate_id = self._ready_candidate()
        before = self.judgments()
        completed = run_cli("accept", str(self.study), "--candidate", candidate_id)
        self.assertEqual(4, completed.returncode, completed.stdout + completed.stderr)
        body = self._payload(completed)
        self.assertEqual("AUTH_REQUIRED", body["reason_code"])
        self.assertEqual(before, self.judgments(), "no human, no new judgment")

    def test_accept_writes_one_evidence_record_and_one_judgment(self) -> None:
        candidate_id = self._ready_candidate()
        before = len(self.evidence_records())
        completed = run_cli("accept", str(self.study), "--candidate", candidate_id,
                            "--by", "product-owner", "--context-key", "nested-log-parse",
                            "--judgment-id", "D03", "--evidence-level", "E2")
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        records = self.evidence_records()
        self.assertEqual(before + 1, len(records))
        accepted = records[-1]
        for field in ("record_id", "user_role", "scene_trigger", "task_outcome",
                      "current_substitute", "friction_cost", "consequence", "evidence_level",
                      "evidence_basis", "corpus_role", "source_family", "source_ref",
                      "normalized_text_hash"):
            self.assertIn(field, accepted, f"evidence record missing {field}")
        self.assertEqual("E2", accepted["evidence_level"])
        self.assertEqual("nested-log-parse", accepted["context_key"])
        judgments = self.judgments()
        self.assertEqual(1, len([j for j in judgments if j["id"] == "D03"]))
        judgment = [j for j in judgments if j["id"] == "D03"][0]
        self.assertEqual([accepted["record_id"]], judgment["problem_evidence_ids"])

    def test_accept_keeps_an_audit_trail(self) -> None:
        candidate_id = self._ready_candidate()
        completed = run_cli("accept", str(self.study), "--candidate", candidate_id,
                            "--by", "product-owner", "--context-key", "nested-log-parse",
                            "--judgment-id", "D03", "--evidence-level", "E2",
                            "--set", "user_role=CLI 使用者")
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        trail = [json.loads(line) for line in
                 (self.study / "04-findings" / "issue-acceptance.jsonl")
                 .read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(1, len(trail))
        entry = trail[0]
        self.assertEqual(candidate_id, entry["candidate_id"])
        self.assertEqual("product-owner", entry["accepted_by"])
        self.assertTrue(entry["accepted_at"])
        self.assertEqual({"user_role": "CLI 使用者"}, entry["edits"])
        self.assertEqual("accepted", entry["status"])

    def test_accept_is_idempotent(self) -> None:
        candidate_id = self._ready_candidate()
        args = ("accept", str(self.study), "--candidate", candidate_id,
                "--by", "product-owner", "--context-key", "nested-log-parse",
                "--judgment-id", "D03", "--evidence-level", "E2")
        first = run_cli(*args)
        self.assertEqual(0, first.returncode, first.stdout + first.stderr)
        count = len(self.evidence_records())
        second = run_cli(*args)
        self.assertEqual(0, second.returncode, second.stdout + second.stderr)
        self.assertEqual(count, len(self.evidence_records()),
                         "a repeated accept must not duplicate the evidence record")
        self.assertEqual(1, len([j for j in self.judgments() if j["id"] == "D03"]))

    def test_feature_request_cannot_be_accepted_as_behavior_evidence(self) -> None:
        rows = [issue(1, "add dark mode", "请加一个深色模式按钮。", author="requester")]
        self.import_issues(rows)
        self.extract()
        candidate_id = self.candidates()[0]["id"]
        completed = run_cli("accept", str(self.study), "--candidate", candidate_id,
                            "--by", "product-owner", "--context-key", "dark-mode",
                            "--judgment-id", "D04", "--evidence-level", "E2")
        self.assertEqual(2, completed.returncode, completed.stdout + completed.stderr)
        body = self._payload(completed)
        self.assertEqual("POLICY_DENIED", body["reason_code"])
        self.assertIn("E1", body["reason"])

    def test_accept_refuses_an_unknown_candidate(self) -> None:
        self._ready_candidate()
        completed = run_cli("accept", str(self.study), "--candidate", "IC-999",
                            "--by", "product-owner")
        self.assertEqual(2, completed.returncode, completed.stdout + completed.stderr)
        self.assertEqual("INPUT_REQUIRED", self._payload(completed)["reason_code"])

    def test_reject_keeps_the_candidate_out_of_the_chain(self) -> None:
        candidate_id = self._ready_candidate()
        completed = run_cli("reject", str(self.study), "--candidate", candidate_id,
                            "--by", "product-owner", "--reason", "单一自述，不足以为判断")
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertEqual([], [j for j in self.judgments() if j.get("id") == "D03"])
        trail = (self.study / "04-findings" / "issue-acceptance.jsonl").read_text(encoding="utf-8")
        self.assertIn("rejected", trail)
        self.assertIn("单一自述", trail)

    def test_accept_registers_counter_evidence_on_both_artifacts(self) -> None:
        """D3: acceptance must carry the candidate's counter-evidence into the chain.

        A-03 maps candidates into `demand-judgments` + `product-reasoning`; dropping
        `counter_evidence` there hides it from A-04's `review_signal`, so the brief
        never flags `needs_re_review` (AC A17 x A21).
        """
        identical = "Nested JSON logs fail to parse; we retry by hand every week."
        rows = [issue(1, "nested log parse failure", identical, author="alice", author_id=501),
                issue(2, "nested log parse failure", identical, author="bob", author_id=502),
                issue(3, "nested log parse failure",
                      "This does not happen for us; nested logs parse fine and we would not pay.",
                      author="skeptic", author_id=504)]
        self.import_issues(rows)
        self.extract()
        # The sample chain ships R05/R07 as counter evidence; clear it so
        # `needs_re_review` can only flip because of the accepted candidate.
        reasoning_path = self.study / "04-findings" / "product-reasoning.json"
        reasoning = json.loads(reasoning_path.read_text(encoding="utf-8"))
        reasoning["chains"][0]["counter_evidence_ids"] = []
        reasoning_path.write_text(json.dumps(reasoning, ensure_ascii=False, indent=2) + "\n",
                                  encoding="utf-8")
        candidate = [item for item in self.candidates() if item["counter_count"]][0]
        counter_ids = [item["record_id"] for item in candidate["counter_evidence"]]
        self.assertTrue(counter_ids, "the fixture must expose one counter record")
        completed = run_cli("accept", str(self.study), "--candidate", candidate["id"],
                            "--by", "product-owner", "--context-key", "nested-log-parse",
                            "--judgment-id", "D03", "--evidence-level", "E2")
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        judgment = [item for item in self.judgments() if item["id"] == "D03"][0]
        self.assertEqual(counter_ids, judgment["counter_evidence_ids"],
                         "the accepted judgment must keep the counter evidence")
        chains = json.loads((self.study / "04-findings" / "product-reasoning.json")
                            .read_text(encoding="utf-8"))["chains"]
        chain = [item for item in chains if item.get("demand_judgment_id") == "D03"][0]
        for record_id in counter_ids:
            self.assertIn(record_id, chain["counter_evidence_ids"],
                          "the canonical chain must keep the counter evidence")
        brief = subprocess.run([sys.executable, str(CLI), "brief", str(self.study),
                                "--format", "json"],
                               capture_output=True, text=True, timeout=120)
        document = json.loads(brief.stdout)
        self.assertEqual("partial", document["artifact_status"], document.get("stale_reasons"))
        self.assertTrue(document["needs_re_review"],
                        "a counter-evidence must make the brief require re-review")

    def test_accept_records_keep_their_own_provenance(self) -> None:
        """The counter record must point at the counter issue, not at the supporter.

        Regression: `_counter_record()` copied `candidate["issue_ref"]` (the
        supporting issue #1) while the text came from the counter issue #9, so an
        audit following `source_ref` landed on the wrong issue — worse than a
        dropped counter-evidence, because it looks traceable.
        """
        identical = "Nested JSON logs fail to parse; we retry by hand every week."
        rows = [issue(1, "nested log parse failure", identical, author="alice", author_id=501),
                issue(2, "nested log parse failure", identical, author="bob", author_id=502),
                issue(9, "nested log parse failure",
                      "This does not happen for us; nested logs parse fine and we would not pay.",
                      author="skeptic", author_id=509)]
        self.import_issues(rows)
        self.extract()
        candidate = [item for item in self.candidates() if item["counter_count"]][0]
        counter = candidate["counter_evidence"][0]
        self.assertEqual("github:10009", counter["record_id"])
        completed = run_cli("accept", str(self.study), "--candidate", candidate["id"],
                            "--by", "product-owner", "--context-key", "nested-log-parse",
                            "--judgment-id", "D03", "--evidence-level", "E2")
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        records = {item["record_id"]: item for item in self.evidence_records()}
        counter_record = records[counter["record_id"]]
        self.assertTrue(counter_record["source_ref"].endswith("#9"),
                        f"counter source_ref points at {counter_record['source_ref']!r}")
        self.assertEqual(counter["source_ref"], counter_record["source_ref"])
        self.assertEqual(counter["author_ref"], counter_record["author_ref"])
        self.assertEqual(counter["created_at"], counter_record["created_at"])
        self.assertIn("does not happen", counter_record["text"],
                      "the counter record's text must be the counter issue's body")
        support_record = records[candidate["source_refs"][0]]
        self.assertEqual(candidate["issue_ref"], support_record["source_ref"],
                         "the supporting record must point at its own issue")
        self.assertTrue(support_record["source_ref"].endswith("#1"))

    def test_audit_passes_after_acceptance(self) -> None:
        candidate_id = self._ready_candidate()
        completed = run_cli("accept", str(self.study), "--candidate", candidate_id,
                            "--by", "product-owner", "--context-key", "nested-log-parse",
                            "--judgment-id", "D03", "--evidence-level", "E2")
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        audit = subprocess.run([sys.executable, str(CLI), "audit", str(self.study), "--json"],
                               capture_output=True, text=True, timeout=120)
        self.assertEqual(0, audit.returncode, audit.stdout + audit.stderr)
        payload = json.loads(audit.stdout)
        self.assertNotEqual("fail", payload.get("status"))


class IssueStatusTests(IssueHelpers, unittest.TestCase):

    def test_status_reports_candidates_and_pending_human_work(self) -> None:
        rows = [issue(1, "nested log parse failure",
                      "Nested JSON logs fail to parse; we retry by hand every week.",
                      author="operator")]
        self.import_issues(rows)
        self.extract()
        completed = run_cli("status", str(self.study))
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        payload = self._payload(completed)
        for field in ("record_count", "observed_users", "candidates", "proposed",
                      "accepted", "rejected", "next_required_action", "state"):
            self.assertIn(field, payload, f"status missing {field}")
        self.assertEqual(1, payload["candidates"])
        self.assertEqual(1, payload["proposed"])
        self.assertTrue(payload["next_required_action"])

    def test_list_filters_by_claim_kind(self) -> None:
        rows = [issue(1, "parser crashes",
                      "Steps to reproduce:\n```\naskovo parse x.json\n```\nTraceback: ValueError",
                      author="reporter"),
                issue(2, "add dark mode", "请加一个深色模式按钮。", author="requester")]
        self.import_issues(rows)
        self.extract()
        completed = run_cli("list", str(self.study), "--claim-kind", "feature_request")
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        payload = self._payload(completed)
        self.assertEqual(1, payload["count"])
        self.assertEqual("feature_request", payload["candidates"][0]["claim_kind"])


if __name__ == "__main__":
    unittest.main()
