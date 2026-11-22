from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/askovo/scripts/askovo.py"
SCRIPTS = ROOT / "skills/askovo/scripts"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


engine = _load("askovo_cdp_expansion_engine_test", SCRIPTS / "sure_engine.py")
mcp = _load("askovo_cdp_expansion_mcp_test", SCRIPTS / "askovo_mcp.py")


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        check=False,
        capture_output=True,
        text=True,
    )


class CdpSourcePlanTests(unittest.TestCase):
    def test_100000_record_plan_includes_instagram_and_discord_cdp_routes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            study = Path(directory) / "study"
            completed = run_cli(
                "plan", str(study),
                "--goal", "Motion capture feedback and substitutes",
                "--region", "overseas",
                "--sample-size", "100000",
                "--platform-types", "forum,social,video",
            )
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(100000, sum(payload["platform_quotas"].values()))
            self.assertIn("instagram", payload["platform_quotas"])
            self.assertIn("discord", payload["platform_quotas"])
            self.assertGreater(payload["platform_quotas"]["instagram"], 0)
            self.assertGreater(payload["platform_quotas"]["discord"], 0)
            feasibility = json.loads((study / "01-sources/feasibility.json").read_text(encoding="utf-8"))
            for platform in ("instagram", "discord"):
                route = next(
                    item for item in feasibility["platforms"]
                    if item["platform"] == platform
                )
                self.assertEqual("cdp", route["transport"])
                self.assertEqual("cdp-authorized-visible-page", route["connector_id"])
                self.assertTrue((study / "01-sources" / f"{platform}-routes.csv").is_file())
                adapter = json.loads((study / "study.json").read_text(encoding="utf-8"))[
                    "source_adapters"
                ][platform]
                self.assertTrue(adapter["enabled"])
                self.assertEqual("cdp_authorized_visible_page", adapter["access_basis"])
                self.assertEqual(engine.VERSION, adapter["connector_revision"])

    def test_plan_rejects_targets_above_100000(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            study = Path(directory) / "study"
            completed = run_cli(
                "plan", str(study),
                "--goal", "Oversized sample",
                "--region", "overseas",
                "--sample-size", "100001",
                "--platform-types", "forum",
            )
            self.assertEqual(2, completed.returncode)
            self.assertIn("100000", completed.stderr)
            self.assertFalse(study.exists())


class CdpCollectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.study = Path(self._tmp.name) / "study"
        (self.study / "01-sources").mkdir(parents=True)
        (self.study / "study.json").write_text(json.dumps({
            "study_id": "synthetic-cdp",
            "scope": {"allowed_sources": ["instagram"]},
            "source_adapters": {"instagram": {"enabled": True}},
        }), encoding="utf-8")

    def test_collect_attaches_to_the_existing_logged_in_page(self) -> None:
        url = "https://www.instagram.com/p/visible/"
        full_text = "A complete user comment about the current workaround. " * 180
        client = mock.MagicMock()
        client.evaluate.return_value = {
            "rows": [{
                "id": "comment-1",
                "text": full_text,
                "author": "visible-user",
                "source_url": url,
                "source_channel": "visible-account",
                "source_content_type": "comment",
                "created_at": "2026-11-20T10:00:00Z",
            }],
            "page_title": "Visible post",
            "page_url": url,
            "page_text": full_text,
        }
        with mock.patch.object(engine, "cdp_existing_page", return_value="ws://127.0.0.1:9222/devtools/page/1") as attach, \
                mock.patch.object(engine, "cdp_new_page") as new_page, \
                mock.patch.object(engine, "CDPClient", return_value=client), \
                mock.patch.object(engine, "_WebSocket"), \
                mock.patch.object(engine.time, "sleep"):
            result = engine.collect_platform(
                self.study,
                "instagram",
                "motion capture workaround",
                limit=1,
                cdp_url="http://127.0.0.1:9222",
                url=url,
                ack_terms=True,
                attach_existing=True,
            )
        self.assertEqual("collected", result["status"], result)
        attach.assert_called_once_with("http://127.0.0.1:9222", url)
        new_page.assert_not_called()
        raw_path = Path(result["raw_file"])
        raw = json.loads(raw_path.read_text(encoding="utf-8").strip())
        self.assertEqual(full_text, raw["text"])
        self.assertEqual("comment", raw["source_content_type"])
        self.assertEqual("visible-account", raw["source_channel"])
        manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
        self.assertEqual("attach_existing", manifest["capture_mode"])
        self.assertNotIn("cookies", json.dumps(manifest).lower())

    def test_dry_run_preserves_attach_existing_and_cdp_next_command(self) -> None:
        result = engine.collect_platform(
            self.study,
            "instagram",
            "motion capture",
            cdp_url="http://127.0.0.1:9222",
            url="https://www.instagram.com/p/visible/",
            ack_terms=True,
            attach_existing=True,
            dry_run=True,
        )
        self.assertEqual("planned", result["status"])
        self.assertTrue(result["attach_existing"])
        self.assertIn("--attach-existing", result["next"])
        self.assertIn("--cdp-url", result["next"])
        self.assertIn("--ack-terms", result["next"])

    def test_instagram_discord_and_youtube_have_dedicated_dom_extractors(self) -> None:
        self.assertIn("instagram", engine.CDP_EXTRACTORS)
        self.assertIn("discord", engine.CDP_EXTRACTORS)
        self.assertIn("youtube", engine.CDP_EXTRACTORS)
        self.assertIn("chat-messages-", engine.CDP_EXTRACTORS["discord"])
        self.assertIn("time[datetime]", engine.CDP_EXTRACTORS["instagram"])
        self.assertIn("ytd-comment-thread-renderer", engine.CDP_EXTRACTORS["youtube"])
        self.assertNotIn("slice(0, 2000)", engine.CDP_EXTRACTORS["instagram"])
        self.assertNotIn("slice(0, 2000)", engine.CDP_EXTRACTORS["discord"])

    def test_youtube_cdp_record_reaches_platform_evidence_fields(self) -> None:
        url = "https://www.youtube.com/watch?v=visible"
        (self.study / "study.json").write_text(json.dumps({
            "study_id": "synthetic-youtube",
            "scope": {"allowed_sources": ["youtube"]},
            "source_adapters": {"youtube": {
                "allow_personal_data": False, "refresh_due_at": "2027-01-01T00:00:00Z",
            }},
        }), encoding="utf-8")
        client = mock.MagicMock()
        client.evaluate.return_value = {
            "rows": [{"id": "comment-1", "text": "A complete comment " * 20,
                      "author": "visible-user", "source_url": url,
                      "source_channel": "visible-channel", "source_content_type": "comment",
                      "created_at": "2026-11-20T10:00:00Z"}],
            "page_title": "Visible video", "page_url": url, "page_text": "visible content",
        }
        with mock.patch.object(engine, "cdp_existing_page", return_value="ws://127.0.0.1:9222/devtools/page/1"), \
                mock.patch.object(engine, "CDPClient", return_value=client), \
                mock.patch.object(engine, "_WebSocket"), mock.patch.object(engine.time, "sleep"):
            result = engine.collect_cdp(self.study, "youtube", "motion capture", url,
                                        "http://127.0.0.1:9222", True,
                                        attach_existing=True, scrolls=0)
        self.assertEqual("collected", result["status"], result)
        normalized = [json.loads(line) for line in
                      (self.study / "02-data/normalized.jsonl").read_text(encoding="utf-8").splitlines()]
        record = normalized[0]
        self.assertEqual("visible", record["youtube_video_id"])
        self.assertEqual("comment-1", record["youtube_item_id"])
        self.assertEqual("top_level_comment", record["youtube_content_type"])
        self.assertEqual("comment-1", record["comment_thread_id"])
        self.assertEqual("motion capture", record["source_query"])
        self.assertEqual(0, record["source_order"])
        self.assertEqual("2027-01-01T00:00:00Z", record["refresh_due_at"])
        self.assertTrue(record["last_verified_at"])
    def test_challenge_title_stops_before_scrolling_or_writing(self) -> None:
        client = mock.MagicMock()
        client.evaluate.return_value = {
            "rows": [], "page_title": "Just a moment...",
            "page_text": "Checking your browser before accessing the site.",
            "page_url": "https://www.instagram.com/p/visible/",
        }
        with mock.patch.object(engine, "cdp_new_page", return_value="ws://127.0.0.1:9222/devtools/page/1"), \
                mock.patch.object(engine, "CDPClient", return_value=client), \
                mock.patch.object(engine, "_WebSocket"), \
                mock.patch.object(engine, "_write_run") as write_run, \
                mock.patch.object(engine.time, "sleep"):
            result = engine.collect_cdp(
                self.study, "instagram", "test", "https://www.instagram.com/p/visible/",
                "http://127.0.0.1:9222", True, scrolls=2,
            )
        self.assertEqual("challenge", result["status"])
        write_run.assert_not_called()
        self.assertEqual(1, client.evaluate.call_count)

    def test_final_url_outside_approved_host_is_not_written(self) -> None:
        client = mock.MagicMock()
        client.evaluate.return_value = {
            "rows": [{"id": "r1", "text": "A long enough record " * 10,
                      "source_url": "https://evil.example/post"}],
            "page_title": "Visible post", "page_text": "valid content",
            "page_url": "https://evil.example/post",
        }
        with mock.patch.object(engine, "cdp_new_page", return_value="ws://127.0.0.1:9222/devtools/page/1"), \
                mock.patch.object(engine, "CDPClient", return_value=client), \
                mock.patch.object(engine, "_WebSocket"), \
                mock.patch.object(engine, "_write_run") as write_run, \
                mock.patch.object(engine.time, "sleep"):
            result = engine.collect_cdp(
                self.study, "instagram", "test", "https://www.instagram.com/p/visible/",
                "http://127.0.0.1:9222", True, scrolls=0,
            )
        self.assertEqual("scope_violation", result["status"])
        write_run.assert_not_called()

    def test_no_personal_data_removes_author_from_raw_bytes(self) -> None:
        study = json.loads((self.study / "study.json").read_text(encoding="utf-8"))
        study["source_adapters"]["instagram"]["allow_personal_data"] = False
        (self.study / "study.json").write_text(json.dumps(study), encoding="utf-8")
        url = "https://www.instagram.com/p/visible/"
        client = mock.MagicMock()
        client.evaluate.return_value = {
            "rows": [{"id": "comment-1", "text": "A complete comment " * 20,
                      "author": "PRIVATE-AUTHOR-SENTINEL", "source_url": url,
                      "source_channel": "PRIVATE-AUTHOR-SENTINEL", "source_content_type": "comment"}],
            "page_title": "Visible post", "page_url": url, "page_text": "visible content",
        }
        with mock.patch.object(engine, "cdp_existing_page", return_value="ws://127.0.0.1:9222/devtools/page/1"), \
                mock.patch.object(engine, "CDPClient", return_value=client), \
                mock.patch.object(engine, "_WebSocket"), \
                mock.patch.object(engine.time, "sleep"):
            result = engine.collect_cdp(
                self.study, "instagram", "test", url, "http://127.0.0.1:9222", True,
                attach_existing=True, scrolls=0,
            )
        self.assertEqual("collected", result["status"], result)
        raw = Path(result["raw_file"]).read_text(encoding="utf-8")
        self.assertNotIn("PRIVATE-AUTHOR-SENTINEL", raw)


class CdpSurfaceParityTests(unittest.TestCase):
    def test_mcp_collect_builder_forwards_attach_existing(self) -> None:
        args = mcp._build_collect({
            "study_dir": "/tmp/study",
            "platform": "instagram",
            "query": "motion capture",
            "cdp_url": "http://127.0.0.1:9222",
            "url": "https://www.instagram.com/p/visible/",
            "ack_terms": True,
            "attach_existing": True,
        })
        self.assertTrue(getattr(args, "attach_existing", False))

    def test_skill_does_not_repeat_generic_pilot_approval_or_contradict_cdp(self) -> None:
        skill = (ROOT / "skills/askovo/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("do not ask for a second generic pilot approval", skill)
        self.assertNotIn("X/YouTube never use browser automation", skill)
        self.assertNotIn("Do not scrape or browser-automate X or YouTube", skill)
        self.assertIn("no supported connector or declared CDP route", skill)


if __name__ == "__main__":
    unittest.main()
