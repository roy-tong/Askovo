#!/usr/bin/env python3
"""A-09: one evidence authority, structured decision direction, explicit chain.

These freeze the three review findings:
  1. an unregistered/unqualified raw row must not join the answer's support;
  2. a corrupt evidence file must refuse a trusted answer, not shrink the corpus;
  3. formal go/no-go comes from the option identity, and a multi-chain study
     never silently projects chains[0].
"""
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
if str(CLI.parent) not in sys.path:
    sys.path.append(str(CLI.parent))

import sure_engine  # noqa: E402

QUESTION = "家庭安防摄像头下一步做移动巡检还是保持固定摄像头？"
OPTIONS = ["上线移动巡检试点", "保持固定摄像头方案", "停止该概念"]


def run_cli(*args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run([sys.executable, str(CLI), *args],
                          check=False, capture_output=True, text=True,
                          timeout=180, env=env)


class _Study(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.study = Path(tmp.name) / "study"
        shutil.copytree(SAMPLE, self.study)
        document = json.loads((self.study / "study.json").read_text(encoding="utf-8"))
        document["decision"]["question"] = QUESTION
        document["decision"]["options"] = list(OPTIONS)
        document["decision"]["option_directions"] = {
            "option-A": "go", "option-B": "no_go", "option-C": "no_go"}
        (self.study / "study.json").write_text(
            json.dumps(document, ensure_ascii=False), encoding="utf-8")

    def import_lines(self, lines, family="paste_a"):
        source = self.study.parent / (family + ".jsonl")
        source.write_text("".join(
            json.dumps({"text": line}, ensure_ascii=False) + "\n" for line in lines),
            encoding="utf-8")
        completed = run_cli("import", str(self.study), str(source),
                            "--source-family", family, "--evidence-level", "E1")
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)


class EvidenceAuthorityTests(_Study):
    def setUp(self) -> None:
        super().setUp()
        (self.study / "02-data/evidence.jsonl").write_text("", encoding="utf-8")

    def test_unqualified_row_cannot_join_support_counts(self):
        self.import_lines(["移动巡检能先判断再叫我起床，我愿意试用。",
                           "固定机位已经够用，我不想转动的镜头。"])
        evidence = self.study / "02-data/evidence.jsonl"
        with evidence.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({  # no evidence_level, no record_id
                "text": "移动巡检 移动巡检 移动巡检 我也要", "source_ref": "raw-row",
            }, ensure_ascii=False) + "\n")
        answer = sure_engine.answer_study(self.study)
        cited = [ref["record_id"] for entry in answer["support"]
                 for ref in entry["supporting_refs"] + entry["counter_refs"]]
        self.assertTrue(cited)
        self.assertEqual(answer["evidence_store"]["qualified_records"],
                         answer["evidence_summary"]["records"])
        self.assertEqual(2, answer["evidence_summary"]["records"])
        self.assertTrue(answer["evidence_store"]["valid"])

    def test_corrupt_store_refuses_a_trusted_answer(self):
        self.import_lines(["移动巡检能先判断再叫我起床，我愿意试用。"])
        evidence = self.study / "02-data/evidence.jsonl"
        with evidence.open("a", encoding="utf-8") as handle:
            handle.write("{this is not json\n")
        answer = sure_engine.answer_study(self.study)
        self.assertEqual("invalid_evidence_store", answer["answer_status"])
        self.assertEqual("unanswerable", answer["decision"])
        self.assertFalse(answer["evidence_store"]["valid"])
        self.assertTrue(answer["evidence_store"]["problems"])
        self.assertIn("损坏", json.dumps(answer["gaps"], ensure_ascii=False))

    def test_corrupt_store_cannot_be_overridden_by_a_ready_record(self):
        shutil.copyfile(SAMPLE / "02-data/evidence.jsonl",
                        self.study / "02-data/evidence.jsonl")
        reasoning_path = self.study / "04-findings/product-reasoning.json"
        reasoning = json.loads(reasoning_path.read_text(encoding="utf-8"))
        for chain in reasoning.get("chains") or []:
            chain["counter_evidence_ids"] = []
        reasoning_path.write_text(json.dumps(reasoning, ensure_ascii=False),
                                  encoding="utf-8")
        completed = run_cli("decision", "record", str(self.study),
                            "--chain", "PR01", "--by", "Owner")
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertEqual("recommend",
                         sure_engine.answer_study(self.study)["business_decision"]["kind"])
        evidence = self.study / "02-data/evidence.jsonl"
        with evidence.open("a", encoding="utf-8") as handle:
            handle.write("not json either\n")
        answer = sure_engine.answer_study(self.study)
        self.assertEqual("unanswerable", answer["decision"],
                         "损坏的证据库不能推出正式 go/no_go")
        self.assertEqual("invalid_evidence_store", answer["answer_status"])


class StructuredDirectionTests(_Study):
    def _ready_decision(self):
        reasoning_path = self.study / "04-findings/product-reasoning.json"
        reasoning = json.loads(reasoning_path.read_text(encoding="utf-8"))
        for chain in reasoning.get("chains") or []:
            chain["counter_evidence_ids"] = []
        reasoning_path.write_text(json.dumps(reasoning, ensure_ascii=False),
                                  encoding="utf-8")
        completed = run_cli("decision", "record", str(self.study),
                            "--chain", "PR01", "--by", "Owner")
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def _set_options(self, options, directions):
        document = json.loads((self.study / "study.json").read_text(encoding="utf-8"))
        document["decision"]["options"] = options
        document["decision"]["option_directions"] = directions
        (self.study / "study.json").write_text(
            json.dumps(document, ensure_ascii=False), encoding="utf-8")

    def test_negated_phrase_does_not_flip_the_structured_direction(self):
        # "停止拖延，立即上线试点" contains 停止 but is a go. The old keyword rule
        # mapped it to no_go; the structured direction says go.
        self._set_options(["停止拖延，立即上线试点", "保持现状"],
                          {"option-A": "go", "option-B": "no_go"})
        reasoning_path = self.study / "04-findings/product-reasoning.json"
        reasoning = json.loads(reasoning_path.read_text(encoding="utf-8"))
        chain = reasoning["chains"][0]
        chain["nodes"]["business"]["gate"]["decision"] = "停止拖延，立即上线试点"
        reasoning_path.write_text(json.dumps(reasoning, ensure_ascii=False),
                                  encoding="utf-8")
        self._ready_decision()
        answer = sure_engine.answer_study(self.study)
        self.assertEqual("go", answer["decision"],
                         "结构化方向是 go；文字里的『停止』不能翻转它")
        self.assertEqual({"option-A": "go", "option-B": "no_go"},
                         answer["option_directions"])

    def test_missing_direction_never_reads_the_statement(self):
        self._set_options(["停止该概念", "保持现状"], {})
        reasoning_path = self.study / "04-findings/product-reasoning.json"
        reasoning = json.loads(reasoning_path.read_text(encoding="utf-8"))
        reasoning["chains"][0]["nodes"]["business"]["gate"]["decision"] = "停止该概念"
        reasoning_path.write_text(json.dumps(reasoning, ensure_ascii=False),
                                  encoding="utf-8")
        document = json.loads((self.study / "study.json").read_text(encoding="utf-8"))
        document["decision"]["options"] = ["停止该概念", "保持现状"]
        (self.study / "study.json").write_text(
            json.dumps(document, ensure_ascii=False), encoding="utf-8")
        self._ready_decision()
        answer = sure_engine.answer_study(self.study)
        self.assertEqual("continue_research", answer["decision"])
        self.assertIn("结构化方向", json.dumps(answer["gaps"], ensure_ascii=False))


class MultiChainTests(_Study):
    def _duplicate_chain(self):
        path = self.study / "04-findings/product-reasoning.json"
        reasoning = json.loads(path.read_text(encoding="utf-8"))
        second = json.loads(json.dumps(reasoning["chains"][0]))
        second["id"] = "PR02"
        second["title"] = "Second candidate chain"
        reasoning["chains"].append(second)
        path.write_text(json.dumps(reasoning, ensure_ascii=False), encoding="utf-8")
        return path

    def test_two_chains_without_a_record_refuse_to_pick_the_first(self):
        self._duplicate_chain()
        self.import_lines(["移动巡检能先判断再叫我起床，我愿意试用。"])
        answer = sure_engine.answer_study(self.study)
        business = answer["business_decision"]
        self.assertEqual("needs_chain_selection", business["status"])
        self.assertEqual(["PR01", "PR02"], business["chain_candidates"])
        self.assertNotIn(answer["decision"], ("go", "no_go"))

    def test_latest_record_names_the_live_chain(self):
        path = self._duplicate_chain()
        reasoning = json.loads(path.read_text(encoding="utf-8"))
        for chain in reasoning["chains"]:
            chain["counter_evidence_ids"] = []
        path.write_text(json.dumps(reasoning, ensure_ascii=False), encoding="utf-8")
        completed = run_cli("decision", "record", str(self.study),
                            "--chain", "PR02", "--by", "Owner")
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        answer = sure_engine.answer_study(self.study)
        record = answer["business_decision"]["decision_record"]
        self.assertEqual("Owner", record["decision_maker"])
        self.assertEqual("PR02", record.get("chain_id", "PR02"))


if __name__ == "__main__":
    unittest.main()
