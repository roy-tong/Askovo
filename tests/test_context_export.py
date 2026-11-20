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
REASONING_RELATIVE = Path("04-findings/product-reasoning.json")
CLAIM_STATUSES = {"evidence_supported", "hypothesis", "insufficient_evidence"}


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_growovo_contract(testcase: unittest.TestCase, envelope: dict) -> None:
    """Replica of Growovo core/work.py lint_context; kept inline on purpose."""
    for field in ("context_id", "version", "approved_by", "content_sha256"):
        testcase.assertTrue(str(envelope.get(field) or "").strip(), field)
    source = envelope.get("source")
    testcase.assertIsInstance(source, dict)
    testcase.assertIn(source.get("kind"), {"askovo", "user_declared"})
    ref = str(source.get("ref") or "").strip()
    testcase.assertTrue(ref, "source.ref")
    if source.get("kind") == "askovo":
        payload_path = Path(ref)
        testcase.assertTrue(payload_path.is_file(), "source.ref must point at an existing file")
        testcase.assertEqual(
            hashlib.sha256(payload_path.read_bytes()).hexdigest(),
            str(envelope["content_sha256"]).lower(),
        )
    for field in ("value_event_definitions", "non_goals", "claims"):
        testcase.assertIsInstance(envelope.get(field), list)
        testcase.assertTrue(envelope[field], field)
    seen = set()
    for claim in envelope["claims"]:
        claim_id = str(claim.get("claim_id") or "").strip()
        testcase.assertTrue(claim_id)
        testcase.assertNotIn(claim_id, seen)
        seen.add(claim_id)
        testcase.assertGreaterEqual(len(str(claim.get("statement") or "")), 8)
        status = claim.get("status")
        testcase.assertIn(status, CLAIM_STATUSES)
        if status == "hypothesis":
            testcase.assertIs(claim.get("assumption"), True)
        if status in ("evidence_supported", "insufficient_evidence"):
            refs = claim.get("evidence_refs") or []
            testcase.assertTrue(refs, claim_id)
            for evidence_ref in refs:
                testcase.assertTrue(str(evidence_ref.get("evidence_id") or "").strip())
                testcase.assertTrue(str(evidence_ref.get("source") or "").strip())


class ContextExportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.study = Path(self.temp.name) / "study"
        shutil.copytree(SAMPLE, self.study)
        self.out = Path(self.temp.name) / "out"
        self.reasoning_path = self.study / REASONING_RELATIVE

    def tearDown(self) -> None:
        self.temp.cleanup()

    def export(self, *extra: str, version: str = "reasoning-test") -> subprocess.CompletedProcess[str]:
        return run_cli(
            "context", "export", str(self.study),
            "--out", str(self.out),
            "--approved-by", "Roy Tong",
            "--value-event", "pilot_signup",
            "--version", version,
            "--market", "CN",
            "--time-window", "2026-11",
            *extra,
        )

    def load_envelope(self) -> dict:
        files = list(self.out.glob("*.json"))
        envelopes = [path for path in files if not path.name.endswith(".payload.json")]
        self.assertEqual(1, len(envelopes), files)
        return json.loads(envelopes[0].read_text(encoding="utf-8"))

    def test_exports_payload_and_envelope_with_verified_hash(self) -> None:
        completed = self.export()
        self.assertEqual(0, completed.returncode, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual("exported", payload["status"])
        payload_file = Path(payload["payload_file"])
        envelope_file = Path(payload["envelope_file"])
        self.assertTrue(payload_file.is_file())
        self.assertTrue(envelope_file.is_file())
        self.assertTrue(payload_file.name.endswith(".payload.json"))
        self.assertEqual(payload_file.parent, envelope_file.parent)

        envelope = self.load_envelope()
        self.assertEqual("askovo.research-context/1", envelope["schema"])
        self.assertEqual(payload["content_sha256"], digest(payload_file))
        self.assertEqual(envelope["content_sha256"], digest(payload_file))
        self.assertEqual("askovo", envelope["source"]["kind"])
        self.assertEqual(str(payload_file.resolve()), envelope["source"]["ref"])
        self.assertEqual(["pilot_signup"], envelope["value_event_definitions"])
        self.assertEqual({"market": "CN", "time_window": "2026-11"}, envelope["scope"])
        self.assertTrue(envelope["non_goals"])
        self.assertEqual(7, len(envelope["claims"]))
        self.assertIn("mkt context import", payload["growovo_import"])
        assert_growovo_contract(self, envelope)

    def test_claims_preserve_grades_and_resolve_evidence(self) -> None:
        completed = self.export()
        self.assertEqual(0, completed.returncode, completed.stderr)
        envelope = self.load_envelope()
        evidence_levels = {
            ref["evidence_id"]: ref.get("evidence_level")
            for claim in envelope["claims"]
            for ref in claim.get("evidence_refs") or []
            if ref.get("resolved")
        }
        self.assertEqual("E5", evidence_levels.get("R06"))
        for claim in envelope["claims"]:
            self.assertEqual("synthetic-mobile-check", claim["context_key"])
            for ref in claim.get("evidence_refs") or []:
                self.assertIn("evidence_level", ref)
                self.assertTrue(ref["resolved"])
            if claim["status"] == "evidence_supported":
                self.assertNotIn("assumption", claim)
        self.assertEqual(
            sorted(set(evidence_levels)),
            envelope["provenance_refs"],
        )
        self.assertEqual(64, len(envelope["provenance"]["reasoning_sha256"]))

    def test_hypothesis_and_missing_evidence_are_never_upgraded(self) -> None:
        reasoning = json.loads(self.reasoning_path.read_text(encoding="utf-8"))
        node = reasoning["chains"][0]["nodes"]["pain"]
        node["status"] = "hypothesis"
        node["evidence_ids"] = []
        reasoning["chains"][0]["nodes"]["need"]["evidence_ids"] = []
        self.reasoning_path.write_text(
            json.dumps(reasoning, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        completed = self.export(version="reasoning-downgrade")
        self.assertEqual(0, completed.returncode, completed.stderr)
        envelope = self.load_envelope()
        by_id = {claim["claim_id"]: claim for claim in envelope["claims"]}
        hypothesis = by_id["PR01:pain"]
        self.assertEqual("hypothesis", hypothesis["status"])
        self.assertIs(True, hypothesis["assumption"])
        needs = by_id["PR01:need"]
        self.assertEqual("insufficient_evidence", needs["status"])
        self.assertIn("降级", needs["note"])
        self.assertEqual("reasoning-record:PR01/need", needs["evidence_refs"][0]["evidence_id"])
        self.assertEqual("status_record_only", needs["evidence_refs"][0]["basis"])
        assert_growovo_contract(self, envelope)

    def test_reexport_same_version_refuses_and_keeps_files_byte_identical(self) -> None:
        first = self.export()
        self.assertEqual(0, first.returncode, first.stderr)
        payload_file = Path(json.loads(first.stdout)["payload_file"])
        envelope_file = Path(json.loads(first.stdout)["envelope_file"])
        before = (digest(payload_file), digest(envelope_file))
        second = self.export()
        self.assertEqual(2, second.returncode)
        self.assertIn("不会覆盖", second.stderr)
        self.assertEqual(before, (digest(payload_file), digest(envelope_file)))
        self.assertEqual(2, len(list(self.out.glob("*.json"))))

    def test_configuration_errors_exit_2_without_writing(self) -> None:
        cases = (
            ("--approved-by", ""),
            ("--value-event", ""),
        )
        for flag, value in cases:
            with self.subTest(flag=flag):
                args = [
                    "context", "export", str(self.study),
                    "--out", str(self.out),
                    "--approved-by", "Roy Tong",
                    "--value-event", "pilot_signup",
                ]
                args[args.index(flag) + 1] = value
                completed = run_cli(*args)
                self.assertEqual(2, completed.returncode)
                self.assertFalse(self.out.exists() and any(self.out.glob("*.json")))

    def test_unknown_chain_exits_2_and_lists_available(self) -> None:
        completed = self.export("--chain", "PR99")
        self.assertEqual(2, completed.returncode)
        self.assertIn("PR01", completed.stderr)
        self.assertFalse(self.out.exists() and any(self.out.glob("*.json")))

    def test_non_goal_flag_is_appended_and_deduplicated(self) -> None:
        completed = self.export("--non-goal", "本轮不做海外市场定价", "--non-goal", "本轮不做海外市场定价")
        self.assertEqual(0, completed.returncode, completed.stderr)
        envelope = self.load_envelope()
        self.assertEqual(1, envelope["non_goals"].count("本轮不做海外市场定价"))
        self.assertGreater(len(envelope["non_goals"]), 1)


if __name__ == "__main__":
    unittest.main()
