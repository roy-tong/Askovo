from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "skills/askovo/scripts/askovo_mcp.py"


def call(requests):
    payload = "\n".join(json.dumps(item) for item in requests) + "\n"
    completed = subprocess.run(
        [sys.executable, str(SERVER)], input=payload, check=False,
        capture_output=True, text=True, timeout=120,
    )
    return [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]


def body(response):
    return json.loads(response["result"]["content"][0]["text"])


class RoleMcpTests(unittest.TestCase):
    def test_role_tools_share_cli_catalog(self) -> None:
        responses = call([
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "askovo_roles", "arguments": {"action": "list", "lifecycle": "L10"}}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "askovo_roles", "arguments": {
                 "action": "recommend", "goal": "医疗器械形成性人因研究", "stage": "validation"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "askovo_roles", "arguments": {
                 "action": "show", "role": "R80", "industry": "consumer_software"}}},
        ])
        by_id = {item.get("id"): item for item in responses}
        names = {item["name"] for item in by_id[1]["result"]["tools"]}
        self.assertIn("askovo_roles", names)
        listed = body(by_id[2])
        self.assertEqual(0, listed["exit_code"])
        self.assertEqual({"R79", "R80"}, {item["id"] for item in listed["result"]["roles"]})
        recommended = body(by_id[3])["result"]
        self.assertEqual("medical_health", recommended["industry"]["id"])
        self.assertEqual("R76", recommended["lead_role_id"])
        self.assertEqual("validate", recommended["task"]["id"])
        self.assertEqual("分层验证报告 + 放行/缺口清单", recommended["output_plan"]["expression"]["format"])
        shown = body(by_id[4])["result"]
        self.assertEqual("R80", shown["id"])
        self.assertGreaterEqual(len(shown["deliverables"]), 2)

    def test_role_action_required_fields_and_roles_array_are_enforced(self) -> None:
        responses = call([
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
             "params": {"name": "askovo_roles", "arguments": {"action": "show"}}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "askovo_roles", "arguments": {"action": "recommend"}}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "askovo_roles", "arguments": {"action": "scaffold", "study_dir": ""}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "askovo_roles", "arguments": {"action": "scaffold", "study_dir": "/tmp/unused", "roles": "R09"}}},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
             "params": {"name": "askovo_deliver", "arguments": {"study_dir": "/tmp/unused", "kind": "role"}}},
        ])
        for response in responses:
            self.assertEqual(-32602, response["error"]["code"])
        self.assertIn("role", responses[0]["error"]["message"])
        self.assertIn("goal", responses[1]["error"]["message"])
        self.assertIn("study_dir", responses[2]["error"]["message"])
        self.assertIn("array", responses[3]["error"]["message"])

    def test_scaffold_role_and_lifecycle_delivery_through_mcp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            study = Path(directory) / "sample"
            shutil.copytree(ROOT / "examples/sample-study", study)
            responses = call([
                {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                 "params": {"name": "askovo_roles", "arguments": {
                     "action": "scaffold", "study_dir": str(study), "roles": ["R09"], "chain": "PR01"}}},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                 "params": {"name": "askovo_deliver", "arguments": {
                     "study_dir": str(study), "kind": "role", "role": "R09", "chain": "PR01"}}},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                 "params": {"name": "askovo_deliver", "arguments": {"study_dir": str(study), "kind": "lifecycle"}}},
            ])
            by_id = {item.get("id"): item for item in responses}
            scaffolded = body(by_id[1])
            self.assertEqual(0, scaffolded["exit_code"], scaffolded)
            self.assertEqual("PR01", scaffolded["result"]["chain_id"])
            delivered = body(by_id[2])
            self.assertEqual(0, delivered["exit_code"], delivered)
            self.assertTrue(delivered["result"]["workplan_bound"])
            self.assertTrue(Path(delivered["result"]["path"]).is_file())
            lifecycle = body(by_id[3])
            self.assertEqual(0, lifecycle["exit_code"], lifecycle)
            self.assertTrue(lifecycle["result"]["workplan_bound"])


if __name__ == "__main__":
    unittest.main()
