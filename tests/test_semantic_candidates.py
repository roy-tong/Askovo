"""Constrained semantic candidates: recall without letting a model decide truth.

The tests pin the hard rules: every candidate carries an existing record id and
an exact quote, ``unknowns`` is mandatory, ``status`` stays ``unverified``, a
model cannot write evidence levels, a critic pass precedes review, and only a
named accept can produce an E2 collected-statement observation.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/askovo/scripts"
CLI = SCRIPTS / "askovo.py"
MCP = SCRIPTS / "askovo_mcp.py"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import observation  # noqa: E402
import semantic_candidates  # noqa: E402


def run_cli(*args: str, env_extra: dict | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for key in ("ASKOVO_LLM_BASE", "ASKOVO_LLM_MODEL", "ASKOVO_LLM_KEY",
                "ASKOVO_SEMANTIC_PROVIDER", "ASKOVO_EMBED_BASE", "ASKOVO_EMBED_MODEL"):
        env.pop(key, None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        check=False, capture_output=True, text=True, env=env, timeout=120)


def default_records() -> list[dict]:
    return [
        {"record_id": "R01", "platform": "reddit", "evidence_level": "E1",
         "created_at": "2026-01-02T00:00:00Z", "source_url": "https://example.com/1",
         "text": ("Night alerts wake users, so they disable push notifications. "
                  "False alarms happen because thresholds are fixed.")},
        {"record_id": "R02", "platform": "reddit", "evidence_level": "E2",
         "created_at": "2026-02-03T00:00:00Z", "source_url": "https://example.com/2",
         "text": ("Users turn off night alerts because the alerts are too frequent "
                  "and wake the household. But some keep them for safety.")},
        {"record_id": "R03", "platform": "forum", "evidence_level": "E1",
         "created_at": "2026-02-10T00:00:00Z", "source_url": "https://example.com/3",
         "text": ("The app sends too many alerts at night. However, one user said "
                  "an alert helped catch a fire.")},
        {"record_id": "R04", "platform": "amazon", "evidence_level": "E2",
         "created_at": "2026-03-01T00:00:00Z", "source_url": "https://example.com/4",
         "text": "Price is high, but users renew anyway."},
    ]


def candidate(**overrides) -> dict:
    payload = {
        "candidate_id": "night-alert-fatigue",
        "kind": "theme",
        "statement": "用户把夜间误报视为需要主动关闭的打扰，而不是安全提醒。",
        "evidence_refs": [{"record_id": "R01", "quote": "Night alerts wake users"}],
        "unknowns": ["没有用户主动说明误报率阈值"],
        "status": "unverified",
    }
    payload.update(overrides)
    return payload


def document(candidates: list[dict]) -> dict:
    return {
        "schema": semantic_candidates.SCHEMA,
        "generator": semantic_candidates.GENERATOR,
        "generator_version": semantic_candidates.GENERATOR_VERSION,
        "model": "test-model",
        "prompt_hash": "sha256:prompt",
        "input_hash": "sha256:input",
        "created_at": "2026-11-24T00:00:00+00:00",
        "status": "unverified",
        "candidates": candidates,
    }


class SemanticFixture(unittest.TestCase):
    def make_study(self, records: list[dict] | None = None) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        study = Path(directory.name) / "study"
        (study / "02-data").mkdir(parents=True)
        (study / "study.json").write_text(json.dumps({
            "title": "Semantic fixture study",
            "decision": {"question": "Should night alerts change?"},
        }), encoding="utf-8")
        rows = records if records is not None else default_records()
        with (study / "02-data" / "evidence.jsonl").open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        return study

    def run_offline(self, study: Path, **kwargs) -> dict:
        records = semantic_candidates.load_records(study)
        return semantic_candidates.run_semantic_analysis(
            study, records, provider="offline", **kwargs)

    def first_candidate(self, study: Path) -> str:
        payload = semantic_candidates.load_candidates(study)
        return payload["candidates"][0]["candidate_id"]


class CandidateValidationTests(SemanticFixture):
    def test_a_valid_candidate_passes(self) -> None:
        study = self.make_study()
        records = semantic_candidates.records_by_id(semantic_candidates.load_records(study))
        errors = semantic_candidates.validate_candidate_document(
            document([candidate()]), records)
        self.assertEqual([], errors)

    def test_quote_must_be_a_substring_of_the_record(self) -> None:
        study = self.make_study()
        records = semantic_candidates.records_by_id(semantic_candidates.load_records(study))
        bad = candidate(evidence_refs=[{"record_id": "R01", "quote": "这句话不在原文里"}])
        errors = semantic_candidates.validate_candidate_document(document([bad]), records)
        self.assertTrue(any("substring" in item for item in errors))

    def test_unknown_record_id_is_rejected(self) -> None:
        study = self.make_study()
        records = semantic_candidates.records_by_id(semantic_candidates.load_records(study))
        bad = candidate(evidence_refs=[{"record_id": "R99", "quote": "Night alerts"}])
        errors = semantic_candidates.validate_candidate_document(document([bad]), records)
        self.assertTrue(any("does not exist" in item for item in errors))

    def test_ambiguous_record_ids_are_rejected_before_citation(self) -> None:
        records = [
            {"record_id": "shared", "platform": "reddit", "text": "same quoted words"},
            {"record_id": "shared", "platform": "forum", "text": "same quoted words"},
        ]
        with self.assertRaises(semantic_candidates.SemanticError) as caught:
            semantic_candidates.records_by_id(records)
        self.assertEqual("INPUT_REQUIRED", caught.exception.reason_code)

    def test_unknowns_are_mandatory(self) -> None:
        study = self.make_study()
        records = semantic_candidates.records_by_id(semantic_candidates.load_records(study))
        errors = semantic_candidates.validate_candidate_document(
            document([candidate(unknowns=[])]), records)
        self.assertTrue(any("unknowns" in item for item in errors))

    def test_status_cannot_be_validated(self) -> None:
        study = self.make_study()
        records = semantic_candidates.records_by_id(semantic_candidates.load_records(study))
        errors = semantic_candidates.validate_candidate_document(
            document([candidate(status="validated")]), records)
        self.assertTrue(any("status must be" in item for item in errors))
        top_level = document([candidate()])
        top_level["status"] = "validated"
        errors = semantic_candidates.validate_candidate_document(top_level, records)
        self.assertTrue(any("candidates are never validated" in item for item in errors))

    def test_model_cannot_declare_an_evidence_level(self) -> None:
        study = self.make_study()
        records = semantic_candidates.records_by_id(semantic_candidates.load_records(study))
        raw = candidate()
        raw["evidence_level"] = "E2"
        accepted, rejected = semantic_candidates.parse_candidates(
            {"candidates": [raw]}, records, batch_index=1)
        self.assertEqual([], accepted)
        self.assertIn("evidence_level", rejected[0]["reason"])

    def test_model_cannot_declare_a_non_unverified_status(self) -> None:
        study = self.make_study()
        records = semantic_candidates.records_by_id(semantic_candidates.load_records(study))
        raw = candidate(status="accepted")
        accepted, rejected = semantic_candidates.parse_candidates(
            {"candidates": [raw]}, records, batch_index=1)
        self.assertEqual([], accepted)
        self.assertIn("status", rejected[0]["reason"])

    def test_parse_injects_record_platform_and_level(self) -> None:
        study = self.make_study()
        records = semantic_candidates.records_by_id(semantic_candidates.load_records(study))
        accepted, rejected = semantic_candidates.parse_candidates(
            {"candidates": [candidate()]}, records, batch_index=2)
        self.assertEqual([], rejected)
        ref = accepted[0]["evidence_refs"][0]
        self.assertEqual("reddit", ref["platform"])
        self.assertEqual("E1", ref["evidence_level"])
        self.assertEqual([2], accepted[0]["batches"])

    def test_duplicate_statements_in_one_batch_merge_refs(self) -> None:
        study = self.make_study()
        records = semantic_candidates.records_by_id(semantic_candidates.load_records(study))
        second = candidate(candidate_id="other-id",
                           evidence_refs=[{"record_id": "R02",
                                           "quote": "Users turn off night alerts"}])
        accepted, _ = semantic_candidates.parse_candidates(
            {"candidates": [candidate(), second]}, records, batch_index=1)
        self.assertEqual(1, len(accepted))
        self.assertEqual(2, len(accepted[0]["evidence_refs"]))

    def test_id_collision_with_a_different_statement_is_renamed(self) -> None:
        study = self.make_study()
        records = semantic_candidates.records_by_id(semantic_candidates.load_records(study))
        second = candidate(statement="另一个不同的主题陈述需要单独保留。",
                           evidence_refs=[{"record_id": "R03",
                                           "quote": "The app sends too many alerts"}])
        renamed: list[dict] = []
        accepted, _ = semantic_candidates.parse_candidates(
            {"candidates": [candidate(), second]}, records, batch_index=1,
            renamed=renamed)
        self.assertEqual(2, len(accepted))
        self.assertEqual(1, len(renamed))
        self.assertTrue(accepted[1]["candidate_id"].startswith("night-alert-fatigue~"))

    def test_cross_batch_duplicates_merge(self) -> None:
        first = candidate()
        second = candidate(batches=[2], evidence_refs=[
            {"record_id": "R02", "quote": "Users turn off night alerts",
             "platform": "reddit", "evidence_level": "E2"}])
        merged = semantic_candidates.merge_candidates([first, second])
        self.assertEqual(1, len(merged))
        self.assertEqual(2, len(merged[0]["evidence_refs"]))

    def test_forbidden_conclusion_field_is_refused(self) -> None:
        study = self.make_study()
        records = semantic_candidates.records_by_id(semantic_candidates.load_records(study))
        errors = semantic_candidates.validate_candidate(
            candidate(demand_claim="strong"), records)
        self.assertTrue(any("demand_claim" in item for item in errors))


class OfflineRunTests(SemanticFixture):
    def test_offline_run_writes_valid_candidates_critic_and_report(self) -> None:
        study = self.make_study()
        result = self.run_offline(study)
        self.assertEqual("complete", result["status"])
        payload = semantic_candidates.load_candidates(study)
        records = semantic_candidates.records_by_id(semantic_candidates.load_records(study))
        self.assertEqual([], semantic_candidates.validate_candidate_document(payload, records))
        self.assertTrue(payload["candidates"])
        critic = semantic_candidates.load_critic(study)
        for item in payload["candidates"]:
            self.assertIn(item["candidate_id"], critic["candidates"])
            self.assertIn("coverage_gaps", critic["candidates"][item["candidate_id"]])
        self.assertTrue((study / semantic_candidates.MARKDOWN_REL).is_file())
        markdown = (study / semantic_candidates.MARKDOWN_REL).read_text(encoding="utf-8")
        self.assertIn("未验证", markdown)
        self.assertIn("覆盖缺口", markdown)

    def test_selection_cap_is_respected(self) -> None:
        study = self.make_study()
        result = self.run_offline(study, max_records=2, batch_size=1)
        self.assertEqual(2, result["selected"])
        self.assertEqual(2, len(result["batches"]))
        self.assertGreaterEqual(len(result["selection"]["months"]), 2)

    def test_keyword_retrieval_ranks_the_question_match_first(self) -> None:
        study = self.make_study()
        records = semantic_candidates.load_records(study)
        selected, summary = semantic_candidates.select_records(
            records, "price renew", semantic_candidates.record_text,
            max_records=4, retrieval="keyword", study_dir=study,
            allow_external=False)
        self.assertEqual("R04", selected[0]["record_id"])
        self.assertEqual("keyword", summary["used"])

    def test_missing_embedding_config_falls_back_to_keyword(self) -> None:
        study = self.make_study()
        records = semantic_candidates.load_records(study)
        with mock.patch.dict(os.environ, {}, clear=True):
            selected, summary = semantic_candidates.select_records(
                records, "night alerts", semantic_candidates.record_text,
                max_records=4, retrieval="auto", study_dir=study,
                allow_external=False)
        self.assertTrue(selected)
        self.assertEqual("keyword", summary["used"])
        self.assertIn("ASKOVO_EMBED", summary["error"])

    def test_explicit_embedding_without_config_fails_loudly(self) -> None:
        study = self.make_study()
        records = semantic_candidates.load_records(study)
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(semantic_candidates.SemanticUnavailable):
                semantic_candidates.select_records(
                    records, "night", semantic_candidates.record_text,
                    max_records=4, retrieval="embedding", study_dir=study,
                    allow_external=False)

    def test_remote_endpoint_requires_explicit_authorization(self) -> None:
        with self.assertRaises(semantic_candidates.SemanticUnavailable) as caught:
            semantic_candidates.run_semantic_analysis(
                self.make_study(), [], question="x", provider="openai",
                allow_external=False)
        self.assertEqual("INPUT_REQUIRED", caught.exception.reason_code)
        with mock.patch.dict(os.environ, {
                "ASKOVO_LLM_BASE": "https://api.example.com/v1",
                "ASKOVO_LLM_MODEL": "m"}, clear=False):
            with self.assertRaises(semantic_candidates.SemanticUnavailable) as caught:
                semantic_candidates.run_semantic_analysis(
                    self.make_study(), [], question="x", provider="openai",
                    allow_external=False)
        self.assertEqual("EXTERNAL_NOT_AUTHORIZED", caught.exception.reason_code)

    def test_loopback_endpoints_do_not_need_the_external_flag(self) -> None:
        semantic_candidates._require_transport_allowed("http://localhost:11434/v1", False)
        semantic_candidates._require_transport_allowed("http://127.0.0.1:8080/v1", False)
        with self.assertRaises(semantic_candidates.SemanticUnavailable):
            semantic_candidates._require_transport_allowed("http://api.example.com/v1", True)
        semantic_candidates._require_transport_allowed("https://api.example.com/v1", True)

    def test_model_requests_do_not_follow_redirects_or_forward_credentials(self) -> None:
        received = []

        class Sink(BaseHTTPRequestHandler):
            def do_GET(self):
                received.append(self.headers.get("Authorization"))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"choices":[{"message":{"content":"{}"}}]}')

            def log_message(self, *args):
                return

        sink = ThreadingHTTPServer(("127.0.0.1", 0), Sink)

        class Redirect(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                self.send_response(302)
                self.send_header("Location", "http://127.0.0.1:%d/sink" % sink.server_port)
                self.end_headers()

            def log_message(self, *args):
                return

        redirect = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
        for server in (sink, redirect):
            threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            provider = semantic_candidates.OpenAICompatibleProvider(
                "http://127.0.0.1:%d/v1" % redirect.server_port, "secret-token", "m")
            with self.assertRaises(semantic_candidates.SemanticUnavailable):
                provider.complete([{"role": "user", "content": "private corpus"}])
            self.assertEqual([], received)
        finally:
            for server in (redirect, sink):
                server.shutdown()
                server.server_close()

    def test_no_configuration_skips_without_writing_candidates(self) -> None:
        study = self.make_study()
        records = semantic_candidates.load_records(study)
        report_path = study / semantic_candidates.REPORT_REL
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text('{"status": "sentinel"}\n', encoding="utf-8")
        with mock.patch.dict(os.environ, {}, clear=True):
            result = semantic_candidates.run_semantic_analysis(study, records)
        self.assertEqual("skipped", result["status"])
        self.assertIn("no ASKOVO_LLM", result["reason"])
        self.assertFalse((study / semantic_candidates.CANDIDATES_REL).exists())
        self.assertEqual('{"status": "sentinel"}\n',
                         report_path.read_text(encoding="utf-8"))

    def test_prompt_marks_records_as_untrusted_data(self) -> None:
        study = self.make_study()
        records = semantic_candidates.load_records(study)[:1]
        messages, prompt_hash = semantic_candidates.build_batch_messages(
            "night alerts", records, semantic_candidates.record_text)
        self.assertIn("untrusted data", messages[0]["content"].lower())
        self.assertIn("R01", messages[1]["content"])
        self.assertTrue(prompt_hash.startswith("sha256:"))

    def test_critic_prompt_includes_uncited_records(self) -> None:
        study = self.make_study()
        records = semantic_candidates.load_records(study)
        by_id = semantic_candidates.records_by_id(records)
        messages = semantic_candidates.build_critic_messages(
            candidate(), by_id, records, semantic_candidates.record_text)
        self.assertIn("critic", messages[0]["content"].lower())
        payload = json.loads(messages[1]["content"].split("RECORDS_JSON: ")[1])
        record_ids = [item["record_id"] for item in payload["records"]]
        self.assertEqual(["R02", "R03", "R04"], record_ids)


class ReviewExportTests(SemanticFixture):
    def test_review_requires_a_critic_pass(self) -> None:
        study = self.make_study()
        records = semantic_candidates.records_by_id(semantic_candidates.load_records(study))
        (study / semantic_candidates.CANDIDATES_REL).parent.mkdir(parents=True, exist_ok=True)
        (study / semantic_candidates.CANDIDATES_REL).write_text(
            json.dumps(document([candidate()])), encoding="utf-8")
        with self.assertRaises(semantic_candidates.SemanticError) as caught:
            semantic_candidates.review_candidate(
                study, "night-alert-fatigue", "accept", reviewer="alice")
        self.assertEqual("REVIEW_REQUIRED", caught.exception.reason_code)

    def test_accept_is_append_only_and_idempotent(self) -> None:
        study = self.make_study()
        self.run_offline(study)
        candidate_id = self.first_candidate(study)
        first = semantic_candidates.review_candidate(
            study, candidate_id, "accept", reviewer="alice", note="quotes checked")
        second = semantic_candidates.review_candidate(
            study, candidate_id, "accept", reviewer="alice", note="quotes checked")
        rows = semantic_candidates.load_reviews(study)
        self.assertEqual("reviewed", first["status"])
        self.assertEqual("unchanged", second["status"])
        self.assertEqual(1, len(rows))
        self.assertEqual("accepted_for_export", rows[0]["status_after"])
        path = study / semantic_candidates.CANDIDATES_REL
        document = json.loads(path.read_text(encoding="utf-8"))
        target = next(item for item in document["candidates"]
                      if item["candidate_id"] == candidate_id)
        target["statement"] = target["statement"] + "（重写）"
        path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        third = semantic_candidates.review_candidate(
            study, candidate_id, "accept", reviewer="alice", note="quotes checked")
        self.assertEqual("reviewed", third["status"])
        self.assertEqual(2, len(semantic_candidates.load_reviews(study)))

    def test_changed_critic_requires_a_new_review_and_unblocks_export(self) -> None:
        study = self.make_study()
        self.run_offline(study)
        candidate_id = self.first_candidate(study)
        semantic_candidates.review_candidate(
            study, candidate_id, "accept", reviewer="alice", note="quotes checked")
        critic_path = study / semantic_candidates.CRITIC_REL
        critic = json.loads(critic_path.read_text(encoding="utf-8"))
        critique = critic["candidates"][candidate_id]
        critique["needs_more_evidence"] = list(
            critique.get("needs_more_evidence") or []) + ["补充独立来源"]
        critic_path.write_text(json.dumps(critic, ensure_ascii=False), encoding="utf-8")
        again = semantic_candidates.review_candidate(
            study, candidate_id, "accept", reviewer="alice", note="quotes checked")
        self.assertEqual("reviewed", again["status"])
        self.assertEqual(2, len(semantic_candidates.load_reviews(study)))
        store = study / "01-sources" / "semantic-observations"
        result = semantic_candidates.export_observations(study, store, by="alice")
        self.assertEqual(1, result["exported_count"])
        self.assertEqual([], [row for row in result["skipped"]
                              if "stale critic" in row["reason"]])

    def test_reject_needs_a_reason(self) -> None:
        study = self.make_study()
        self.run_offline(study)
        candidate_id = self.first_candidate(study)
        with self.assertRaises(semantic_candidates.SemanticError) as caught:
            semantic_candidates.review_candidate(
                study, candidate_id, "reject", reviewer="alice")
        self.assertEqual("INPUT_REQUIRED", caught.exception.reason_code)

    def test_unknown_candidate_is_refused(self) -> None:
        study = self.make_study()
        self.run_offline(study)
        with self.assertRaises(semantic_candidates.SemanticError) as caught:
            semantic_candidates.review_candidate(
                study, "not-a-candidate", "accept", reviewer="alice")
        self.assertEqual("INPUT_REQUIRED", caught.exception.reason_code)

    def test_changed_evidence_makes_the_candidate_stale(self) -> None:
        study = self.make_study()
        self.run_offline(study)
        candidate_id = self.first_candidate(study)
        path = study / "02-data" / "evidence.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        for row in rows:
            if row["record_id"] == "R01":
                row["text"] = "Completely rewritten text with no original quote."
        path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
                        encoding="utf-8")
        with self.assertRaises(semantic_candidates.SemanticError) as caught:
            semantic_candidates.review_candidate(
                study, candidate_id, "accept", reviewer="alice")
        self.assertEqual("STALE_SOURCE", caught.exception.reason_code)

    def test_contradicted_support_blocks_export(self) -> None:
        study = self.make_study()
        self.run_offline(study)
        candidate_id = self.first_candidate(study)
        semantic_candidates.review_candidate(
            study, candidate_id, "accept", reviewer="alice", note="quotes checked")
        semantic_candidates.assess_support(
            study, candidate_id, entailment="contradicted", context_intact=False,
            generalization_risk="high", reviewer="alice", checker="human",
            note="R02 says the opposite")
        store = study / "01-sources" / "semantic-observations"
        result = semantic_candidates.export_observations(study, store, by="alice")
        self.assertEqual(0, result["exported_count"])
        self.assertEqual(1, result["support"]["contradicted"])
        self.assertIn("contradicted", result["skipped"][0]["reason"])

    def test_unsupported_support_needs_a_named_override(self) -> None:
        study = self.make_study()
        self.run_offline(study)
        candidate_id = self.first_candidate(study)
        semantic_candidates.review_candidate(
            study, candidate_id, "accept", reviewer="alice", note="quotes checked")
        with self.assertRaises(semantic_candidates.SemanticError):
            semantic_candidates.assess_support(
                study, candidate_id, entailment="unsupported", context_intact=True,
                generalization_risk="medium", reviewer="alice")
        semantic_candidates.assess_support(
            study, candidate_id, entailment="unsupported", context_intact=True,
            generalization_risk="medium", reviewer="alice", override=True,
            note="quotes are adjacent but do not entail the stronger claim")
        store = study / "01-sources" / "semantic-observations"
        result = semantic_candidates.export_observations(study, store, by="alice")
        self.assertEqual(1, result["exported_count"])
        exported = json.loads((store / (result["exported"][0]["observation_id"] + ".json"))
                              .read_text(encoding="utf-8"))
        self.assertEqual("unsupported",
                         exported["semantic_provenance"]["support"])

    def test_partial_support_exports_with_a_warning(self) -> None:
        study = self.make_study()
        self.run_offline(study)
        candidate_id = self.first_candidate(study)
        semantic_candidates.review_candidate(
            study, candidate_id, "accept", reviewer="alice", note="quotes checked")
        semantic_candidates.assess_support(
            study, candidate_id, entailment="partial", context_intact=True,
            generalization_risk="low", reviewer="alice", note="one quote only")
        store = study / "01-sources" / "semantic-observations"
        result = semantic_candidates.export_observations(study, store, by="alice")
        self.assertEqual(1, result["exported_count"])
        self.assertEqual(1, len(result["support_warnings"]))

    def test_added_counterevidence_blocks_export_until_historical_snapshot(self) -> None:
        study = self.make_study()
        self.run_offline(study)
        candidate_id = self.first_candidate(study)
        semantic_candidates.review_candidate(
            study, candidate_id, "accept", reviewer="alice", note="quotes checked")
        declared = semantic_candidates.load_candidates(study)["corpus_snapshot"]
        path = study / "02-data" / "evidence.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        rows.append({
            "record_id": "R05", "platform": "forum", "evidence_level": "E1",
            "created_at": "2026-04-01T00:00:00Z", "source_url": "https://example.com/5",
            "text": "Later users say night alerts are useful and should stay on.",
        })
        path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
                        encoding="utf-8")
        with self.assertRaises(semantic_candidates.SemanticError) as caught:
            semantic_candidates.review_candidate(
                study, candidate_id, "accept", reviewer="alice", note="quotes checked")
        self.assertEqual("STALE_SOURCE", caught.exception.reason_code)
        store = study / "01-sources" / "semantic-observations"
        with self.assertRaises(semantic_candidates.SemanticError) as caught:
            semantic_candidates.export_observations(study, store, by="alice")
        self.assertEqual("STALE_CORPUS", caught.exception.reason_code)
        historical = semantic_candidates.export_observations(
            study, store, by="alice", against_snapshot=declared["records_sha256"])
        self.assertTrue(historical["historical_corpus"])
        self.assertEqual(1, historical["exported_count"])
        exported = json.loads((store / (historical["exported"][0]["observation_id"] + ".json"))
                              .read_text(encoding="utf-8"))
        self.assertEqual("historical", exported["semantic_provenance"]["corpus_binding"])

    def test_export_skips_unreviewed_and_other_reviewers(self) -> None:
        study = self.make_study()
        self.run_offline(study)
        payload = semantic_candidates.load_candidates(study)
        first = payload["candidates"][0]["candidate_id"]
        second = payload["candidates"][1]["candidate_id"] if len(payload["candidates"]) > 1 else ""
        semantic_candidates.review_candidate(
            study, first, "accept", reviewer="alice", note="ok")
        if second:
            semantic_candidates.review_candidate(
                study, second, "accept", reviewer="bob", note="ok")
        store = study / "01-sources" / "semantic-observations"
        result = semantic_candidates.export_observations(
            study, store, by="alice")
        self.assertEqual(1, result["exported_count"])
        if second:
            self.assertTrue(any(item["reason"].startswith("accepted by a different reviewer")
                                for item in result["skipped"]))
        exported_ids = {item["candidate_id"] for item in result["exported"]}
        self.assertEqual({first}, exported_ids)

    def test_export_produces_an_e2_collected_statement(self) -> None:
        study = self.make_study()
        self.run_offline(study)
        candidate_id = self.first_candidate(study)
        semantic_candidates.review_candidate(
            study, candidate_id, "accept", reviewer="alice", note="quote reviewed")
        store = study / "01-sources" / "semantic-observations"
        result = semantic_candidates.export_observations(study, store, by="alice")
        self.assertEqual(1, result["exported_count"])
        target = store / ("%s.json" % result["exported"][0]["observation_id"])
        payload = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(observation.COLLECTED_SOURCE_KIND, payload["source_kind"])
        claim = payload["claims"][0]
        self.assertEqual("E2", claim["evidence_level"])
        self.assertEqual(observation.COLLECTED_BASIS, claim["basis"])
        self.assertEqual([], observation.validate_observation(payload))
        self.assertFalse((study / "02-data" / "evidence.jsonl").read_text(
            encoding="utf-8").count("collected_corpus_statement"))

    def test_observation_export_keeps_the_collected_source_kind(self) -> None:
        study = self.make_study()
        self.run_offline(study)
        candidate_id = self.first_candidate(study)
        semantic_candidates.review_candidate(
            study, candidate_id, "accept", reviewer="alice", note="ok")
        store = study / "01-sources" / "semantic-observations"
        semantic_candidates.export_observations(study, store, by="alice")
        code = observation.cmd_export(SimpleNamespace(
            store=str(store), study=str(study), json=False))
        lines = [json.loads(line) for line in
                 (study / observation.EXPORT_REL).read_text(encoding="utf-8").splitlines()]
        self.assertEqual(0, code)
        self.assertEqual(observation.COLLECTED_SOURCE_KIND, lines[0]["source_kind"])
        self.assertIn("collected", lines[0]["boundary"])

    def test_export_refuses_a_review_for_an_older_candidate_revision(self) -> None:
        study = self.make_study()
        self.run_offline(study)
        candidate_id = self.first_candidate(study)
        semantic_candidates.review_candidate(
            study, candidate_id, "accept", reviewer="alice", note="ok")
        path = study / semantic_candidates.CANDIDATES_REL
        document = json.loads(path.read_text(encoding="utf-8"))
        target = next(item for item in document["candidates"]
                      if item["candidate_id"] == candidate_id)
        target["statement"] = target["statement"] + "（语义重写）"
        path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        result = semantic_candidates.export_observations(
            study, study / "01-sources" / "semantic-observations", by="alice")
        self.assertEqual(0, result["exported_count"])
        self.assertTrue(any("stale for this candidate revision" in item["reason"]
                            for item in result["skipped"]))
        listed = semantic_candidates.list_semantics(study)
        row = next(item for item in listed["candidates"]
                   if item["candidate_id"] == candidate_id)
        self.assertTrue(row["review"]["stale"])

    def test_export_refuses_a_review_for_an_older_critic_revision(self) -> None:
        study = self.make_study()
        self.run_offline(study)
        candidate_id = self.first_candidate(study)
        semantic_candidates.review_candidate(
            study, candidate_id, "accept", reviewer="alice", note="ok")
        path = study / semantic_candidates.CRITIC_REL
        critic = json.loads(path.read_text(encoding="utf-8"))
        critic["candidates"][candidate_id]["needs_more_evidence"].append(
            "new counter-evidence requires another review")
        path.write_text(json.dumps(critic, ensure_ascii=False), encoding="utf-8")
        result = semantic_candidates.export_observations(
            study, study / "01-sources" / "semantic-observations", by="alice")
        self.assertEqual(0, result["exported_count"])
        self.assertTrue(any("stale critic" in item["reason"]
                            for item in result["skipped"]))

    def test_export_is_idempotent(self) -> None:
        study = self.make_study()
        self.run_offline(study)
        candidate_id = self.first_candidate(study)
        semantic_candidates.review_candidate(
            study, candidate_id, "accept", reviewer="alice", note="ok")
        store = study / "01-sources" / "semantic-observations"
        first = semantic_candidates.export_observations(study, store, by="alice")
        second = semantic_candidates.export_observations(study, store, by="alice")
        self.assertEqual(1, first["exported_count"])
        self.assertEqual(0, second["exported_count"])
        self.assertTrue(any("already exported" in item["reason"]
                            for item in second["skipped"]))

    def test_semantic_list_reports_review_state(self) -> None:
        study = self.make_study()
        self.run_offline(study)
        candidate_id = self.first_candidate(study)
        semantic_candidates.review_candidate(
            study, candidate_id, "reject", reviewer="alice", note="too vague")
        payload = semantic_candidates.list_semantics(study)
        row = next(item for item in payload["candidates"]
                   if item["candidate_id"] == candidate_id)
        self.assertEqual("reject", row["review"]["decision"])
        self.assertEqual("alice", row["review"]["reviewer"])


class HostModeTests(SemanticFixture):
    def make_request(self, study: Path) -> dict:
        report = semantic_candidates.run_semantic_analysis(
            study, semantic_candidates.load_records(study),
            provider="host", question="night alerts")
        self.assertEqual("host_requested", report["status"])
        return json.loads((study / semantic_candidates.HOST_REQUEST_REL).read_text(encoding="utf-8"))

    def response(self, request: dict, **overrides) -> dict:
        payload = {
            "schema": semantic_candidates.HOST_RESPONSE_SCHEMA,
            "nonce": request["nonce"],
            "producer_id": "claude-code",
            "single_agent": False,
            "candidates": [{
                "kind": "theme",
                "statement": "夜间误报让用户主动关闭提醒，而不是把它当作安全功能。",
                "evidence_refs": [{"record_id": "R01", "quote": "Night alerts wake users"}],
                "unknowns": ["没有误报率阈值"],
            }],
        }
        payload.update(overrides)
        return payload

    def test_host_request_import_review_and_export(self) -> None:
        study = self.make_study()
        request = self.make_request(study)
        self.assertFalse((study / semantic_candidates.CANDIDATES_REL).exists())
        report = semantic_candidates.import_host_response(
            study, self.response(request), by="alice")
        self.assertEqual("imported", report["status"])
        self.assertEqual(1, report["candidates"])
        listed = semantic_candidates.list_semantics(study)
        candidate_id = listed["candidates"][0]["candidate_id"]
        self.assertTrue(candidate_id.startswith("host-"))
        semantic_candidates.review_candidate(
            study, candidate_id, "accept", reviewer="alice", note="checked")
        store = study / "01-sources" / "semantic-observations"
        exported = semantic_candidates.export_observations(study, store, by="alice")
        self.assertEqual(1, exported["exported_count"])
        self.assertEqual("current", exported["corpus_binding"])

    def test_host_import_rejects_quote_mismatch(self) -> None:
        study = self.make_study()
        request = self.make_request(study)
        response = self.response(request)
        response["candidates"][0]["evidence_refs"][0]["quote"] = "not in the record"
        with self.assertRaises(semantic_candidates.SemanticError) as caught:
            semantic_candidates.import_host_response(study, response, by="alice")
        self.assertEqual("INVALID_RESPONSE", caught.exception.reason_code)

    def test_host_import_rejects_stale_nonce(self) -> None:
        study = self.make_study()
        request = self.make_request(study)
        with self.assertRaises(semantic_candidates.SemanticError) as caught:
            semantic_candidates.import_host_response(
                study, self.response(request, nonce="old"), by="alice")
        self.assertEqual("STALE_SOURCE", caught.exception.reason_code)

    def test_host_import_rejects_forbidden_evidence_fields(self) -> None:
        study = self.make_study()
        request = self.make_request(study)
        response = self.response(request)
        response["candidates"][0]["evidence_level"] = "E3"
        with self.assertRaises(semantic_candidates.SemanticError) as caught:
            semantic_candidates.import_host_response(study, response, by="alice")
        self.assertEqual("INVALID_RESPONSE", caught.exception.reason_code)


class SemanticCliTests(SemanticFixture):
    def test_analyze_semantic_offline_end_to_end(self) -> None:
        study = self.make_study()
        completed = run_cli("analyze", str(study), "--semantic",
                            "--semantic-provider", "offline")
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual("complete", payload["semantic"]["status"])
        self.assertTrue((study / semantic_candidates.CANDIDATES_REL).is_file())
        self.assertTrue((study / semantic_candidates.CRITIC_REL).is_file())

    def test_analyze_without_semantic_writes_no_semantic_files(self) -> None:
        study = self.make_study()
        completed = run_cli("analyze", str(study))
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertFalse((study / semantic_candidates.CANDIDATES_REL).exists())
        self.assertTrue((study / "04-findings" / "analysis.json").is_file())

    def test_analyze_semantic_without_config_falls_back(self) -> None:
        study = self.make_study()
        completed = run_cli("analyze", str(study), "--semantic")
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual("skipped", payload["semantic"]["status"])
        self.assertTrue((study / "04-findings" / "analysis.json").is_file())

    def test_remote_model_without_authorization_exits_two(self) -> None:
        study = self.make_study()
        completed = run_cli(
            "analyze", str(study), "--semantic", "--semantic-provider", "openai",
            env_extra={"ASKOVO_LLM_BASE": "https://api.example.com/v1",
                       "ASKOVO_LLM_MODEL": "test"})
        self.assertEqual(2, completed.returncode)
        self.assertIn("--allow-external", completed.stderr)
        self.assertFalse((study / semantic_candidates.CANDIDATES_REL).exists())

    def test_semantic_review_and_export_via_cli(self) -> None:
        study = self.make_study()
        run_cli("analyze", str(study), "--semantic", "--semantic-provider", "offline")
        candidate_id = self.first_candidate(study)
        reviewed = run_cli("semantic", "review", str(study), "--candidate", candidate_id,
                           "--decision", "accept", "--reviewer", "alice",
                           "--note", "quote reviewed")
        self.assertEqual(0, reviewed.returncode, reviewed.stdout + reviewed.stderr)
        exported = run_cli("semantic", "export", str(study), "--by", "alice")
        self.assertEqual(0, exported.returncode, exported.stdout + exported.stderr)
        payload = json.loads(exported.stdout)
        self.assertEqual(1, payload["exported_count"])

    def test_mcp_exposes_semantic_tools(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(MCP), "--tools"],
            check=False, capture_output=True, text=True, timeout=120)
        self.assertEqual(0, completed.returncode, completed.stderr)
        tools = {tool["name"]: tool for tool in json.loads(completed.stdout)["tools"]}
        self.assertIn("askovo_semantic", tools)
        analyze = tools["askovo_analyze"]["inputSchema"]["properties"]
        self.assertIn("semantic", analyze)
        self.assertIn("allow_external", analyze)
        self.assertNotIn("review", tools["askovo_semantic"]["inputSchema"]["properties"]["action"]["enum"])

    def test_mcp_cannot_self_attest_human_semantic_review(self) -> None:
        import askovo_mcp
        with self.assertRaisesRegex(ValueError, "human-only"):
            askovo_mcp._build_semantic({
                "action": "review", "study_dir": "/tmp/study", "candidate": "c1",
                "decision": "accept", "reviewer": "agent-self-declared"})


if __name__ == "__main__":
    unittest.main()
