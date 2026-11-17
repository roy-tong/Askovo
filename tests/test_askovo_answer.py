#!/usr/bin/env python3
"""Research answer projection: conclusions follow the evidence, never invent it.

Golden-chain acceptance (review 2026-11-17 §4.1): two opposite corpora must
flip the conclusion, every key judgment back-links to collected source ids,
and no evidence means unanswerable + gap list, not a fabricated answer.
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
    # append (never insert): scripts/askovo.py would shadow the root package
    sys.path.append(str(CLI.parent))

import sure_engine  # noqa: E402


def run_cli(*args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run([sys.executable, str(CLI), *args],
                          check=False, capture_output=True, text=True, timeout=180, env=env)


QUESTION = "家庭安防摄像头下一步做移动巡检还是保持固定摄像头？"
OPTIONS = ["上线移动巡检试点", "保持固定摄像头方案", "停止该概念"]

CORPUS_A = [  # supports the mobile-patrol pilot
    "用户说：夜间误报太多，移动巡检能先判断再叫我起床，我愿意试用。",
    "租客反馈：固定视角拍不到门口，移动巡检覆盖盲区，正合我意。",
    "宠物主人：出门时最担心盲区，移动巡检主动看一圈让我安心不少。",
    "老人家属：误报一响全家紧张，能移动查看再报警的产品才是我要的。",
]
CORPUS_B = [  # supports keeping the fixed-camera concept (worded without the
    # rival option's distinctive terms, like a real either-or corpus)
    "用户说：转动的东西容易坏，我就是要固定摄像头全天盯着门口。",
    "物业反馈：固定摄像头装一次就不动，维护成本低，省心。",
    "店主：固定摄像头已经覆盖全部通道，够用了，不加钱。",
    "邻居：转动的镜头让人不安，固定摄像头明确不拍别人家，我才放心。",
]


class AnswerCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.study = Path(tmp.name) / "study"
        shutil.copytree(SAMPLE, self.study)
        document = json.loads((self.study / "study.json").read_text(encoding="utf-8"))
        document["decision"]["question"] = QUESTION
        document["decision"]["options"] = list(OPTIONS)
        (self.study / "study.json").write_text(
            json.dumps(document, ensure_ascii=False), encoding="utf-8")
        # the golden chain starts from the study's own evidence state
        (self.study / "02-data/evidence.jsonl").write_text("", encoding="utf-8")

    def _import_corpus(self, lines: list[str], family: str, **flags: str) -> None:
        # pasted notes as JSONL: one record per note (a whole .txt is one record)
        source = self.study.parent / f"{family}.jsonl"
        source.write_text(
            "".join(json.dumps({"text": line}, ensure_ascii=False) + "\n" for line in lines),
            encoding="utf-8")
        args = ["import", str(self.study), str(source), "--source-family", family,
                "--evidence-level", "E1"]
        for key, value in flags.items():
            args += [f"--{key.replace('_', '-')}", value]
        completed = run_cli(*args)
        assert completed.returncode == 0, completed.stdout + completed.stderr

    def _answer(self) -> dict:
        result = sure_engine.answer_study(self.study)
        return result


class OppositeCorporaTests(AnswerCase):
    def test_conclusion_flips_with_the_evidence_and_back_links(self) -> None:
        self._import_corpus(CORPUS_A, "paste_a")
        answer_a = self._answer()
        self.assertEqual("supported", answer_a["answer_status"])
        self.assertEqual(OPTIONS[0], answer_a["leading_option"])
        self.assertEqual("go", answer_a["decision"])
        ids_a = {ref["record_id"] for ref in answer_a["support"][0]["supporting_refs"]}
        self.assertGreaterEqual(len(ids_a), 3)

        fresh = Path(tempfile.mkdtemp(prefix="askovo-answer-b-")) / "study"
        shutil.copytree(SAMPLE, fresh)
        document = json.loads((fresh / "study.json").read_text(encoding="utf-8"))
        document["decision"]["question"] = QUESTION
        document["decision"]["options"] = list(OPTIONS)
        (fresh / "study.json").write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        (fresh / "02-data/evidence.jsonl").write_text("", encoding="utf-8")
        source = fresh.parent / "paste_b.jsonl"
        source.write_text(
            "".join(json.dumps({"text": line}, ensure_ascii=False) + "\n"
                    for line in CORPUS_B), encoding="utf-8")
        completed = run_cli("import", str(fresh), str(source),
                            "--source-family", "paste_b", "--evidence-level", "E1")
        assert completed.returncode == 0, completed.stdout
        answer_b = sure_engine.answer_study(fresh)
        self.assertEqual("supported", answer_b["answer_status"])
        self.assertEqual(OPTIONS[1], answer_b["leading_option"],
                         "opposite corpus must flip the conclusion")
        self.assertEqual("go", answer_b["decision"])

        # back-links: every cited record exists in the evidence store
        for answer, study in ((answer_a, self.study), (answer_b, fresh)):
            stored = {json.loads(line)["record_id"]
                      for line in (study / "02-data/evidence.jsonl").read_text(
                          encoding="utf-8").splitlines() if line.strip()}
            for option in answer["support"]:
                for ref in option["supporting_refs"] + option["counter_refs"]:
                    self.assertIn(ref["record_id"], stored)
                    self.assertTrue(ref["source_ref"])

    def test_counter_evidence_is_never_outvoted(self) -> None:
        self._import_corpus(CORPUS_A, "paste_a")
        counter = self.study.parent / "counter.txt"
        counter.write_text(
            "隐私敏感用户：会转动的移动巡检镜头让室友不安，我们拒绝了它。\n", encoding="utf-8")
        completed = run_cli("import", str(self.study), str(counter),
                            "--source-family", "counter_paste", "--evidence-level", "E1",
                            "--corpus-role", "substitute_rejector")
        assert completed.returncode == 0, completed.stdout
        answer = self._answer()
        self.assertEqual("contested", answer["answer_status"])
        self.assertEqual("continue_research", answer["decision"])
        self.assertTrue(answer["support"][0]["counter_refs"])

    def test_no_evidence_means_unanswerable_with_gap_list(self) -> None:
        answer = self._answer()
        self.assertEqual("unanswerable", answer["answer_status"])
        self.assertEqual("unanswerable", answer["decision"])
        self.assertIsNone(answer["leading_option"])
        gaps = json.dumps(answer["gaps"], ensure_ascii=False)
        self.assertIn("Problem and substitute evidence", gaps)
        self.assertGreaterEqual(len(answer["gaps"]), 3)
        self.assertNotIn("leading_option_supported", json.dumps(answer))


class CapturePathTests(AnswerCase):
    def test_accepted_capture_feeds_the_answer_with_capture_backlinks(self) -> None:
        import capture_review  # noqa: E402

        document = json.loads((self.study / "study.json").read_text(encoding="utf-8"))
        document["scope"]["allowed_sources"] = ["amazon"]
        document["source_adapters"] = {"amazon": {"enabled": True}}
        (self.study / "study.json").write_text(json.dumps(document, ensure_ascii=False),
                                               encoding="utf-8")

        class _FakeClient:
            def __init__(self, ws):
                self.ws = ws

            def call(self, method, params=None):
                if method == "Page.captureScreenshot":
                    return {"data": "aGVsbG8="}
                return {}

            def evaluate(self, expression):
                return {"title": "论坛页", "url": "https://www.amazon.com/product-reviews/B0",
                        "text": "\n".join(CORPUS_A[:1])}

            def close(self):
                pass

        saved = (sure_engine.cdp_new_page, sure_engine._WebSocket, sure_engine.CDPClient)
        sure_engine.cdp_new_page = lambda base, url: "ws://127.0.0.1:9222/devtools/page/1"
        sure_engine._WebSocket = lambda url: object()
        sure_engine.CDPClient = _FakeClient
        try:
            captured = sure_engine.capture_page(
                self.study, "https://www.amazon.com/product-reviews/B0", "http://127.0.0.1:9222", True)
        finally:
            sure_engine.cdp_new_page, sure_engine._WebSocket, sure_engine.CDPClient = saved
        self.assertEqual("captured", captured["status"])
        capture_id = Path(captured["capture"]).stem
        accepted = capture_review.accept(self.study, capture_id, by="验收员", evidence_level="E1")
        self.assertEqual("accepted", accepted["status"])

        self._import_corpus(CORPUS_A[1:], "paste_a")
        answer = self._answer()
        refs = answer["support"][0]["supporting_refs"]
        cap_refs = [ref for ref in refs if ref.get("capture_id") == capture_id]
        self.assertEqual(1, len(cap_refs))
        self.assertIn("captures/" + capture_id, cap_refs[0]["source_ref"])


class AnswerCliTests(AnswerCase):
    def test_cli_answer_writes_json_and_markdown(self) -> None:
        self._import_corpus(CORPUS_A, "paste_a")
        completed = run_cli("answer", str(self.study))
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual("go", payload["decision"])
        self.assertTrue((self.study / "04-findings/research-answer.json").is_file())
        markdown = (self.study / "04-findings/research-answer.md").read_text(encoding="utf-8")
        self.assertIn(OPTIONS[0], markdown)
        self.assertIn("回链", markdown)

    def test_cli_answer_unanswerable_exits_zero_with_gaps(self) -> None:
        completed = run_cli("answer", str(self.study))
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual("unanswerable", payload["decision"])
        self.assertTrue(payload["gaps"])


if __name__ == "__main__":
    unittest.main()
