#!/usr/bin/env python3
"""Regression tests for the 2026-11 end-to-end UX findings.

Covers: Chinese lexicon tokenization and query matching, collected_at dates,
import source alias, plan placeholder narrative and voice dedupe, join error
guidance, missing-directory errors, design-contract type hints, MCP query
alias, English domain routing, and contradiction follow-ups.
"""
from __future__ import annotations

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
MCP_SERVER = ROOT / "skills/askovo/scripts/askovo_mcp.py"
SAMPLE = ROOT / "examples/sample-study"
STOP = set("the and for with".split())


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


ENGINE = load_module("sure_engine_ux", ROOT / "skills/askovo/scripts/sure_engine.py")
MCP = load_module("askovo_mcp_ux", MCP_SERVER)


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(CLI), *args],
                          capture_output=True, text=True, timeout=180)


class ChineseTokenizerTests(unittest.TestCase):
    def test_lexicon_terms_are_words_not_fragments(self) -> None:
        terms = ENGINE._cjk_lexicon_terms("续费决策时点需要一份团队使用与价值摘要")
        self.assertIn("续费", terms)
        self.assertIn("决策", terms)
        self.assertIn("摘要", terms)
        for term in terms:
            self.assertGreaterEqual(len(term), 2)
            self.assertNotIn(term, {"费决", "策时", "时点需要"})

    def test_unknown_run_yields_nothing_for_terms(self) -> None:
        self.assertEqual(ENGINE._cjk_lexicon_terms("唦哫"), [])

    def test_query_terms_fall_back_to_bigrams(self) -> None:
        terms = ENGINE._query_terms("唦哫嫵嫹", STOP)
        self.assertEqual(terms, ["唦哫", "哫嫵", "嫵嫹"])

    def test_multi_word_query_matches_records(self) -> None:
        terms = ENGINE._query_terms("续费决策 使用证据", STOP)
        self.assertIn("续费", terms)
        self.assertIn("决策", terms)
        self.assertIn("证据", terms)

    def test_analysis_terms_skip_stopwords_and_fragments(self) -> None:
        terms = ENGINE._analysis_terms("the 续费 csv 乱丗丠両", STOP)
        self.assertEqual(terms, ["续费", "csv"])


class AnalyzeStudyTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        (self.dir / "02-data").mkdir(parents=True)
        (self.dir / "study.json").write_text("{}", encoding="utf-8")
        rows = [
            {"record_id": "A1", "text": "续费前需要自己导出数据整理表格", "collected_at": "2026-09-12", "source_family": "interviews"},
            {"record_id": "A2", "text": "到期邮件只有金额没有使用情况", "collected_at": "2026-10-02", "source_family": "interviews"},
        ]
        with (self.dir / "02-data" / "evidence.jsonl").open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _analysis(self, question: str | None = None) -> dict:
        ENGINE.analyze_study(self.dir, question=question)
        return json.loads((self.dir / "04-findings" / "analysis.json").read_text(encoding="utf-8"))

    def test_collected_at_drives_month_coverage(self) -> None:
        result = self._analysis()
        self.assertEqual(result["by_month"], {"2026-09": 1, "2026-10": 1})
        self.assertEqual(result["time_coverage"]["month_count"], 2)

    def test_multi_word_question_matches(self) -> None:
        result = self._analysis(question="续费决策 使用证据")
        self.assertTrue(result["question_matches"])
        self.assertEqual(result["question_matches"][0]["record_id"], "A1")

    def test_top_terms_are_lexicon_words(self) -> None:
        result = self._analysis()
        terms = [item["term"] for item in result["top_terms"]]
        self.assertIn("续费", terms)
        for term in terms:
            self.assertTrue(term.isascii() or term in ENGINE._chinese_lexicon()[0])


class ImportNormalizationTests(unittest.TestCase):
    def test_source_alias_and_collected_at_passthrough(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        study = Path(tmp.name) / "study"
        shutil.copytree(SAMPLE, study)
        payload = Path(tmp.name) / "rows.jsonl"
        payload.write_text(json.dumps({
            "record_id": "X1",
            "source": "surveys",
            "collected_at": "2026-10-01",
            "text": "这是一句测试文本",
        }, ensure_ascii=False) + "\n", encoding="utf-8")
        result = ENGINE.import_material(study, payload, source_family="imported")
        self.assertEqual(result["added"], 1)
        line = (study / "02-data" / "evidence.jsonl").read_text(encoding="utf-8").splitlines()[-1]
        record = json.loads(line)
        self.assertEqual(record["record_id"], "X1")
        self.assertEqual(record["source_family"], "surveys")
        self.assertEqual(record["collected_at"], "2026-10-01")


class PlanRenderingTests(unittest.TestCase):
    def _chain(self) -> dict:
        return {
            "nodes": {
                "scene": {"statement": "到期前30天做续费决策", "trigger": "收到到期通知邮件"},
                "user": {"statement": "团队管理员", "role": "待填写"},
                "pain": {"current_substitute": "待填写", "friction_cost": "每月人工整理耗时"},
                "need": {"desired_outcome": "无需手工整理即可出示使用证据"},
                "feature": {},
                "product": {},
                "business": {},
            }
        }

    def test_narrative_drops_placeholders(self) -> None:
        lines = ENGINE._plan_narrative(self._chain())
        narrative = "".join(lines)
        self.assertIn("推理主线", narrative)
        self.assertNotIn("待填写", narrative)
        self.assertIn("收到到期通知邮件", narrative)
        self.assertIn("眼下每月人工整理耗时", narrative)

    def test_quotes_dedupe_across_sections(self) -> None:
        record = {"record_id": "R01", "text_excerpt": "一条足够长的原话内容用于去重测试", "source_family": "interviews"}
        used: set = set()
        first = ENGINE._plan_quotes([record], limit=2, used=used)
        second = ENGINE._plan_quotes([record], limit=2, used=used)
        self.assertTrue(first)
        self.assertEqual(second, [])


class JoinGuidanceTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.study = Path(tmp.name) / "study"
        shutil.copytree(SAMPLE, self.study)

    def _cite_solution_evidence_on_need(self) -> None:
        path = self.study / "04-findings" / "product-reasoning.json"
        reasoning = json.loads(path.read_text(encoding="utf-8"))
        reasoning["chains"][0]["nodes"]["need"]["evidence_ids"] = ["R03"]
        path.write_text(json.dumps(reasoning, ensure_ascii=False, indent=2), encoding="utf-8")

    def test_join_error_names_the_misplaced_class(self) -> None:
        self._cite_solution_evidence_on_need()
        completed = run_cli("audit", str(self.study), "--json")
        payload = json.loads(completed.stdout)
        detail = json.dumps(payload, ensure_ascii=False)
        self.assertIn("registered in solution_evidence_ids", detail)
        self.assertIn("problem_evidence_ids", detail)

    def test_missing_directory_is_a_path_error(self) -> None:
        completed = run_cli("check", str(self.study.parent / "no-such-dir"), "--stage", "design")
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "fail")
        self.assertIn("study directory not found", json.dumps(payload, ensure_ascii=False))
        self.assertNotIn("missing study.json", json.dumps(payload, ensure_ascii=False))


class DesignContractHintsTests(unittest.TestCase):
    def test_scope_missing_lists_shapes(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        study = Path(tmp.name) / "study"
        shutil.copytree(SAMPLE, study)
        payload = json.loads((study / "study.json").read_text(encoding="utf-8"))
        payload.pop("scope", None)
        payload.pop("decision", None)
        (study / "study.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        completed = run_cli("check", str(study), "--stage", "design")
        detail = json.dumps(json.loads(completed.stdout), ensure_ascii=False)
        self.assertIn("target_users (array of strings)", detail)
        self.assertIn("options (array with at least 2 choices)", detail)
        self.assertIn("source_time_window (object with start/end as YYYY-MM-DD)", detail)


class McpAliasTests(unittest.TestCase):
    def test_query_alias_accepted(self) -> None:
        ns = MCP._build_route({"query": "家居摄像头夜间误报"})
        self.assertEqual(ns.need, "家居摄像头夜间误报")

    def test_need_still_preferred(self) -> None:
        ns = MCP._build_route({"need": "甲", "query": "乙"})
        self.assertEqual(ns.need, "甲")

    def test_missing_both_raises(self) -> None:
        with self.assertRaises(ValueError):
            MCP._build_route({"domain": "hardware"})


class EnglishRoutingTests(unittest.TestCase):
    def test_english_hardware_query_routes_without_domain(self) -> None:
        result = ENGINE.detect_domain("home security camera false alerts at night")
        self.assertEqual(result["domain"], "hardware")
        self.assertFalse(result["needs_domain"])

    def test_english_software_query_routes(self) -> None:
        result = ENGINE.detect_domain("SaaS subscription churn, why users do not renew")
        self.assertEqual(result["domain"], "software")


class ContradictionFollowUpTests(unittest.TestCase):
    def test_follow_ups_flag_chain_only_registration(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        study = Path(tmp.name) / "study"
        shutil.copytree(SAMPLE, study)
        # Register R09 the minimal way: chain counter list only. The revision
        # accepts it, but the full gate needs more — follow-ups must say so.
        evidence = study / "02-data" / "evidence.jsonl"
        template = json.loads(evidence.read_text(encoding="utf-8").splitlines()[0])
        record = dict(template)
        record.update({
            "record_id": "R09",
            "text": "Pilot household cancelled after one week",
            "evidence_level": "E1",
            "evidence_basis": "human graded",
            "source_ref": "raw/r09.txt",
            "source_family": "interviews",
            "normalized_text_hash": "",
            "consequence": "",
        })
        with evidence.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        path = study / "04-findings" / "product-reasoning.json"
        reasoning = json.loads(path.read_text(encoding="utf-8"))
        chain = reasoning["chains"][0]
        chain["counter_evidence_ids"] = sorted(set(chain.get("counter_evidence_ids", [])) | {"R09"})
        path.write_text(json.dumps(reasoning, ensure_ascii=False, indent=2), encoding="utf-8")
        self.assertEqual(run_cli("decision", "record", str(study), "--chain", "PR01",
                                 "--by", "po", "--decision", "go").returncode, 0)
        completed = run_cli("decision", "record", str(study), "--chain", "PR01",
                            "--by", "po", "--contradiction", "R09")
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "recorded")
        follow_ups = json.dumps(payload.get("full_gate_follow_ups", []), ensure_ascii=False)
        self.assertIn("counter_evidence_ids", follow_ups)
        self.assertIn("normalized fields", follow_ups)
        self.assertIn("source-plan.csv", follow_ups)


if __name__ == "__main__":
    unittest.main()
