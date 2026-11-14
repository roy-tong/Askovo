"""A-01 证据资格反例：注意力指标不是商业 E5（先冻结，后修复）。

三个正交显示属性（measurement_integrity / behavior_kind / claim_eligibility）
与 E0–E5 契约并存：资格派生不改写 evidence_level，也不迁移历史数据；
跨维度冲突只输出 needs_requalification 标记，交人工重审。
"""
from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/askovo/scripts/askovo.py"
SAMPLE = ROOT / "examples/sample-study"
DOC = ROOT / "docs/plan-evidence-check.md"
sys.path.insert(0, str(ROOT / "skills/askovo/scripts"))
import sure_engine  # noqa: E402

_spec = importlib.util.spec_from_file_location("askovo_cli_under_test", CLI)
askovo_cli = importlib.util.module_from_spec(_spec)
sys.modules["askovo_cli_under_test"] = askovo_cli
_spec.loader.exec_module(askovo_cli)


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        check=False, capture_output=True, text=True, timeout=120,
    )


def star_record(**overrides) -> dict:
    """A1 场景：真实 star 数，GitHub API 来源可核实，但只是注意力指标。"""
    record = {
        "record_id": "S01",
        "context_key": "launch-baseline",
        "user_role": "GitHub visitor",
        "scene_trigger": "Repo seen in feed",
        "task_outcome": "Starred the repo",
        "current_substitute": "none",
        "friction_cost": "none",
        "consequence": "Attention only; no use or payment implied",
        "evidence_level": "E5",  # 旧污染：注意力指标被标成商业级
        "evidence_basis": "GitHub API stargazers_count = 200",
        "corpus_role": "open_scene",
        "source_family": "github_api",
        "source_ref": "repos/roy-tong/Askovo",
        "source_url": "https://api.github.com/repos/roy-tong/Askovo",
        "collection_run_id": "github-api-2026-11-15",
        "normalized_text_hash": "sha256:s01",
        "evidence_form": "attention_metric",
    }
    record.update(overrides)
    return record


def claimed_payment_record(**overrides) -> dict:
    """A2 场景：口头声称已付款，来源不可核实。"""
    record = {
        "record_id": "P01",
        "context_key": "claimed-payment",
        "user_role": "Individual buyer",
        "scene_trigger": "Asked about purchase",
        "task_outcome": "Says already paid",
        "current_substitute": "manual spreadsheet",
        "friction_cost": "none stated",
        "consequence": "claimed transaction",
        "evidence_level": "E5",  # 越级：未验证来源的付款陈述被标商业级
        "evidence_basis": "self-reported payment statement, no receipt",
        "corpus_role": "open_scene",
        "source_family": "interview",
        "source_ref": "interview-notes-07",
        "normalized_text_hash": "sha256:p01",
        "evidence_form": "transaction",
    }
    record.update(overrides)
    return record


class A1RealStarIsDescriptiveOnly(unittest.TestCase):
    """A1：可核实的 star 数只是描述性观测，不得推出商业 E5 资格。"""

    def test_confirmed_star_qualifies_descriptive_only(self) -> None:
        info = sure_engine.qualify_evidence(star_record())
        self.assertEqual("confirmed_source", info["measurement_integrity"])
        self.assertEqual("attention_metric", info["behavior_kind"])
        self.assertEqual("descriptive_only", info["claim_eligibility"])

    def test_attention_metric_never_gets_commercial_eligibility(self) -> None:
        info = sure_engine.qualify_evidence(star_record())
        self.assertNotEqual("commercial", info["claim_eligibility"])
        self.assertTrue(info["needs_requalification"])
        self.assertTrue(any("E5" in reason for reason in info["reasons"]))

    def test_qualification_does_not_rewrite_the_level(self) -> None:
        record = star_record()
        snapshot = copy.deepcopy(record)
        sure_engine.qualify_evidence(record)
        self.assertEqual(snapshot, record)
        self.assertEqual("E5", record["evidence_level"])


class A2UnverifiedPaymentIsNotCommercial(unittest.TestCase):
    """A2：来源 unverified/self_reported 的「已付款」不得获得商业资格。"""

    def test_unverified_payment_statement_gets_no_commercial_eligibility(self) -> None:
        info = sure_engine.qualify_evidence(claimed_payment_record())
        self.assertEqual("unverified", info["measurement_integrity"])
        self.assertEqual("commercial_transaction", info["behavior_kind"])
        self.assertNotEqual("commercial", info["claim_eligibility"])
        self.assertTrue(info["review_required"])
        self.assertTrue(info["needs_requalification"])

    def test_self_reported_payment_gets_no_commercial_eligibility(self) -> None:
        record = claimed_payment_record(measurement_integrity="self_reported")
        info = sure_engine.qualify_evidence(record)
        self.assertEqual("self_reported", info["measurement_integrity"])
        self.assertNotEqual("commercial", info["claim_eligibility"])
        self.assertTrue(info["review_required"])

    def test_verified_transaction_can_qualify_commercial(self) -> None:
        record = claimed_payment_record(
            record_id="P02",
            source_url="https://example.invalid/order/1",
            collection_run_id="marketplace-run-1",
            commerce_transaction_status="verified_purchase",
        )
        info = sure_engine.qualify_evidence(record)
        self.assertEqual("confirmed_source", info["measurement_integrity"])
        self.assertEqual("commercial", info["claim_eligibility"])
        self.assertFalse(info["needs_requalification"])


class A3CopiedSourceDoesNotRaiseIndependence(unittest.TestCase):
    """A3：同一来源复制三条，独立来源数不提升。"""

    def test_three_copies_count_as_one_independent_source(self) -> None:
        records = [
            star_record(record_id=f"S0{i}", normalized_text_hash=f"sha256:s0{i}")
            for i in range(1, 4)
        ]
        self.assertEqual(1, sure_engine.independent_source_count(records))
        summary = sure_engine.evidence_qualification(records)
        self.assertEqual(1, summary["independent_sources"])
        self.assertEqual(3, summary["records_total"])
        self.assertEqual(3, summary["counts"]["claim_eligibility"]["descriptive_only"])

    def test_distinct_sources_count_separately(self) -> None:
        records = [
            star_record(source_url=f"https://api.github.com/repos/r{i}") for i in range(2)
        ]
        self.assertEqual(2, sure_engine.independent_source_count(records))


class A4LegacyDataStaysReadOnly(unittest.TestCase):
    """A4：旧数据只读可用，不静默晋级，也不因资格逻辑报错。"""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="askovo-a01-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.study = self.tmp / "study"
        shutil.copytree(SAMPLE, self.study)
        self.evidence_path = self.study / "02-data/evidence.jsonl"

    def test_legacy_records_qualify_without_error_or_mutation(self) -> None:
        for line in self.evidence_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            snapshot = copy.deepcopy(record)
            info = sure_engine.qualify_evidence(record)
            self.assertIn(info["measurement_integrity"], sure_engine.MEASUREMENT_INTEGRITY_VALUES)
            self.assertIn(info["behavior_kind"], sure_engine.BEHAVIOR_KIND_VALUES)
            self.assertIn(info["claim_eligibility"], sure_engine.CLAIM_ELIGIBILITY_VALUES)
            self.assertEqual(snapshot, record)

    def test_legacy_study_audit_reads_without_error_and_keeps_file(self) -> None:
        before = self.evidence_path.read_bytes()
        payload = askovo_cli.audit_payload(self.study)
        self.assertIn("evidence_qualification", payload)
        self.assertEqual(before, self.evidence_path.read_bytes())

    def test_conflicted_e5_is_flagged_not_upgraded_or_rewritten(self) -> None:
        with self.evidence_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(star_record(), ensure_ascii=False) + "\n")
        before = self.evidence_path.read_bytes()
        payload = askovo_cli.audit_payload(self.study)
        flagged = payload["evidence_qualification"]["needs_requalification"]
        self.assertIn("S01", flagged)
        self.assertEqual(before, self.evidence_path.read_bytes())
        stored = {
            json.loads(line)["record_id"]: json.loads(line)
            for line in self.evidence_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
        self.assertEqual("E5", stored["S01"]["evidence_level"])


class A5QualificationAgreesAcrossDocReviewerProjection(unittest.TestCase):
    """A5：文档示例、审核器、投影对同一证据给出一致资格判断。"""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="askovo-a01-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.study = self.tmp / "study"
        shutil.copytree(SAMPLE, self.study)
        with (self.study / "02-data/evidence.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(star_record(), ensure_ascii=False) + "\n")

    @property
    def triple(self) -> tuple[str, str, str]:
        info = sure_engine.qualify_evidence(star_record())
        return (
            info["measurement_integrity"],
            info["behavior_kind"],
            info["claim_eligibility"],
        )

    def test_reviewer_and_projection_agree(self) -> None:
        payload = askovo_cli.audit_payload(self.study)
        reviewer = payload["evidence_qualification"]["records"]["S01"]
        self.assertEqual(self.triple, (
            reviewer["measurement_integrity"],
            reviewer["behavior_kind"],
            reviewer["claim_eligibility"],
        ))
        completed = run_cli("deliver", str(self.study), "--kind", "plan")
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        summary = json.loads(completed.stdout)["chat_summary"]
        projection = summary["evidence_qualification"]["records"]["S01"]
        self.assertEqual(self.triple, (
            projection["measurement_integrity"],
            projection["behavior_kind"],
            projection["claim_eligibility"],
        ))

    def test_doc_example_matches_engine(self) -> None:
        text = DOC.read_text(encoding="utf-8")
        integrity, kind, eligibility = self.triple
        annotation = (
            f"measurement_integrity={integrity} / behavior_kind={kind} / "
            f"claim_eligibility={eligibility}"
        )
        self.assertIn(annotation, text)
        drilldown = text.split("## 演练", 1)[1].split("## 实际发生了什么", 1)[0]
        self.assertNotIn("| E5", drilldown)
        self.assertIn("A-01", text)


if __name__ == "__main__":
    unittest.main()
