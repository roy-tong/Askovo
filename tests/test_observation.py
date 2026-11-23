"""CLI tests for `askovo observation` (product behaviour as a research source)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/askovo/scripts/askovo.py"


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


def observation(generalization="single_case", repeat_count=1, **overrides):
    claim = {
        "claim_id": "c1",
        "statement": "导出按钮在有数据的视图上直接可用",
        "observed_facts": [
            {"fact_id": "f1", "text": "点击 Export 后在 2 秒内下载了 CSV"}
        ],
        "inferred_rule": "有数据时导出走同步下载，不进入异步任务队列",
        "uncovered_conditions": ["空视图", "超过 10 万行的数据量"],
        "generalization": generalization,
        "repeat_count": repeat_count,
        "evidence_level": "E2",
        "basis": "product_behavior_observation",
    }
    if generalization == "multi_context":
        claim["contexts"] = [
            {"product_version": "2.20.3", "account_permission": "admin",
             "platform": "web", "region": "CN"},
            {"product_version": "2.20.3", "account_permission": "viewer",
             "platform": "web", "region": "US"},
        ]
    claim.update(overrides.pop("claim", {}))
    doc = {
        "schema": "askovo.product-observation/1",
        "observation_id": "obs-001",
        "product": "competitive product X",
        "product_version": "2.20.3",
        "account_permission": "admin",
        "platform": "web",
        "region": "CN",
        "tested_at": "2026-11-22T10:00:00+08:00",
        "method": "manual",
        "inputs": ["打开有数据的列表页", "点击 Export"],
        "observed": ["页面出现下载提示", "浏览器保存了 CSV"],
        "claims": [claim],
    }
    doc.update(overrides)
    return doc


class ObservationCliTest(unittest.TestCase):
    def test_valid_single_case_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "obs.json"
            path.write_text(json.dumps(observation()), encoding="utf-8")
            run = run_cli("observation", "validate", str(path))
        self.assertEqual(0, run.returncode, run.stdout + run.stderr)
        self.assertIn("校验通过", run.stdout)

    def test_universal_generalisation_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "obs.json"
            path.write_text(
                json.dumps(observation(generalization="universal")),
                encoding="utf-8")
            run = run_cli("observation", "validate", str(path))
        self.assertEqual(1, run.returncode)
        self.assertIn("universal", run.stdout)

    def test_single_case_cannot_claim_multiple_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "obs.json"
            path.write_text(json.dumps(observation(repeat_count=3)),
                            encoding="utf-8")
            run = run_cli("observation", "validate", str(path))
        self.assertEqual(1, run.returncode)
        self.assertIn("single_case", run.stdout)

    def test_missing_platform_is_rejected(self):
        doc = observation()
        doc["platform"] = ""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "obs.json"
            path.write_text(json.dumps(doc), encoding="utf-8")
            run = run_cli("observation", "validate", str(path))
        self.assertEqual(1, run.returncode)
        self.assertIn("platform", run.stdout)

    def test_claim_needs_uncovered_conditions(self):
        doc = observation()
        doc["claims"][0]["uncovered_conditions"] = []
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "obs.json"
            path.write_text(json.dumps(doc), encoding="utf-8")
            run = run_cli("observation", "validate", str(path))
        self.assertEqual(1, run.returncode)
        self.assertIn("uncovered_conditions", run.stdout)

    def test_record_is_append_only_and_listable(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "store"
            path = Path(tmp) / "obs.json"
            path.write_text(json.dumps(observation()), encoding="utf-8")
            first = run_cli("observation", "record", str(path),
                            "--store", str(store))
            second = run_cli("observation", "record", str(path),
                             "--store", str(store))
            listed = run_cli("observation", "list", "--store", str(store),
                             "--json")
        self.assertEqual(0, first.returncode, first.stdout + first.stderr)
        self.assertEqual(2, second.returncode)
        self.assertIn("already exists", second.stderr)
        rows = json.loads(listed.stdout)
        self.assertEqual(1, len(rows))
        self.assertEqual("obs-001", rows[0]["observation_id"])

    def test_export_marks_single_case_not_generalizable(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "store"
            study = Path(tmp) / "study"
            study.mkdir()
            path = Path(tmp) / "obs.json"
            path.write_text(json.dumps(observation()), encoding="utf-8")
            run_cli("observation", "record", str(path), "--store", str(store))
            exported = run_cli("observation", "export", "--store", str(store),
                               "--study", str(study), "--json")
            lines = [json.loads(line) for line in
                     (study / "01-sources/observations.jsonl")
                     .read_text(encoding="utf-8").splitlines()]
        self.assertEqual(0, exported.returncode, exported.stdout + exported.stderr)
        self.assertEqual(1, len(lines))
        self.assertTrue(lines[0]["not_generalizable"])
        self.assertEqual("product_observation", lines[0]["source_kind"])
        self.assertEqual("E2", lines[0]["evidence_level"])
        self.assertEqual("web", lines[0]["context"]["platform"])

    def test_export_keeps_multi_context_contexts(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "store"
            study = Path(tmp) / "study"
            study.mkdir()
            doc = observation(generalization="multi_context", repeat_count=2)
            path = Path(tmp) / "obs.json"
            path.write_text(json.dumps(doc), encoding="utf-8")
            run_cli("observation", "record", str(path), "--store", str(store))
            exported = run_cli("observation", "export", "--store", str(store),
                               "--study", str(study))
            line = json.loads(
                (study / "01-sources/observations.jsonl")
                .read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(0, exported.returncode, exported.stdout + exported.stderr)
        self.assertFalse(line["not_generalizable"])
        self.assertEqual(2, len(line["contexts"]))

    def test_export_aborts_on_invalid_stored_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "store"
            store.mkdir()
            study = Path(tmp) / "study"
            study.mkdir()
            broken = observation()
            broken["claims"][0]["evidence_level"] = "E5"
            (store / "obs-001.json").write_text(
                json.dumps(broken), encoding="utf-8")
            exported = run_cli("observation", "export", "--store", str(store),
                               "--study", str(study))
            self.assertFalse(
                (study / "01-sources/observations.jsonl").exists())
        self.assertEqual(1, exported.returncode)
        self.assertIn("evidence_level", exported.stderr)
    def test_export_preserves_observed_facts_inputs_and_source_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "store"; study = Path(tmp) / "study"; study.mkdir()
            path = Path(tmp) / "obs.json"; path.write_text(json.dumps(observation()), encoding="utf-8")
            run_cli("observation", "record", str(path), "--store", str(store))
            exported = run_cli("observation", "export", "--store", str(store), "--study", str(study))
            line = json.loads((study / "01-sources/observations.jsonl").read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(0, exported.returncode)
        self.assertEqual("点击 Export 后在 2 秒内下载了 CSV", line["observed_facts"][0]["text"])
        self.assertIn("打开有数据的列表页", line["inputs"])
        self.assertTrue(line["source_hash"].startswith("sha256:"))
        self.assertEqual("obs-001/c1", line["source_ref"])

    def test_observation_id_cannot_escape_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); store = root / "store"
            path = root / "obs.json"
            path.write_text(json.dumps(observation(observation_id="../outside")), encoding="utf-8")
            run = run_cli("observation", "record", str(path), "--store", str(store))
            self.assertEqual(2, run.returncode)
            self.assertFalse((root / "outside.json").exists())

    def test_naive_timestamp_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "obs.json"
            path.write_text(json.dumps(observation(tested_at="2026-11-22T10:00:00")), encoding="utf-8")
            run = run_cli("observation", "validate", str(path))
        self.assertEqual(1, run.returncode)

    def test_reviewed_observation_cannot_be_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "store"; path = Path(tmp) / "obs.json"
            reviewed = observation(reviewed_at="2026-11-22T11:00:00+08:00")
            path.write_text(json.dumps(reviewed), encoding="utf-8")
            run_cli("observation", "record", str(path), "--store", str(store))
            run = run_cli("observation", "record", str(path), "--store", str(store), "--replace")
            self.assertEqual(2, run.returncode)
            self.assertIn("reviewed", run.stderr)

    def test_repeat_export_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "store"; study = Path(tmp) / "study"; study.mkdir()
            path = Path(tmp) / "obs.json"; path.write_text(json.dumps(observation()), encoding="utf-8")
            run_cli("observation", "record", str(path), "--store", str(store))
            first = run_cli("observation", "export", "--store", str(store), "--study", str(study), "--json")
            second = run_cli("observation", "export", "--store", str(store), "--study", str(study), "--json")
            target = study / "01-sources/observations.jsonl"
            rows = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(0, first.returncode, first.stdout + first.stderr)
        self.assertEqual(0, second.returncode, second.stdout + second.stderr)
        self.assertEqual(1, len(rows))
        self.assertEqual(1, json.loads(first.stdout)["added"])
        self.assertEqual(0, json.loads(second.stdout)["added"])

    def test_failed_export_transaction_preserves_previous_bytes(self):
        scripts = ROOT / "skills/askovo/scripts"
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        import observation as observation_module
        if not hasattr(observation_module, "write_integrity"):
            self.fail("observation export does not use the study transaction boundary")
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "store"; store.mkdir(); study = Path(tmp) / "study"; study.mkdir()
            doc = observation()
            (store / "obs-001.json").write_text(json.dumps(doc), encoding="utf-8")
            args = SimpleNamespace(store=str(store), study=str(study), json=True)
            observation_module.cmd_export(args)
            target = study / "01-sources/observations.jsonl"
            before = target.read_bytes()
            doc["claims"][0]["statement"] = "new revision"
            (store / "obs-001.json").write_text(json.dumps(doc), encoding="utf-8")
            with mock.patch.object(
                    observation_module.write_integrity.Transaction, "commit",
                    side_effect=observation_module.write_integrity.IntegrityError("boom")):
                with self.assertRaises(observation_module.write_integrity.IntegrityError):
                    observation_module.cmd_export(args)
            self.assertEqual(before, target.read_bytes())

    def test_mcp_validate_uses_shared_observation_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "obs.json"; path.write_text(json.dumps(observation()), encoding="utf-8")
            request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
                "name": "askovo_observation", "arguments": {"action": "validate", "file": str(path)}}}
            run = subprocess.run([sys.executable, str(ROOT / "skills/askovo/scripts/askovo_mcp.py")],
                                 input=json.dumps(request) + "\n", capture_output=True, text=True)
            response = json.loads(run.stdout.strip())
            payload = json.loads(response["result"]["content"][0]["text"])
            self.assertEqual(0, payload["exit_code"])


if __name__ == "__main__":
    unittest.main()
