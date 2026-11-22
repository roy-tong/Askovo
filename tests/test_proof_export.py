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


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True, env=env)


def tree_hashes(root: Path) -> dict:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*") if path.is_file()
    }


class ProofExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="askovo-proof-"))
        self.study = self.tmp / "study"
        shutil.copytree(SAMPLE, self.study)
        self.out = self.tmp / "proof-bundle"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_export_is_read_only_and_keeps_external_checks_unproven(self) -> None:
        before = tree_hashes(self.study)
        completed = run_cli(
            "proof", "export", str(self.study), "--out", str(self.out),
            "--by", "artifact-reviewer", "--classification", "synthetic",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        payload = json.loads(completed.stdout)
        self.assertEqual("exported", payload["status"])
        self.assertEqual("BLOCKED", payload["proof_status"])
        self.assertEqual(before, tree_hashes(self.study))
        for relative in (
            "bundle.json", "contract.json", "trace.jsonl", "checks.json",
            "proof.json", "replay/manifest.json", "artifacts/decision-brief.json",
            "artifacts/decision-brief.md",
        ):
            self.assertTrue((self.out / relative).is_file(), relative)
        checks = json.loads((self.out / "checks.json").read_text(encoding="utf-8"))["checks"]
        by_id = {item["check_id"]: item for item in checks}
        self.assertEqual("PASS", by_id["artifact-readable"]["status"])
        self.assertEqual("P1", by_id["artifact-readable"]["level"])
        self.assertEqual("UNCHECKED", by_id["independent-semantic-review"]["status"])
        self.assertEqual("UNCHECKED", by_id["external-decision-adoption"]["status"])
        self.assertFalse(any("proof_level" in item for item in checks))
        artifact_names = {path.name for path in (self.out / "artifacts").iterdir()}
        self.assertEqual({"decision-brief.json", "decision-brief.md"}, artifact_names)

    def test_export_uses_shared_evidence_vocabulary(self) -> None:
        completed = run_cli(
            "proof", "export", str(self.study), "--out", str(self.out), "--by", "reviewer",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        bundle = json.loads((self.out / "bundle.json").read_text(encoding="utf-8"))
        allowed = {"source_document", "api_response", "screenshot", "log", "replay", "observation", "test_run", "third_party"}
        for entry in bundle["evidence_ledger"]["entries"]:
            self.assertIn(entry["kind"], allowed)
        brief = next(item for item in bundle["evidence_ledger"]["entries"] if item["evidence_id"] == "decision-brief-json")
        self.assertEqual("source_document", brief["kind"])
        self.assertEqual("derived", brief["trust"])

    def test_stale_brief_becomes_expired_not_pass(self) -> None:
        chain = self.study / "04-findings/product-reasoning.json"
        payload = json.loads(chain.read_text(encoding="utf-8"))
        payload["chains"][0]["nodes"]["scene"]["evidence_ids"] = ["R404"]
        chain.write_text(json.dumps(payload), encoding="utf-8")
        completed = run_cli(
            "proof", "export", str(self.study), "--out", str(self.out), "--by", "reviewer",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        checks = json.loads((self.out / "checks.json").read_text(encoding="utf-8"))["checks"]
        artifact = next(item for item in checks if item["check_id"] == "artifact-readable")
        self.assertEqual("EXPIRED", artifact["status"])
        brief = json.loads((self.out / "artifacts/decision-brief.json").read_text(encoding="utf-8"))
        self.assertEqual("stale", brief["artifact_status"])

    def test_export_refuses_to_overwrite_existing_output(self) -> None:
        self.out.mkdir()
        (self.out / "keep.txt").write_text("keep", encoding="utf-8")
        completed = run_cli(
            "proof", "export", str(self.study), "--out", str(self.out), "--by", "reviewer",
        )
        self.assertEqual(2, completed.returncode)
        self.assertIn("OUTPUT_EXISTS", completed.stderr + completed.stdout)
        self.assertEqual("keep", (self.out / "keep.txt").read_text(encoding="utf-8"))

    def test_mcp_export_uses_the_same_implementation(self) -> None:
        mcp_out = self.tmp / "mcp-proof"
        request = {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "askovo_proof_export", "arguments": {
                "study_dir": str(self.study), "out": str(mcp_out), "by": "mcp-reviewer",
            }},
        }
        completed = subprocess.run(
            [sys.executable, str(ROOT / "skills/askovo/scripts/askovo_mcp.py")],
            input=json.dumps(request) + "\n", capture_output=True, text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        response = json.loads(completed.stdout.strip())
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(0, payload["exit_code"], payload)
        self.assertEqual("exported", payload["result"]["status"])
        self.assertTrue((mcp_out / "proof.json").is_file())

    def test_export_requires_named_artifact_reviewer(self) -> None:
        completed = run_cli(
            "proof", "export", str(self.study), "--out", str(self.out), "--by", "",
        )
        self.assertEqual(2, completed.returncode)


if __name__ == "__main__":
    unittest.main()
