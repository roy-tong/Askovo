from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/askovo/scripts/askovo.py"
REASONING_RELATIVE = Path("04-findings/product-reasoning.json")


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


class ChainNodeEditingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.study = Path(self.temp.name) / "study"
        self.study.mkdir()
        (self.study / "study.json").write_text(
            json.dumps({"study_id": "chain-node-test", "title": "chain node test"}),
            encoding="utf-8",
        )
        scaffold = run_cli("chain", str(self.study))
        self.assertEqual(0, scaffold.returncode, scaffold.stderr)
        self.reasoning_path = self.study / REASONING_RELATIVE
        self.reasoning = json.loads(self.reasoning_path.read_text(encoding="utf-8"))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def add_evidence(self, record_id: str, level: str = "E1") -> None:
        path = self.study / "02-data" / "evidence.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "record_id": record_id,
                "evidence_level": level,
                "claim_type": "need",
                "context_key": "ctx",
            }, ensure_ascii=False) + "\n")

    def load_node(self, node: str, chain_index: int = 0) -> dict:
        data = json.loads(self.reasoning_path.read_text(encoding="utf-8"))
        return data["chains"][chain_index]["nodes"][node]

    def test_set_writes_node_and_change_log(self) -> None:
        completed = run_cli(
            "chain-node", str(self.study), "set", "--node", "pain",
            "--statement", "用户在固定摄像头盲区里无法确认宠物状态",
            "--rationale", "场景与用户记录都指向同一个验证缺口",
            "--status", "needs-validation",
            "--note", "人工把痛点从占位改成可审判断",
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual("updated", payload["status"])
        self.assertEqual("PR01", payload["chain"])
        self.assertEqual("pain", payload["node"])
        self.assertEqual(["statement", "rationale", "status"], payload["changed_fields"])
        self.assertEqual(["PR01.pain"], payload["affected_refs"])
        self.assertNotEqual("pass", payload["audit_status"])
        self.assertIn("askovo check", payload["next_step"])

        node = self.load_node("pain")
        self.assertEqual("用户在固定摄像头盲区里无法确认宠物状态", node["statement"])
        self.assertEqual("needs-validation", node["status"])
        self.assertEqual("待填写", node["current_substitute"])

        chain = json.loads(self.reasoning_path.read_text(encoding="utf-8"))["chains"][0]
        self.assertEqual(1, len(chain["change_log"]))
        entry = chain["change_log"][0]
        for field in ("id", "impact", "decision", "projection_sync"):
            self.assertTrue(entry.get(field), field)
        self.assertEqual("pending", entry["projection_sync"])
        self.assertEqual(["PR01.pain"], entry["affected_refs"])
        self.assertEqual("待填写", entry["previous"]["statement"])

    def test_unknown_node_fails_and_leaves_file_byte_identical(self) -> None:
        before = digest(self.reasoning_path)
        completed = run_cli(
            "chain-node", str(self.study), "set", "--node", "not-a-node",
            "--statement", "x",
        )
        self.assertEqual(2, completed.returncode)
        self.assertIn("可用节点", completed.stderr)
        self.assertEqual(before, digest(self.reasoning_path))

    def test_unknown_chain_fails_and_lists_available_values(self) -> None:
        before = digest(self.reasoning_path)
        completed = run_cli(
            "chain-node", str(self.study), "set", "--chain", "PR99",
            "--node", "pain", "--statement", "x",
        )
        self.assertEqual(2, completed.returncode)
        self.assertIn("PR01", completed.stderr)
        self.assertEqual(before, digest(self.reasoning_path))

    def test_same_value_is_unchanged_and_does_not_rewrite(self) -> None:
        first = run_cli(
            "chain-node", str(self.study), "set", "--node", "pain",
            "--statement", "same value",
        )
        self.assertEqual(0, first.returncode, first.stderr)
        after_first = digest(self.reasoning_path)
        second = run_cli(
            "chain-node", str(self.study), "set", "--node", "pain",
            "--statement", "same value",
        )
        self.assertEqual(0, second.returncode, second.stderr)
        payload = json.loads(second.stdout)
        self.assertEqual("unchanged", payload["status"])
        self.assertEqual([], payload["changed_fields"])
        self.assertIsNone(payload["change_log_id"])
        self.assertEqual(after_first, digest(self.reasoning_path))
        chain = json.loads(self.reasoning_path.read_text(encoding="utf-8"))["chains"][0]
        self.assertEqual(1, len(chain["change_log"]))

    def test_bind_unknown_evidence_fails_without_write(self) -> None:
        before = digest(self.reasoning_path)
        completed = run_cli(
            "chain-node", str(self.study), "bind-evidence",
            "--node", "pain", "--evidence", "R404",
        )
        self.assertEqual(2, completed.returncode)
        self.assertIn("证据库没有", completed.stderr)
        self.assertIn("R404", completed.stderr)
        self.assertEqual(before, digest(self.reasoning_path))

    def test_bind_is_idempotent_and_unbind_updates_change_log(self) -> None:
        self.add_evidence("R01")
        self.add_evidence("R02")
        first = run_cli(
            "chain-node", str(self.study), "bind-evidence",
            "--node", "pain", "--evidence", "R01", "--evidence", "R02",
        )
        self.assertEqual(0, first.returncode, first.stderr)
        self.assertEqual(["R01", "R02"], json.loads(first.stdout)["evidence_ids"])
        self.assertEqual({"R01": "E1", "R02": "E1"}, json.loads(first.stdout)["evidence_levels"])

        before = digest(self.reasoning_path)
        again = run_cli(
            "chain-node", str(self.study), "bind-evidence",
            "--node", "pain", "--evidence", "R01",
        )
        self.assertEqual(0, again.returncode, again.stderr)
        self.assertEqual("unchanged", json.loads(again.stdout)["status"])
        self.assertEqual(before, digest(self.reasoning_path))

        chain = json.loads(self.reasoning_path.read_text(encoding="utf-8"))["chains"][0]
        self.assertEqual(1, len(chain["change_log"]))
        self.assertEqual(["R01", "R02"], chain["change_log"][0]["reason_evidence_ids"])

        removed = run_cli(
            "chain-node", str(self.study), "unbind-evidence",
            "--node", "pain", "--evidence", "R01",
        )
        self.assertEqual(0, removed.returncode, removed.stderr)
        self.assertEqual(["R02"], self.load_node("pain")["evidence_ids"])
        chain = json.loads(self.reasoning_path.read_text(encoding="utf-8"))["chains"][0]
        self.assertEqual(2, len(chain["change_log"]))
        self.assertEqual(["R01"], chain["change_log"][1]["reason_evidence_ids"])

        missing = run_cli(
            "chain-node", str(self.study), "unbind-evidence",
            "--node", "pain", "--evidence", "R01",
        )
        self.assertEqual(2, missing.returncode)
        self.assertIn("未绑定", missing.stderr)

    def test_chain_can_be_selected_by_index(self) -> None:
        data = json.loads(self.reasoning_path.read_text(encoding="utf-8"))
        second = json.loads(json.dumps(data["chains"][0]))
        second["id"] = "PR02"
        data["chains"].append(second)
        self.reasoning_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        completed = run_cli(
            "chain-node", str(self.study), "set", "--chain", "2",
            "--node", "need", "--statement", "second chain need",
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual("PR02", payload["chain"])
        self.assertEqual(["PR02.need"], payload["affected_refs"])
        self.assertEqual("second chain need", self.load_node("need", 1)["statement"])
        self.assertEqual("待填写", self.load_node("need", 0)["statement"])

    def test_show_is_read_only(self) -> None:
        before = digest(self.reasoning_path)
        completed = run_cli(
            "chain-node", str(self.study), "show", "--node", "business",
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual("shown", payload["status"])
        self.assertEqual("business", payload["node"])
        self.assertIn("gate", payload["node_payload"])
        self.assertTrue(payload["next_step"])
        self.assertEqual(before, digest(self.reasoning_path))

    def test_chain_next_step_points_at_chain_node(self) -> None:
        result = run_cli("chain", str(self.study))
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("chain-node", payload["next_step"])


if __name__ == "__main__":
    unittest.main()
