#!/usr/bin/env python3
"""A-05 incremental research delta (AC A24-A28).

Frozen acceptance tests for `askovo delta`. The hard floor is that history is
never overwritten: every sync that changes the source produces a **new** snapshot
version, older versions stay byte-identical, and a new counter-evidence only
raises `needs_re_review` — it never rewrites an approved DecisionRecord.

Everything runs offline on synthetic GitHub issue exports.
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

SCHEMA = "askovo.decision-delta/1"
SNAPSHOT_SCHEMA = "askovo.decision-snapshot/1"
FOUR_BLOCKS = ("新增证据", "已影响节点", "反证影响", "建议是否重审")


def run_cli(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    merged = dict(os.environ)
    merged.setdefault("ASKOVO_AUTHOR_SALT", "a-05-frozen-test-salt")
    if env:
        merged.update(env)
    return subprocess.run([sys.executable, str(CLI), "delta", *args],
                          capture_output=True, text=True, timeout=120, env=merged)


def issue(number: int, title: str, body: str, *, author: str = "u1",
          author_id: int | None = None, **overrides) -> dict:
    record = {
        "id": 10000 + number,
        "number": number,
        "title": title,
        "body": body,
        "state": "open",
        "html_url": f"https://github.com/owner/repo/issues/{number}",
        "user": {"login": author, **({"id": author_id} if author_id is not None else {})},
        "author_association": "NONE",
        "created_at": "2026-09-01T10:00:00Z",
        "updated_at": "2026-09-01T10:00:00Z",
        "labels": [],
        "comments": [],
        "visibility": "public",
    }
    record.update(overrides)
    return record


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


class DeltaHelpers:
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.study = self.dir / "study"
        shutil.copytree(SAMPLE, self.study)
        self.base = [issue(1, "nested log parse failure",
                           "Nested JSON logs fail to parse; we retry by hand every week.",
                           author="alice", author_id=501),
                     issue(2, "add dark mode", "请加一个深色模式按钮。",
                           author="bob", author_id=502)]
        # The sample chain cites R01..R07; map one synthetic issue onto an
        # existing evidence id so "affected node" assertions are meaningful.
        self._link_issue_to_chain()

    def _link_issue_to_chain(self) -> None:
        path = self.study / "04-findings" / "product-reasoning.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["chains"][0]["nodes"]["pain"]["evidence_ids"] = ["github:10001"]
        payload["chains"][0]["nodes"]["scene"]["evidence_ids"] = ["github:10001"]
        payload["chains"][0]["counter_evidence_ids"] = []
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        # A-06 cross-ticket invariant: a chain that cites a record the evidence
        # store does not contain is a broken reference, and both the brief and the
        # delta now report it as stale. Keep the fixture internally consistent by
        # registering the cited record, so this file still tests the delta rather
        # than the stale gate.
        evidence = self.study / "02-data" / "evidence.jsonl"
        existing = [line for line in evidence.read_text(encoding="utf-8").splitlines()
                    if line.strip()] if evidence.is_file() else []
        existing.append(json.dumps({
            "record_id": "github:10001",
            "context_key": "synthetic-mobile-check",
            "user_role": "CLI user",
            "scene_trigger": "nested log parse failure",
            "task_outcome": "parse nested logs",
            "current_substitute": "manual retry",
            "friction_cost": "weekly manual work",
            "consequence": "delayed alerts",
            "evidence_level": "E2",
            "evidence_basis": "synthetic fixture record for the delta scenario",
            "corpus_role": "open_scene",
            "source_family": "github",
            "source_ref": "github:o/r#1",
            "normalized_text_hash": "sha256:fixture",
            "text": "Nested JSON logs fail to parse; we retry by hand every week.",
            "claim_type": "need",
            "evidence_form": "self_report",
        }, ensure_ascii=False))
        evidence.write_text("\n".join(existing) + "\n", encoding="utf-8")

    # -- fixture plumbing -------------------------------------------------- #

    def deltas_dir(self) -> Path:
        return self.study / "04-findings" / "deltas"

    def index_path(self) -> Path:
        return self.deltas_dir() / "index.jsonl"

    def state_path(self) -> Path:
        return self.deltas_dir() / "state.json"

    def versions(self) -> list[dict]:
        path = self.index_path()
        if not path.is_file():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()]

    def snapshot_dir(self, version: str) -> Path:
        return self.deltas_dir() / version

    def write_export(self, rows: list[dict], name: str = "issues.jsonl") -> Path:
        path = self.dir / name
        path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
                        encoding="utf-8")
        return path

    def sync(self, rows: list[dict], *extra: str, name: str = "issues.jsonl"
             ) -> tuple[subprocess.CompletedProcess, dict]:
        path = self.write_export(rows, name=name)
        completed = run_cli("sync", str(self.study), "--file", str(path),
                            "--authorized-by", "research-lead", *extra)
        try:
            return completed, json.loads(completed.stdout)
        except json.JSONDecodeError:
            return completed, {"raw": completed.stdout, "stderr": completed.stderr}

    def show(self, *extra: str) -> tuple[subprocess.CompletedProcess, dict]:
        completed = run_cli("show", str(self.study), *extra)
        try:
            return completed, json.loads(completed.stdout)
        except json.JSONDecodeError:
            return completed, {"raw": completed.stdout, "stderr": completed.stderr}

    def status(self) -> tuple[subprocess.CompletedProcess, dict]:
        completed = run_cli("status", str(self.study))
        try:
            return completed, json.loads(completed.stdout)
        except json.JSONDecodeError:
            return completed, {"raw": completed.stdout, "stderr": completed.stderr}

    def approve(self, *extra: str) -> tuple[subprocess.CompletedProcess, dict]:
        completed = run_cli("approve", str(self.study), "--by", "product-owner", *extra)
        try:
            return completed, json.loads(completed.stdout)
        except json.JSONDecodeError:
            return completed, {"raw": completed.stdout, "stderr": completed.stderr}

    def snapshot(self, version: str) -> dict:
        return json.loads((self.snapshot_dir(version) / "snapshot.json")
                          .read_text(encoding="utf-8"))

    def evidence_lines(self, version: str) -> list[dict]:
        path = self.snapshot_dir(version) / "evidence.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()]


class DeltaSyncTests(DeltaHelpers, unittest.TestCase):

    def test_first_sync_creates_a_versioned_snapshot(self) -> None:
        completed, payload = self.sync(self.base)
        self.assertEqual(0, completed.returncode, payload)
        self.assertTrue(payload["has_changes"])
        self.assertEqual(2, payload["counts"]["added"])
        self.assertEqual(1, len(self.versions()))
        version = self.versions()[0]["version"]
        self.assertTrue(version.startswith("v001-"), version)
        snapshot = self.snapshot(version)
        self.assertEqual(SNAPSHOT_SCHEMA, snapshot["schema"])
        for field in ("decision_id", "study_id", "question", "scope", "hypothesis_ids",
                      "evidence_snapshot_hash", "recommendation_snapshot_hash",
                      "chosen_option", "approval_ref", "approved_at", "next_validation",
                      "validation_receipts", "supersedes", "current_review_status"):
            self.assertIn(field, snapshot, f"DecisionSnapshot missing {field}")
        self.assertIsNone(snapshot["supersedes"])
        self.assertEqual(2, len(self.evidence_lines(version)))

    def test_repeat_sync_is_a_noop(self) -> None:
        self.sync(self.base)
        first_index = self.index_path().read_text(encoding="utf-8")
        before = self._tree_digest()
        completed, payload = self.sync(self.base)
        self.assertEqual(0, completed.returncode, payload)
        self.assertTrue(payload["noop"])
        self.assertFalse(payload["has_changes"])
        self.assertEqual(1, len(self.versions()), "a no-op must not create a new version")
        self.assertEqual(first_index, self.index_path().read_text(encoding="utf-8"))
        self.assertEqual(before, self._tree_digest(),
                         "a no-op sync must not rewrite a single byte")
        self.assertIn("无变化", payload["message"])

    def _tree_digest(self) -> dict:
        roots = [self.deltas_dir(), self.study / "06-report"]
        return {path.relative_to(self.study).as_posix(): sha(path)
                for root in roots if root.is_dir()
                for path in sorted(root.rglob("*")) if path.is_file()}

    def test_added_record_is_classified(self) -> None:
        self.sync(self.base)
        rows = self.base + [issue(3, "multiline traces",
                                  "Multiline stack traces break alerts.",
                                  author="carol", author_id=503,
                                  updated_at="2026-09-05T10:00:00Z")]
        _, payload = self.sync(rows)
        self.assertEqual(1, payload["counts"]["added"])
        self.assertEqual(0, payload["counts"]["changed"])
        self.assertEqual(0, payload["counts"]["deleted"])
        self.assertIn("github:10003", [item["source_id"] for item in payload["added"]])

    def test_changed_record_is_detected_by_update_time(self) -> None:
        self.sync(self.base)
        rows = json.loads(json.dumps(self.base))
        rows[0]["body"] = "Nested JSON logs fail to parse; we retry by hand every day now."
        rows[0]["updated_at"] = "2026-09-09T10:00:00Z"
        _, payload = self.sync(rows)
        self.assertEqual(1, payload["counts"]["changed"])
        changed = payload["changed"][0]
        self.assertEqual("github:10001", changed["source_id"])
        self.assertNotEqual(changed["previous_hash"], changed["current_hash"])
        self.assertIn("v001", changed["previous_ref"])
        self.assertIn("github:10001", changed["previous_ref"])
        self.assertIn("body", changed["fields"])

    def test_deleted_record_is_detected(self) -> None:
        self.sync(self.base)
        _, payload = self.sync([self.base[0]])
        self.assertEqual(1, payload["counts"]["deleted"])
        deleted = payload["deleted"][0]
        self.assertEqual("github:10002", deleted["source_id"])
        self.assertTrue(deleted["previous_ref"])
        self.assertTrue(deleted["acquisition_basis"])
        self.assertTrue(deleted["retention_rule"])

    def test_deletion_is_not_asserted_when_filters_change(self) -> None:
        self.sync(self.base)
        completed, payload = self.sync([self.base[0]], "--label", "bug")
        self.assertEqual(0, completed.returncode, payload)
        self.assertEqual(0, payload["counts"]["deleted"],
                         "a filtered export cannot prove deletion")
        self.assertEqual("not_asserted", payload["deletion_basis"])


class DeltaHistoryTests(DeltaHelpers, unittest.TestCase):
    """A25: history is append-only; deleted or edited records stay traceable."""

    def test_history_snapshots_are_never_overwritten(self) -> None:
        first_completed, first = self.sync(self.base)
        self.assertEqual(0, first_completed.returncode, first)
        self.assertTrue(first["has_changes"])
        version = self.versions()[0]["version"]
        before = {path.name: sha(path)
                  for path in self.snapshot_dir(version).iterdir() if path.is_file()}
        rows = json.loads(json.dumps(self.base))
        rows[0]["body"] = "Rewritten body."
        rows[0]["updated_at"] = "2026-09-10T10:00:00Z"
        second_completed, second = self.sync(rows)
        self.assertEqual(0, second_completed.returncode, second)
        self.assertTrue(second["has_changes"], "the second sync must really append a version")
        after = {path.name: sha(path)
                 for path in self.snapshot_dir(version).iterdir() if path.is_file()}
        self.assertEqual(before, after, "an old snapshot version must stay byte-identical")

    def test_deleted_record_keeps_previous_content(self) -> None:
        self.sync(self.base)
        version = self.versions()[0]["version"]
        self.sync([self.base[0]])
        preserved = [item for item in self.evidence_lines(version)
                     if item["source_id"] == "github:10002"]
        self.assertEqual(1, len(preserved))
        self.assertEqual("add dark mode", preserved[0]["title"],
                         "the deleted record keeps its previous content")

    def test_edited_record_keeps_the_previous_body(self) -> None:
        self.sync(self.base)
        version = self.versions()[0]["version"]
        rows = json.loads(json.dumps(self.base))
        rows[0]["body"] = "Rewritten body."
        rows[0]["updated_at"] = "2026-09-11T10:00:00Z"
        self.sync(rows)
        old = [item for item in self.evidence_lines(version)
               if item["source_id"] == "github:10001"][0]
        self.assertIn("retry by hand", old["body"])
        current = [item for item in self.evidence_lines(self.versions()[-1]["version"])
                   if item["source_id"] == "github:10001"][0]
        self.assertIn("Rewritten body", current["body"])

    def test_index_is_append_only(self) -> None:
        self.sync(self.base)
        first = self.index_path().read_text(encoding="utf-8")
        rows = self.base + [issue(3, "third", "third body", author="carol", author_id=503,
                                  updated_at="2026-09-06T10:00:00Z")]
        self.sync(rows)
        self.assertTrue(self.index_path().read_text(encoding="utf-8").startswith(first))
        self.assertEqual(2, len(self.versions()))
        self.assertEqual(self.versions()[0]["version"],
                         self.versions()[1]["supersedes"])

    def test_version_dirs_are_content_addressed(self) -> None:
        _, payload = self.sync(self.base)
        version = payload["version"]
        self.assertEqual(version, self.versions()[0]["version"])
        digest = hashlib.sha256(
            (self.snapshot_dir(version) / "evidence.jsonl").read_bytes()).hexdigest()
        self.assertTrue(version.startswith("v001-" + digest[:12]),
                        f"{version} must embed the evidence hash")

    def test_snapshot_hash_covers_evidence(self) -> None:
        _, payload = self.sync(self.base)
        snapshot = self.snapshot(payload["version"])
        digest = hashlib.sha256(
            (self.snapshot_dir(payload["version"]) / "evidence.jsonl").read_bytes()).hexdigest()
        self.assertEqual("sha256:" + digest, snapshot["evidence_snapshot_hash"])


class DeltaIdentityTests(DeltaHelpers, unittest.TestCase):
    """A26: an edited source is not a new user and not new evidence."""

    def test_author_rename_is_not_a_new_user(self) -> None:
        self.sync(self.base)
        rows = json.loads(json.dumps(self.base))
        rows[0]["user"] = {"login": "alice-renamed", "id": 501}
        rows[0]["updated_at"] = "2026-09-12T10:00:00Z"
        _, payload = self.sync(rows)
        self.assertEqual(0, payload["counts"]["added"], "a rename is not a new source")
        self.assertEqual(1, payload["counts"]["changed"])
        self.assertEqual(2, payload["identity"]["observed_users"])
        self.assertEqual([], payload["identity"]["identity_drift"],
                         "a stable user id proves the same person")

    def test_login_only_rename_is_flagged_not_counted(self) -> None:
        rows = json.loads(json.dumps(self.base))
        rows[0]["user"] = {"login": "alice"}
        rows[1]["user"] = {"login": "bob"}
        self.sync(rows)
        edited = json.loads(json.dumps(rows))
        edited[0]["user"] = {"login": "alice-new"}
        edited[0]["updated_at"] = "2026-09-12T10:00:00Z"
        _, payload = self.sync(edited)
        self.assertEqual(0, payload["counts"]["added"])
        self.assertEqual(2, payload["identity"]["observed_users"],
                         "a login rename must not add an observed user")
        self.assertTrue(payload["identity"]["identity_drift"])
        self.assertEqual("login_only", payload["identity"]["identity_basis"])

    def test_edit_never_becomes_new_evidence(self) -> None:
        self.sync(self.base)
        rows = json.loads(json.dumps(self.base))
        rows[1]["body"] = "完全重写：请加一个深色模式开关。"
        rows[1]["updated_at"] = "2026-09-13T10:00:00Z"
        _, payload = self.sync(rows)
        added_ids = [item["source_id"] for item in payload["added"]]
        self.assertNotIn("github:10002", added_ids)
        self.assertEqual(1, payload["counts"]["changed"])


class DeltaDocumentTests(DeltaHelpers, unittest.TestCase):

    def test_delta_carries_the_four_blocks(self) -> None:
        self.sync(self.base)
        completed, payload = self.show()
        self.assertEqual(0, completed.returncode, payload)
        self.assertEqual(SCHEMA, payload["schema"])
        for key in ("added", "affected_nodes", "counter_impact", "needs_re_review"):
            self.assertIn(key, payload)

    def test_affected_nodes_point_back_to_records(self) -> None:
        self.sync(self.base)
        rows = json.loads(json.dumps(self.base))
        rows[0]["body"] = "Nested JSON logs fail to parse; we retry by hand every day."
        rows[0]["updated_at"] = "2026-09-06T10:00:00Z"
        _, payload = self.sync(rows)
        affected = {item["record_id"]: item for item in payload["affected_nodes"]
                    if item["record_id"] == "github:10001"}
        self.assertTrue(affected, "a cited record must appear in affected_nodes")
        node = affected["github:10001"]
        self.assertEqual("PR01", node["chain_id"])
        self.assertIn("pain", node["nodes"])

    def test_counter_impact_lists_registered_counter_evidence(self) -> None:
        self.sync(self.base)
        path = self.study / "04-findings" / "product-reasoning.json"
        chain = json.loads(path.read_text(encoding="utf-8"))
        chain["chains"][0]["counter_evidence_ids"] = ["github:10003"]
        path.write_text(json.dumps(chain, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        rows = self.base + [issue(3, "does not happen here",
                                  "This does not happen for us; works fine.",
                                  author="skeptic", author_id=504,
                                  updated_at="2026-09-07T10:00:00Z")]
        _, payload = self.sync(rows)
        self.assertTrue(payload["counter_impact"])
        self.assertEqual("github:10003", payload["counter_impact"][0]["record_id"])

    def test_markdown_has_the_four_blocks(self) -> None:
        self.sync(self.base)
        rows = self.base + [issue(3, "third", "third body", author="carol", author_id=503,
                                  updated_at="2026-09-06T10:00:00Z")]
        self.sync(rows)
        markdown = (self.study / "06-report" / "decision-delta.md").read_text(encoding="utf-8")
        for block in FOUR_BLOCKS:
            self.assertIn(block, markdown, f"decision_delta.md missing {block}")
        self.assertIn("github:10003", markdown)

    def test_delta_is_deterministic(self) -> None:
        self.sync(self.base)
        rows = self.base + [issue(3, "third", "third body", author="carol", author_id=503,
                                  updated_at="2026-09-06T10:00:00Z")]
        _, first = self.sync(rows)
        _, second = self.show("--version", first["version"])
        self.assertEqual(first["digest"], second["digest"])


class DeltaAcceptedDecisionTests(DeltaHelpers, unittest.TestCase):
    """A27: new counter-evidence raises needs_re_review, never rewrites the record."""

    def _approve(self) -> Path:
        completed, payload = self.approve("--approval-ref", "SIGNOFF-001",
                                          "--option", "option-A")
        self.assertEqual(0, completed.returncode, payload)
        snapshots = self.study / "04-findings" / "deltas" / "decision-snapshots"
        return sorted(snapshots.glob("*.json"))[0]

    def test_approval_writes_one_decision_snapshot(self) -> None:
        self.sync(self.base)
        path = self._approve()
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual("SIGNOFF-001", payload["approval_ref"])
        self.assertEqual("product-owner", payload["approved_by"])
        self.assertEqual("declaration_only", payload["identity_basis"])
        self.assertEqual("option-A", payload["chosen_option"])
        self.assertTrue(payload["evidence_snapshot_hash"].startswith("sha256:"))

    def test_new_counter_evidence_marks_needs_re_review(self) -> None:
        self.sync(self.base)
        self._approve()
        path = self.study / "04-findings" / "product-reasoning.json"
        chain = json.loads(path.read_text(encoding="utf-8"))
        chain["chains"][0]["counter_evidence_ids"] = ["github:10003"]
        path.write_text(json.dumps(chain, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        rows = self.base + [issue(3, "does not happen here", "Works fine for us.",
                                  author="skeptic", author_id=504,
                                  updated_at="2026-09-08T10:00:00Z")]
        _, payload = self.sync(rows)
        self.assertTrue(payload["needs_re_review"])
        self.assertTrue(payload["review_basis"])

    def test_accepted_decision_is_never_mutated(self) -> None:
        self.sync(self.base)
        accepted_path = self._approve()
        before = sha(accepted_path)
        rows = self.base + [issue(3, "does not happen here", "Works fine for us.",
                                  author="skeptic", author_id=504,
                                  updated_at="2026-09-08T10:00:00Z")]
        self.sync(rows)
        self.assertEqual(before, sha(accepted_path),
                         "a delta must never rewrite an approved DecisionRecord")
        _, payload = self.show()
        self.assertFalse(payload["decision_record_mutated"])
        self.assertTrue(payload["accepted"])

    def test_delta_shows_current_versus_accepted(self) -> None:
        self.sync(self.base)
        self._approve()
        rows = self.base + [issue(3, "third", "third body", author="carol", author_id=503,
                                  updated_at="2026-09-08T10:00:00Z")]
        _, payload = self.sync(rows)
        self.assertTrue(payload["accepted"]["approval_ref"])
        self.assertTrue(payload["differences"], "current vs accepted must be explicit")
        self.assertIn("accepted_version", payload)

    def test_without_approval_there_is_no_accepted_baseline(self) -> None:
        self.sync(self.base)
        _, payload = self.show()
        self.assertIsNone(payload["accepted"])
        self.assertIn("approve", payload["next_required_action"])


class DeltaStaleTests(DeltaHelpers, unittest.TestCase):
    """A28: an unreachable source still shows the last good result, marked stale."""

    def test_unreachable_source_keeps_the_last_good_snapshot(self) -> None:
        self.sync(self.base)
        version = self.versions()[0]["version"]
        missing = self.dir / "missing.jsonl"
        completed = run_cli("sync", str(self.study), "--file", str(missing),
                            "--authorized-by", "research-lead")
        self.assertEqual(2, completed.returncode, completed.stdout + completed.stderr)
        completed, payload = self.show()
        # Exit 1 = a valid but degraded research status (repo convention: gate not
        # passed). The read still succeeds and shows the last good snapshot.
        self.assertEqual(1, completed.returncode, payload)
        self.assertTrue(payload["stale"])
        self.assertEqual("STALE_SOURCE", payload["reason_code"])
        self.assertTrue(payload["last_success_at"])
        self.assertTrue((self.snapshot_dir(version) / "evidence.jsonl").is_file())

    def test_stale_delta_never_pretends_to_be_fresh(self) -> None:
        self.sync(self.base)
        run_cli("sync", str(self.study), "--file", str(self.dir / "missing.jsonl"),
                "--authorized-by", "research-lead")
        _, payload = self.show()
        self.assertEqual("stale", payload["freshness"]["status"])
        self.assertTrue(payload["freshness"]["reason"])

    def test_sync_requires_authorization(self) -> None:
        path = self.write_export(self.base)
        completed = run_cli("sync", str(self.study), "--file", str(path))
        self.assertEqual(4, completed.returncode, completed.stdout + completed.stderr)
        body = json.loads(completed.stdout)
        self.assertEqual("AUTH_REQUIRED", body["reason_code"])
        self.assertEqual([], self.versions())

    def test_status_reports_versions_and_freshness(self) -> None:
        self.sync(self.base)
        completed, payload = self.status()
        self.assertEqual(0, completed.returncode, payload)
        self.assertEqual(1, payload["versions"])
        self.assertTrue(payload["latest_version"])
        self.assertEqual("fresh", payload["freshness"]["status"])
        self.assertTrue(payload["next_required_action"])


class DeltaDecideIntegrationTests(DeltaHelpers, unittest.TestCase):
    """A-05 replaces A-02's explicit `decide delta` refusal."""

    def _decide_task(self) -> tuple[Path, str]:
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
        started = subprocess.run(
            [sys.executable, str(CLI), "decide", "start", "--workspace", str(workspace),
             "--input", str(task_path), "--study", str(self.study)],
            capture_output=True, text=True, timeout=120)
        self.assertEqual(0, started.returncode, started.stdout + started.stderr)
        return workspace, json.loads(started.stdout)["task_id"]

    def test_decide_delta_returns_the_latest_delta(self) -> None:
        self.sync(self.base)
        workspace, task_id = self._decide_task()
        completed = subprocess.run(
            [sys.executable, str(CLI), "decide", "delta", task_id,
             "--workspace", str(workspace), "--since", "latest-accepted"],
            capture_output=True, text=True, timeout=120)
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(SCHEMA, payload["schema"])
        self.assertEqual("latest-accepted", payload["since"])

    def test_decide_delta_without_snapshot_is_explicit(self) -> None:
        workspace, task_id = self._decide_task()
        completed = subprocess.run(
            [sys.executable, str(CLI), "decide", "delta", task_id,
             "--workspace", str(workspace), "--since", "latest-accepted"],
            capture_output=True, text=True, timeout=120)
        self.assertEqual(2, completed.returncode, completed.stdout + completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual("INPUT_REQUIRED", payload["reason_code"])
        self.assertTrue(payload["next_required_action"])


if __name__ == "__main__":
    unittest.main()
