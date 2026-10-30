from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MCP_SERVER = ROOT / "skills/user-demand-research/scripts/sure_mcp.py"


def run_mcp(*requests: dict) -> list[dict]:
    lines = "\n".join(json.dumps(request) for request in requests) + "\n"
    completed = subprocess.run(
        [sys.executable, str(MCP_SERVER)],
        input=lines,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]


def tool_payload(response: dict) -> dict:
    content = response["result"]["content"]
    return json.loads(content[0]["text"])


class SureMcpServerTests(unittest.TestCase):
    def test_handshake_lists_tools_and_calls_registry(self) -> None:
        responses = run_mcp(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"},
                },
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "sure_connectors", "arguments": {"platform": "x"}},
            },
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "sure_platform_map", "arguments": {}},
            },
        )
        by_id = {response.get("id"): response for response in responses}
        initialize = by_id[1]["result"]
        self.assertEqual("user-demand-research", initialize["serverInfo"]["name"])
        self.assertIn("tools", initialize["capabilities"])
        self.assertIn("sure_plan", initialize["instructions"])
        self.assertIn("exit codes", initialize["instructions"])
        tool_names = {tool["name"] for tool in by_id[2]["result"]["tools"]}
        self.assertIn("sure_plan", tool_names)
        self.assertIn("sure_report", tool_names)
        self.assertIn("sure_lexicon", tool_names)
        self.assertIn("sure_audit", tool_names)
        for name in ("sure_route", "sure_do", "sure_platforms", "sure_collect", "sure_analyze"):
            self.assertIn(name, tool_names)

        connectors = tool_payload(by_id[3])
        self.assertEqual(0, connectors["exit_code"])
        self.assertEqual(["x-tweepy"], [item["id"] for item in connectors["result"]["connectors"]])

        platform_map = tool_payload(by_id[4])
        self.assertEqual(0, platform_map["exit_code"])
        self.assertEqual(
            "supported", platform_map["result"]["platforms"]["reddit"]["registry_decision"]
        )



    def test_single_entry_route_and_platform_plan_through_mcp(self) -> None:
        responses = run_mcp(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "sure_route",
                    "arguments": {"need": "手机相机夜景和续航"},
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "sure_do",
                    "arguments": {"need": "手机相机夜景和续航", "dry_run": True},
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "sure_platforms",
                    "arguments": {"need": "手机相机夜景的用户抱怨", "domain": "mobile", "bulk": True},
                },
            },
        )
        by_id = {response.get("id"): response for response in responses}
        routed = tool_payload(by_id[1])
        self.assertEqual(0, routed["exit_code"])
        self.assertEqual("mobile", routed["result"]["domain"])
        self.assertIn("recommended_methods", routed["result"])
        dry = tool_payload(by_id[2])
        self.assertEqual(0, dry["exit_code"])
        self.assertEqual("mobile", dry["result"]["domain"])
        platforms = tool_payload(by_id[3])
        self.assertEqual(0, platforms["exit_code"])
        ids = [item["id"] for item in platforms["result"]["recommended"]]
        self.assertIn("reddit", ids)

    def test_plan_then_check_through_mcp_tools(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            study_dir = str(Path(directory) / "study")
            responses = run_mcp(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "sure_plan",
                        "arguments": {
                            "study_dir": study_dir,
                            "goal": "AI glasses complaints overseas",
                            "region": "overseas",
                            "sample_size": 5000,
                            "platform_types": "forum,social",
                        },
                    },
                },
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "sure_check",
                        "arguments": {"study_dir": study_dir, "stage": "design"},
                    },
                },
            )
            by_id = {response.get("id"): response for response in responses}
            planned = tool_payload(by_id[1])
            self.assertEqual(0, planned["exit_code"])
            self.assertEqual(["reddit", "x"], planned["result"]["feasible_platforms"])
            self.assertEqual(5000, sum(planned["result"]["platform_quotas"].values()))
            design = tool_payload(by_id[2])
            self.assertEqual(1, design["exit_code"])
            self.assertEqual("fail", design["result"]["status"])

    def test_missing_required_argument_returns_invalid_params(self) -> None:
        responses = run_mcp(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "sure_plan", "arguments": {"goal": "no paths"}},
            }
        )
        error = responses[0].get("error")
        self.assertIsNotNone(error)
        self.assertEqual(-32602, error["code"])
        self.assertIn("study_dir", error["message"])

    def test_unknown_tool_returns_invalid_params(self) -> None:
        responses = run_mcp(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "sure_telepathy", "arguments": {}},
            }
        )
        self.assertEqual(-32602, responses[0]["error"]["code"])


if __name__ == "__main__":
    unittest.main()
