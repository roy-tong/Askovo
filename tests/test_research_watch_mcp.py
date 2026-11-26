from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from skills.askovo.scripts import askovo_mcp

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "examples/sample-study"


class ResearchWatchMcpTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.study = Path(tmp.name) / "study"
        shutil.copytree(SAMPLE, self.study)

    def call(self, action: str, **extra):
        return askovo_mcp._run_tool("askovo_research_watch", dict(
            action=action, study_dir=str(self.study), **extra))

    def test_manifest_exposes_only_local_watch_actions(self) -> None:
        tool = next(row for row in askovo_mcp.TOOLS if row["name"] == "askovo_research_watch")
        actions = tool["inputSchema"]["properties"]["action"]["enum"]
        self.assertEqual({"create", "status", "run", "execute", "pause", "resume", "resolution"}, set(actions))
        self.assertFalse(any("serve" in action or "collect" in action for action in actions))

    def test_mcp_create_run_pause_resume_and_status(self) -> None:
        created = self.call(
            "create", question="Track demand changes", interval_hours=24, by="research-owner")
        self.assertEqual(0, created["exit_code"], created)
        self.assertEqual("W001", created["result"]["watch"]["watch_id"])
        ran = self.call("run")
        self.assertEqual(0, ran["exit_code"], ran)
        self.assertEqual("completed", ran["result"]["status"])
        self.assertFalse(ran["result"]["new_evidence_collected"])
        paused = self.call("pause", watch_id="W001")
        self.assertEqual("paused", paused["result"]["status"])
        self.assertEqual("no_due_watches", self.call("run")["result"]["status"])
        resumed = self.call("resume", watch_id="W001")
        self.assertEqual("resumed", resumed["result"]["status"])
        status = self.call("status", due=True)
        self.assertEqual(1, status["result"]["due_count"])

    def test_skill_documents_external_tick_and_evidence_boundary(self) -> None:
        text = (ROOT / "skills/askovo/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("askovo watch create", text)
        self.assertIn("external cron/host", text)
        self.assertIn("askovo_research_watch", text)
        self.assertIn("no network collection", text)


if __name__ == "__main__":
    unittest.main()
