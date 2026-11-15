#!/usr/bin/env python3
"""A-07 canonical decision write integrity (frozen acceptance tests).

`askovo issues accept` writes five artifacts: appends ``02-data/evidence.jsonl``,
rewrites ``04-findings/demand-judgments.json`` and ``product-reasoning.json``,
flips the candidate status and appends the acceptance trail. Before A-07 that
sequence could silently erase history (a corrupt judgment file was replaced by
``[]``), stop half-way (evidence on disk, judgment missing) and lose concurrent
updates (read-modify-write without a lock).

These tests freeze the A-07 contract:

- a canonical file that cannot be read is refused with ``INTERNAL_ERROR`` before
  any byte is written — never ``except -> []/{}``;
- the five writes are one journaled transaction: an interrupted accept leaves
  ``04-findings/.write-journal.json`` behind, ``askovo issues recover`` reports
  what completed and what did not, and ``--apply`` finishes it. No evidence-only
  orphan survives;
- two concurrent accepts of the same candidate cannot both write: the loser sees
  ``already_accepted`` and the three artifacts still hold exactly one record;
- an ``OSError`` during the writes rolls back and leaves the study byte-identical.

They fail on the pre-A-07 implementation by design (there is no
``write_integrity`` module and no ``issues recover`` action there).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/askovo/scripts/askovo.py"
SCRIPTS = ROOT / "skills/askovo/scripts"
SAMPLE = ROOT / "examples/sample-study"

ACCEPT_FLAGS = ("--by", "product-owner", "--context-key", "nested-log-parse",
                "--judgment-id", "D03", "--evidence-level", "E2")


def run_cli(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    merged = dict(os.environ)
    merged.setdefault("ASKOVO_AUTHOR_SALT", "a-07-write-integrity-test-salt")
    if env:
        merged.update(env)
    return subprocess.run([sys.executable, str(CLI), "issues", *args],
                          capture_output=True, text=True, timeout=120, env=merged)


def run_child(script: str, *args: str) -> subprocess.CompletedProcess:
    merged = dict(os.environ)
    merged.setdefault("ASKOVO_AUTHOR_SALT", "a-07-write-integrity-test-salt")
    return subprocess.run([sys.executable, "-c", textwrap.dedent(script), *args],
                          capture_output=True, text=True, timeout=120, env=merged)


def issue_row(number: int, body: str) -> dict:
    return {
        "id": 10000 + number,
        "number": number,
        "title": "nested log parse failure",
        "body": body,
        "state": "open",
        "html_url": f"https://github.com/owner/repo/issues/{number}",
        "user": {"login": "operator", "type": "User"},
        "author_association": "NONE",
        "created_at": "2026-09-01T10:00:00Z",
        "updated_at": "2026-09-02T10:00:00Z",
        "labels": [],
        "comments": [],
        "visibility": "public",
    }


class IntegrityHelpers(unittest.TestCase):
    """One synthetic study per test, with one extracted candidate."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.study = self.dir / "study"
        shutil.copytree(SAMPLE, self.study)

    # -- paths ------------------------------------------------------------- #

    @property
    def evidence_path(self) -> Path:
        return self.study / "02-data" / "evidence.jsonl"

    @property
    def judgments_path(self) -> Path:
        return self.study / "04-findings" / "demand-judgments.json"

    @property
    def reasoning_path(self) -> Path:
        return self.study / "04-findings" / "product-reasoning.json"

    @property
    def candidates_path(self) -> Path:
        return self.study / "04-findings" / "issue-candidates.json"

    @property
    def trail_path(self) -> Path:
        return self.study / "04-findings" / "issue-acceptance.jsonl"

    @property
    def journal_path(self) -> Path:
        return self.study / "04-findings" / ".write-journal.json"

    # -- fixture ----------------------------------------------------------- #

    def ready_candidate(self) -> str:
        export = self.dir / "issues.jsonl"
        export.write_text(json.dumps(issue_row(
            1, "Nested JSON logs fail to parse; we retry by hand every week.")) + "\n",
            encoding="utf-8")
        imported = run_cli("import", str(self.study), "--file", str(export),
                           "--authorized-by", "research-lead")
        self.assertEqual(0, imported.returncode, imported.stdout + imported.stderr)
        extracted = run_cli("extract", str(self.study))
        self.assertEqual(0, extracted.returncode, extracted.stdout + extracted.stderr)
        return self.candidates()[0]["id"]

    # -- readers ----------------------------------------------------------- #

    def payload(self, completed: subprocess.CompletedProcess) -> dict:
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError:
            return {"raw": completed.stdout, "stderr": completed.stderr}

    def candidates(self) -> list[dict]:
        return json.loads(self.candidates_path.read_text(encoding="utf-8"))["candidates"]

    def evidence(self) -> list[dict]:
        if not self.evidence_path.is_file():
            return []
        return [json.loads(line) for line in
                self.evidence_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def judgments(self) -> list[dict]:
        return json.loads(self.judgments_path.read_text(encoding="utf-8"))

    def chains(self) -> list[dict]:
        return json.loads(self.reasoning_path.read_text(encoding="utf-8"))["chains"]

    def trail(self) -> list[dict]:
        if not self.trail_path.is_file():
            return []
        return [json.loads(line) for line in
                self.trail_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def artifact_bytes(self) -> dict:
        """Exact bytes of every artifact one accept may write."""
        return {
            path: path.read_bytes() if path.is_file() else None
            for path in (self.evidence_path, self.judgments_path, self.reasoning_path,
                         self.candidates_path, self.trail_path)
        }

    def accept(self) -> subprocess.CompletedProcess:
        candidate_id = self.candidates()[0]["id"]
        return run_cli("accept", str(self.study), "--candidate", candidate_id,
                       *ACCEPT_FLAGS)


class CorruptCanonicalRefusalTests(IntegrityHelpers):
    """A: an unreadable canonical file is refused before anything is written."""

    def test_corrupt_demand_judgments_is_refused_without_writing(self) -> None:
        self.ready_candidate()
        pristine = self.judgments_path.read_bytes()
        judgment_count = len(json.loads(pristine))
        self.judgments_path.write_text("{ this is not a judgment array", encoding="utf-8")
        before = self.artifact_bytes()

        completed = self.accept()

        self.assertEqual(2, completed.returncode, completed.stdout + completed.stderr)
        body = self.payload(completed)
        self.assertEqual("INTERNAL_ERROR", body["reason_code"])
        self.assertIn(str(self.judgments_path), body["reason"],
                      "the refusal must name the unreadable canonical path")
        for path, data in before.items():
            self.assertEqual(data, path.read_bytes() if path.is_file() else None,
                             f"{path.name} changed although the accept was refused")
        self.assertNotEqual(pristine, self.judgments_path.read_bytes(),
                            "the fixture must actually be corrupt")
        self.assertEqual(judgment_count, len(json.loads(pristine)),
                         "the pre-corruption judgment count is the frozen reference")
        self.assertFalse(self.journal_path.exists(),
                         "a refused accept must not leave a write journal behind")

    def test_wrong_type_demand_judgments_is_refused_without_writing(self) -> None:
        self.ready_candidate()
        self.judgments_path.write_text('{"judgments": []}\n', encoding="utf-8")
        before = self.artifact_bytes()

        completed = self.accept()

        self.assertEqual(2, completed.returncode, completed.stdout + completed.stderr)
        self.assertEqual("INTERNAL_ERROR", self.payload(completed)["reason_code"])
        for path, data in before.items():
            self.assertEqual(data, path.read_bytes() if path.is_file() else None,
                             f"{path.name} changed although the accept was refused")

    def test_corrupt_product_reasoning_is_refused_without_writing(self) -> None:
        self.ready_candidate()
        reasoning_count = len(self.chains())
        original = self.reasoning_path.read_text(encoding="utf-8")
        self.reasoning_path.write_text('[not a reasoning object', encoding="utf-8")
        before = self.artifact_bytes()

        completed = self.accept()

        self.assertEqual(2, completed.returncode, completed.stdout + completed.stderr)
        body = self.payload(completed)
        self.assertEqual("INTERNAL_ERROR", body["reason_code"])
        self.assertIn(str(self.reasoning_path), body["reason"])
        for path, data in before.items():
            self.assertEqual(data, path.read_bytes() if path.is_file() else None,
                             f"{path.name} changed although the accept was refused")
        self.reasoning_path.write_text(original, encoding="utf-8")
        self.assertEqual(reasoning_count, len(self.chains()),
                         "the seven-node chain count must survive a corrupt read")

    def test_corrupt_evidence_store_is_refused_instead_of_appending(self) -> None:
        self.ready_candidate()
        self.evidence_path.write_text(
            self.evidence_path.read_text(encoding="utf-8") + "{ truncated record\n",
            encoding="utf-8")
        before = self.artifact_bytes()

        completed = self.accept()

        self.assertEqual(2, completed.returncode, completed.stdout + completed.stderr)
        body = self.payload(completed)
        self.assertEqual("INTERNAL_ERROR", body["reason_code"])
        self.assertIn(str(self.evidence_path), body["reason"])
        for path, data in before.items():
            self.assertEqual(data, path.read_bytes() if path.is_file() else None,
                             f"{path.name} changed although the accept was refused")


class JournalRecoveryTests(IntegrityHelpers):
    """B: an interrupted accept is reported and replayable, never silently kept."""

    def crash_after_judgments(self) -> str:
        """Interrupt after evidence + judgments, before the chain/candidate writes.

        On the A-07 implementation the interruption point is the third atomic
        replace (journal + evidence + judgments). The pre-A-07 implementation has
        no journal, so the child falls back to its own call order and exits inside
        ``_chain`` — right after it rewrote the judgment array. Either way the
        parent asserts a journal exists, which is exactly what the old code cannot
        offer.
        """
        candidate_id = self.ready_candidate()
        script = """
            import os
            import sys
            sys.path.insert(0, sys.argv[1])
            import issue_structuring
            try:
                import write_integrity
            except ImportError:
                write_integrity = None
            if write_integrity is None:
                def crashing_chain(*args, **kwargs):
                    os._exit(77)
                issue_structuring._chain = crashing_chain
            else:
                original = write_integrity.atomic_replace
                state = {"calls": 0}

                def crashing_replace(source, target):
                    original(source, target)
                    state["calls"] += 1
                    if state["calls"] == 3:
                        os._exit(77)

                write_integrity.atomic_replace = crashing_replace
            issue_structuring.accept_candidate(
                sys.argv[2], sys.argv[3], by="product-owner",
                context_key="nested-log-parse", judgment_id="D03", evidence_level="E2")
        """
        child = run_child(script, str(SCRIPTS), str(self.study), candidate_id)
        self.assertEqual(77, child.returncode, child.stdout + child.stderr)
        return candidate_id

    def test_dry_run_reports_completed_and_pending_items(self) -> None:
        self.crash_after_judgments()
        self.assertTrue(self.journal_path.is_file(), "the journal must outlive the crash")
        journal = json.loads(self.journal_path.read_text(encoding="utf-8"))
        self.assertEqual("askovo.write-journal", journal["kind"])
        self.assertEqual(5, len(journal["files"]))
        for entry in journal["files"]:
            self.assertTrue(entry["new_sha256"].startswith("sha256:"))
            self.assertIn("old_sha256", entry)
        before = self.artifact_bytes()

        dry = run_cli("recover", str(self.study))

        self.assertEqual(1, dry.returncode, dry.stdout + dry.stderr)
        body = self.payload(dry)
        self.assertEqual("incomplete", body["status"])
        self.assertIn("上次接受未完成", body["reason"])
        self.assertEqual(2, len(body["completed"]), body)
        self.assertEqual(3, len(body["pending"]), body)
        self.assertEqual(before, self.artifact_bytes(),
                         "a dry-run recover must not modify the study")
        self.assertTrue(self.journal_path.is_file())

    def test_apply_finishes_the_accept_and_leaves_no_orphan(self) -> None:
        candidate_id = self.crash_after_judgments()
        evidence_before = len(self.evidence())

        applied = run_cli("recover", str(self.study), "--apply")

        self.assertEqual(0, applied.returncode, applied.stdout + applied.stderr)
        self.assertEqual("completed", self.payload(applied)["status"])
        self.assertFalse(self.journal_path.exists(), "a completed recovery deletes its journal")
        records = self.evidence()
        self.assertEqual(evidence_before, len(records),
                         "recovery must not append the evidence a second time")
        accepted = self.candidates()[0]
        self.assertEqual(candidate_id, accepted["id"])
        self.assertEqual("accepted", accepted["status"])
        record_id = accepted["accepted"]["evidence_record_id"]
        judgments = [item for item in self.judgments() if item["id"] == "D03"]
        self.assertEqual(1, len(judgments), "exactly one judgment after recovery")
        self.assertEqual([record_id], judgments[0]["problem_evidence_ids"])
        chains = [item for item in self.chains() if item["demand_judgment_id"] == "D03"]
        self.assertEqual(1, len(chains), "exactly one chain after recovery")
        self.assertIn(record_id, chains[0]["nodes"]["need"]["evidence_ids"])
        self.assertEqual(1, len([item for item in self.trail()
                                 if item.get("status") == "accepted"]))
        # No evidence-only orphan: every record this candidate wrote is cited by
        # the judgment that recovery completed.
        written = [item for item in records
                   if item.get("issue_candidate_id") == candidate_id]
        cited = set(judgments[0]["problem_evidence_ids"])
        cited.update(judgments[0]["counter_evidence_ids"])
        for item in written:
            self.assertIn(item["record_id"], cited,
                          "an accepted candidate must not leave an uncited evidence record")
        again = run_cli("recover", str(self.study))
        self.assertEqual(0, again.returncode, again.stdout + again.stderr)
        self.assertEqual("none", self.payload(again)["status"])

    def test_any_entry_finishes_a_replayable_journal(self) -> None:
        self.crash_after_judgments()
        status = run_cli("status", str(self.study))
        self.assertEqual(0, status.returncode, status.stdout + status.stderr)
        body = self.payload(status)
        self.assertEqual("ready", body["state"], body)
        self.assertEqual(1, body["accepted"], body)
        self.assertIn("recovery", body)
        self.assertEqual("completed", body["recovery"]["status"])
        self.assertFalse(self.journal_path.exists())
        self.assertEqual(1, len([item for item in self.chains()
                                 if item["demand_judgment_id"] == "D03"]))

    def test_conflict_is_reported_and_blocks_writes(self) -> None:
        self.crash_after_judgments()
        # A third party edits a still-pending artifact: neither the recorded old
        # nor the recorded new bytes, so replay would overwrite human work.
        changed = json.loads(self.reasoning_path.read_text(encoding="utf-8"))
        changed["chains"] = []
        changed["manual_note"] = "edited after the crash"
        self.reasoning_path.write_text(json.dumps(changed, ensure_ascii=False, indent=2) + "\n",
                                      encoding="utf-8")
        conflict_bytes = self.reasoning_path.read_bytes()

        dry = run_cli("recover", str(self.study))
        self.assertEqual(2, dry.returncode, dry.stdout + dry.stderr)
        body = self.payload(dry)
        self.assertEqual("conflict", body["status"])
        self.assertIn("上次接受未完成", body["reason"])
        self.assertEqual(["04-findings/product-reasoning.json"],
                         [item["path"] for item in body["conflicts"]])
        self.assertTrue(body["completed"] and body["pending"] is not None)

        applied = run_cli("recover", str(self.study), "--apply")
        self.assertEqual(2, applied.returncode, applied.stdout + applied.stderr)
        self.assertEqual("conflict", self.payload(applied)["status"])
        self.assertEqual(conflict_bytes, self.reasoning_path.read_bytes(),
                         "a conflicted recovery must not overwrite the edited artifact")
        self.assertTrue(self.journal_path.is_file())

        blocked = run_cli("list", str(self.study))
        self.assertEqual(2, blocked.returncode, blocked.stdout + blocked.stderr)
        self.assertEqual("INTERNAL_ERROR", self.payload(blocked)["reason_code"])
        self.assertEqual(conflict_bytes, self.reasoning_path.read_bytes())

    def test_corrupt_journal_is_reported_not_ignored(self) -> None:
        self.crash_after_judgments()
        self.journal_path.write_text("{ broken journal", encoding="utf-8")
        dry = run_cli("recover", str(self.study))
        self.assertEqual(2, dry.returncode, dry.stdout + dry.stderr)
        self.assertEqual("corrupt", self.payload(dry)["status"])
        blocked = run_cli("status", str(self.study))
        self.assertEqual(2, blocked.returncode, blocked.stdout + blocked.stderr)
        self.assertEqual("INTERNAL_ERROR", self.payload(blocked)["reason_code"])


class WriteFailureTests(IntegrityHelpers):
    """B: an OSError mid-write leaves no half-completed state."""

    def test_oserror_during_apply_is_rolled_back(self) -> None:
        candidate_id = self.ready_candidate()
        before = self.artifact_bytes()
        script = """
            import json
            import os
            import sys
            sys.path.insert(0, sys.argv[1])
            import issue_structuring
            real_replace = os.replace
            state = {"calls": 0}

            def failing_replace(source, target):
                state["calls"] += 1
                if state["calls"] == 3:
                    raise OSError(28, "No space left on device")
                return real_replace(source, target)

            os.replace = failing_replace
            try:
                issue_structuring.accept_candidate(
                    sys.argv[2], sys.argv[3], by="product-owner",
                    context_key="nested-log-parse", judgment_id="D03",
                    evidence_level="E2")
                print(json.dumps({"status": "accepted"}))
            except issue_structuring.IssueError as exc:
                print(json.dumps({"status": "refused",
                                  "reason_code": exc.reason_code,
                                  "reason": str(exc)}))
        """
        child = run_child(script, str(SCRIPTS), str(self.study), candidate_id)
        self.assertEqual(0, child.returncode, child.stdout + child.stderr)
        lines = [line for line in child.stdout.splitlines() if line.strip().startswith("{")]
        self.assertTrue(lines, child.stdout + child.stderr)
        outcome = json.loads(lines[-1])
        self.assertEqual("refused", outcome["status"], outcome)
        self.assertEqual("INTERNAL_ERROR", outcome["reason_code"])
        for path, data in before.items():
            self.assertEqual(data, path.read_bytes() if path.is_file() else None,
                             f"{path.name} kept a half-written state")
        self.assertFalse(self.journal_path.exists(),
                         "a rolled-back write must not leave a journal")


class ConcurrentAcceptTests(IntegrityHelpers):
    """C: two processes accepting the same candidate cannot both write."""

    def test_two_concurrent_accepts_leave_one_judgment_and_no_lost_records(self) -> None:
        candidate_id = self.ready_candidate()
        gate = self.dir / "gate"
        gate.mkdir()
        evidence_before = len(self.evidence())
        script = """
            import json
            import sys
            import time
            from pathlib import Path
            sys.path.insert(0, sys.argv[1])
            import issue_structuring
            gate = Path(sys.argv[4])
            side = sys.argv[5]
            original = issue_structuring._load_candidates

            def gated(study_dir):
                document = original(study_dir)
                (gate / (side + ".loaded")).write_text("1", encoding="utf-8")
                deadline = time.time() + 2.0
                while time.time() < deadline:
                    if len(list(gate.glob("*.loaded"))) >= 2:
                        break
                    time.sleep(0.01)
                return document

            issue_structuring._load_candidates = gated
            try:
                result = issue_structuring.accept_candidate(
                    sys.argv[2], sys.argv[3], by="product-owner",
                    context_key="nested-log-parse", judgment_id="D03",
                    evidence_level="E2")
                print(json.dumps({"status": result.get("status"),
                                  "already_accepted": bool(result.get("already_accepted"))}))
            except Exception as exc:  # noqa: BLE001 - the child reports its own failure
                print(json.dumps({"status": "error", "error": str(exc)}))
        """
        env = dict(os.environ)
        env.setdefault("ASKOVO_AUTHOR_SALT", "a-07-write-integrity-test-salt")
        command = [sys.executable, "-c", textwrap.dedent(script), str(SCRIPTS),
                   str(self.study), candidate_id, str(gate)]
        first = subprocess.Popen(command + ["a"], stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, env=env)
        second = subprocess.Popen(command + ["b"], stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, env=env)
        first_out, first_err = first.communicate(timeout=120)
        second_out, second_err = second.communicate(timeout=120)
        self.assertEqual(0, first.returncode, first_out + first_err)
        self.assertEqual(0, second.returncode, second_out + second_err)
        outcomes = [json.loads(first_out.strip().splitlines()[-1]),
                    json.loads(second_out.strip().splitlines()[-1])]
        self.assertEqual("accepted", outcomes[0]["status"], outcomes)
        self.assertEqual("accepted", outcomes[1]["status"], outcomes)
        self.assertEqual([False, True],
                         sorted(item["already_accepted"] for item in outcomes),
                         "exactly one accept may do the write")
        self.assertEqual(evidence_before + 1, len(self.evidence()),
                         "a concurrent accept must not duplicate the evidence record")
        record_ids = [item["record_id"] for item in self.evidence()]
        self.assertEqual(len(record_ids), len(set(record_ids)),
                         "the evidence store must not gain a duplicate record id")
        self.assertEqual(1, len([item for item in self.judgments() if item["id"] == "D03"]))
        self.assertEqual(1, len([item for item in self.chains()
                                 if item["demand_judgment_id"] == "D03"]))
        self.assertEqual(1, len([item for item in self.trail()
                                 if item.get("status") == "accepted"]))
        self.assertFalse(self.journal_path.exists())


class SuccessPathTests(IntegrityHelpers):
    """The integrity layer must not change canonical semantics."""

    def test_accept_still_writes_four_valid_artifacts(self) -> None:
        candidate_id = self.ready_candidate()
        before_ids = [item["id"] for item in self.judgments()]

        completed = self.accept()

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        body = self.payload(completed)
        self.assertEqual("accepted", body["status"])
        self.assertFalse(body["already_accepted"])
        self.assertFalse(self.journal_path.exists())
        judgments = self.judgments()
        self.assertEqual(before_ids, [item["id"] for item in judgments if item["id"] != "D03"],
                         "existing judgments must be preserved byte-for-byte in order")
        accepted = self.candidates()[0]
        self.assertEqual(candidate_id, accepted["id"])
        self.assertEqual("accepted", accepted["status"])
        self.assertEqual("E2", accepted["accepted"]["evidence_level"])
        self.assertEqual(1, len([item for item in self.judgments() if item["id"] == "D03"]))

        validating = subprocess.run(
            [sys.executable, str(SCRIPTS / "validate_study.py"), str(self.study)],
            capture_output=True, text=True, timeout=120,
            env={**os.environ, "ASKOVO_AUTHOR_SALT": "a-07-write-integrity-test-salt"})
        self.assertEqual(0, validating.returncode,
                         validating.stdout + validating.stderr)
        audit = run_cli("status", str(self.study))
        self.assertEqual(0, audit.returncode, audit.stdout + audit.stderr)
        self.assertEqual("ready", self.payload(audit)["state"])


if __name__ == "__main__":
    unittest.main()
