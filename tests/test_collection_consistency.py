from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/askovo/scripts"
CONNECTORS = SCRIPTS / "connectors"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


engine = load("collection_consistency_engine", SCRIPTS / "sure_engine.py")
sys.path.insert(0, str(CONNECTORS))
youtube = load("collection_consistency_youtube", CONNECTORS / "collect_youtube_innertube.py")
hn = load("collection_consistency_hn", CONNECTORS / "collect_hn.py")
arctic = load("collection_consistency_arctic", CONNECTORS / "collect_arctic_reddit.py")
windows = load("collection_consistency_windows", CONNECTORS / "collect_arctic_windows.py")
pullpush = load("collection_consistency_pullpush", CONNECTORS / "collect_pullpush_reddit.py")
amazon = load("collection_consistency_amazon", CONNECTORS / "collect_amazon_reviews_2023.py")
issues = load("collection_consistency_issues", SCRIPTS / "issue_structuring.py")
amazon_manifest = load("collection_consistency_amazon_manifest", CONNECTORS / "amazon_reviews_2023_manifest.py")
common = load("collection_consistency_common", CONNECTORS / "common.py")


def study(tmp: Path, platform: str = "youtube", enabled: bool = True) -> Path:
    root = tmp / "study"
    (root / "01-sources").mkdir(parents=True, exist_ok=True)
    (root / "study.json").write_text(json.dumps({
        "study_id": "audit",
        "scope": {"allowed_sources": [platform] if enabled else []},
        "source_adapters": {platform: {"enabled": enabled}},
    }), encoding="utf-8")
    return root


def cdp_client(url: str, rows: list[dict]) -> mock.MagicMock:
    client = mock.MagicMock()
    client.evaluate.return_value = {
        "rows": rows, "page_title": "Visible", "page_url": url, "page_text": "Visible body",
    }
    return client


class CollectionConsistencyTests(unittest.TestCase):
    def test_direct_cdp_requires_scope_and_enabled_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = study(Path(tmp), enabled=False)
            url = "https://www.youtube.com/watch?v=audit"
            client = cdp_client(url, [{"id": "r1", "text": "synthetic"}])
            with mock.patch.object(engine, "cdp_existing_page", return_value="ws://127.0.0.1:9222/devtools/page/audit"), \
                    mock.patch.object(engine, "CDPClient", return_value=client), \
                    mock.patch.object(engine, "_WebSocket"), \
                    mock.patch.object(engine, "_write_run") as write_run:
                result = engine.collect_cdp(root, "youtube", "audit", url, "http://127.0.0.1:9222", True,
                                            attach_existing=True, scrolls=0)
            self.assertEqual("scope_blocked", result["status"])
            write_run.assert_not_called()

    def test_cdp_zero_rows_is_unconfirmed_and_not_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = study(Path(tmp))
            url = "https://www.youtube.com/watch?v=audit-zero"
            with mock.patch.object(engine, "cdp_existing_page", return_value="ws://127.0.0.1:9222/devtools/page/audit-zero"), \
                    mock.patch.object(engine, "CDPClient", return_value=cdp_client(url, [])), \
                    mock.patch.object(engine, "_WebSocket"), \
                    mock.patch.object(engine.time, "sleep"), \
                    mock.patch.object(engine, "_write_run") as write_run:
                result = engine.collect_cdp(root, "youtube", "audit-zero", url, "http://127.0.0.1:9222", True,
                                            attach_existing=True, scrolls=0)
            self.assertEqual("empty_unconfirmed", result["status"])
            write_run.assert_not_called()

    def test_cli_failure_statuses_are_nonzero(self):
        args = SimpleNamespace(study_dir="/tmp/audit", platform="youtube", query="audit", limit=1,
                               dry_run=False, fixture=None, cdp_url="http://127.0.0.1:9222",
                               url="https://www.youtube.com/watch?v=audit", ack_terms=True,
                               attach_existing=True)
        for status in ("cdp_timeout", "blank_render", "page_not_found", "scope_violation", "session_drop"):
            with self.subTest(status=status), mock.patch.object(
                    engine, "collect_platform", return_value={"status": status, "records": 0}):
                self.assertNotEqual(0, engine.cli_collect(args))
        for status in ("planned", "collected"):
            with self.subTest(status=status), mock.patch.object(
                    engine, "collect_platform", return_value={"status": status, "records": 0}):
                self.assertEqual(0, engine.cli_collect(args))

    def test_failed_youtube_query_is_not_marked_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "queries.json"
            config.write_text(json.dumps([
                {"q": "failed", "route": "audit", "n_videos": 1, "cap_comments": 1},
            ]), encoding="utf-8")
            argv = ["collect_youtube_innertube.py", "--queries", str(config),
                    "--out", str(root / "out.jsonl"), "--state", str(root / "state.json"),
                    "--user-agent", "audit/1.0"]
            with mock.patch.object(sys, "argv", argv), \
                    mock.patch.object(youtube, "post", return_value=None), \
                    self.assertRaises(RuntimeError):
                youtube.main()
            state = json.loads((root / "state.json").read_text(encoding="utf-8"))
            self.assertEqual([], state["queries_run"])
            manifest = json.loads((root / "out.manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("failed", manifest["stop_reason"])

    def test_legacy_records_are_never_primary_sample(self):
        item = {"id": "c1", "body": "a sufficiently long legacy comment body",
                "created_utc": 1735689600, "link_id": "t3_post", "subreddit": "python"}
        self.assertFalse(arctic.normalize_comment(item, None, None)["primary_sample_eligible"])
        self.assertFalse(windows.normalize_comment(item, "python", 0, None)["primary_sample_eligible"])
        self.assertFalse(pullpush.normalize_comment(item, "audit")["primary_sample_eligible"])

    def test_cdp_true_requires_access_mode(self):
        catalog = json.loads((SCRIPTS.parent / "assets/platform-catalog.json").read_text(encoding="utf-8"))
        missing = [row["id"] for row in catalog["platforms"]
                   if row.get("cdp") and "cdp_visible_page" not in row.get("access_modes", [])]
        self.assertEqual([], missing)

    def test_platform_ids_match_catalog(self):
        hit = hn.normalize_hit({"objectID": "1", "comment_text": "a sufficiently long HN comment",
                                "created_at": "2026-01-01T00:00:00Z"}, "audit")
        self.assertEqual("hackernews", hit["source_platform"])
        review = amazon.normalize_review({"id": "r1", "parent_asin": "a1", "text": "a sufficiently long review",
                                          "timestamp": 1735689600000}, "Toys", "audit", None)
        self.assertEqual("amazon", review["source_platform"])

    def test_title_only_issue_stays_unverified(self):
        row = issues._extract_record({"title": "something is off", "text": "something is off"})
        self.assertEqual("unverified", row["confidence_basis"])
        self.assertIsNone(row["source_quote_span"])

    def test_supported_collectors_are_wired(self):
        for platform in ("youtube", "hackernews"):
            with self.subTest(platform=platform):
                self.assertEqual(platform, engine.platform_index()[platform]["adapter"])

    def test_supported_collectors_write_normalized_and_manifest(self):
        for platform in ("youtube", "hackernews"):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as tmp:
                root = study(Path(tmp), platform=platform)
                raw = {"id": f"{platform}:1", "title": "synthetic", "text": "a sufficiently long record",
                       "url": "https://example.test/1", "created_at": "2026-01-01T00:00:00Z"}
                collector_name = "_collect_youtube" if platform == "youtube" else "_collect_hn"
                with mock.patch.object(engine, collector_name, return_value=[raw]):
                    result = engine.collect_platform(root, platform, "audit", limit=1)
                self.assertEqual("collected", result["status"], result)
                self.assertTrue(Path(result["manifest"]).is_file())
                normalized = (root / "02-data/normalized.jsonl").read_text(encoding="utf-8")
                self.assertIn("sufficiently long record", normalized)

    def test_manifest_start_precedes_collection_finish(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = study(Path(tmp))
            url = "https://www.youtube.com/watch?v=audit-time"
            rows = [{"id": "r1", "text": "synthetic", "source_url": url}]
            with mock.patch.object(engine, "cdp_existing_page", return_value="ws://127.0.0.1:9222/devtools/page/audit-time"), \
                    mock.patch.object(engine, "CDPClient", return_value=cdp_client(url, rows)), \
                    mock.patch.object(engine, "_WebSocket"), \
                    mock.patch.object(engine.time, "sleep"), \
                    mock.patch.object(engine, "now", side_effect=["t0", "t1", "t2", "t3", "t4"]):
                result = engine.collect_cdp(root, "youtube", "audit-time", url, "http://127.0.0.1:9222", True,
                                            attach_existing=True, scrolls=0)
            manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual("t0", manifest["started_at"])
            self.assertEqual("t4", manifest["completed_at"])

    def test_retry_after_is_honored(self):
        import urllib.error
        headers = {"Retry-After": "7"}
        error = urllib.error.HTTPError("https://example.test", 429, "limited", headers, None)
        response = mock.MagicMock()
        response.read.return_value = b"{}"
        response.__enter__ = mock.Mock(return_value=response)
        response.__exit__ = mock.Mock(return_value=False)
        with mock.patch("urllib.request.urlopen", side_effect=[error, response]), \
                mock.patch("time.sleep") as sleep:
            payload = __import__("common").request_json("https://example.test", retries=2)
        self.assertEqual({}, payload)
        sleep.assert_called_once_with(7)


class IndependentConnectorContractTests(unittest.TestCase):
    def test_http_collectors_fail_loud_and_write_manifest(self):
        for name, module, args in (
            ("hn", hn, ["--config", "cfg.json", "--user-agent", "audit"]),
            ("arctic", arctic, ["--subreddits", "python", "--user-agent", "audit"]),
            ("pullpush", pullpush, ["--config", "cfg.json", "--user-agent", "audit"]),
        ):
            with self.subTest(platform=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                args = [str(root / "cfg.json") if item == "cfg.json" else item for item in args]
                (root / "cfg.json").write_text(json.dumps({"queries": ["audit"], "subreddits": ["python"]}), encoding="utf-8")
                out = root / "out.jsonl"
                with mock.patch.object(sys, "argv", [f"collect_{name}.py", *args, "--out", str(out)]), \
                        mock.patch.object(module.common, "request_json", side_effect=RuntimeError("boom")), \
                        self.assertRaises(SystemExit) as stopped:
                    module.main()
                self.assertNotEqual(0, stopped.exception.code)
                manifest_path = out.with_name("out.manifest.json")
                self.assertTrue(manifest_path.is_file(), manifest_path)
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                self.assertEqual("failed", manifest["stop_reason"])

    def test_arctic_append_preserves_previous_run(self):
        first = {"record_id": "reddit:1", "source_record_id": "reddit:1", "text": "first"}
        second = {"record_id": "reddit:2", "source_record_id": "reddit:2", "text": "second"}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.jsonl"
            with mock.patch.object(sys, "argv", ["collect_arctic_reddit.py", "--subreddits", "python",
                                                "--user-agent", "audit", "--out", str(out)]), \
                    mock.patch.object(arctic, "collect", side_effect=[[first], [second]]):
                arctic.main()
                arctic.main()
            self.assertEqual(2, len(out.read_text(encoding="utf-8").splitlines()))

    def test_raw_envelope_has_canonical_fields(self):
        record = youtube.build_record(
            {"id": "c1", "text": "a sufficiently long YouTube comment", "time_text": "1 day ago",
             "author": "user", "likes": 1},
            {"title": "video", "channel": "channel"}, "v1",
            {"q": "audit", "route": "route"}, "run-1")
        self.assertEqual(record["record_id"], record["source_record_id"])
        self.assertEqual(record["text_hash"], record["normalized_text_hash"])
        self.assertEqual("run-1", record["collection_run_id"])
        self.assertTrue(record["connector_revision"])

        hit = hn.normalize_hit({"objectID": "1", "comment_text": "a sufficiently long HN comment",
                                "created_at": "2026-01-01T00:00:00Z"}, "audit")
        self.assertEqual(hit["record_id"], hit["source_record_id"])
        self.assertEqual(hit["text_hash"], hit["normalized_text_hash"])
        self.assertTrue(hit["source_tier"])
        self.assertTrue(hit["collection_run_id"])

        legacy = pullpush.normalize_comment({"id": "c1", "body": "a sufficiently long Reddit comment",
                                             "created_utc": 1735689600, "link_id": "t3_post"}, "audit")
        self.assertEqual(legacy["record_id"], legacy["source_record_id"])
        self.assertEqual(legacy["text_hash"], legacy["normalized_text_hash"])
        self.assertTrue(legacy["collection_run_id"])

        review = amazon.normalize_review({"id": "r1", "parent_asin": "a1", "text": "a sufficiently long review",
                                          "timestamp": 1735689600000}, "Toys", "audit", None)
        self.assertEqual(review["record_id"], review["source_record_id"])
        self.assertTrue(review["normalized_text_hash"])
        self.assertTrue(review["collection_run_id"])

    def test_youtube_global_cap_is_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "queries.json"
            config.write_text(json.dumps([{"q": "audit", "route": "r", "n_videos": 1, "cap_comments": 10}]), encoding="utf-8")
            argv = ["collect_youtube_innertube.py", "--queries", str(config), "--out", str(root / "out.jsonl"),
                    "--state", str(root / "state.json"), "--user-agent", "audit", "--max-records", "1"]
            def comment(cid, text):
                return {"commentRenderer": {
                    "commentId": cid, "authorText": {"simpleText": "user"},
                    "contentText": {"runs": [{"text": text}]},
                    "publishedTimeText": {"simpleText": "1 day ago"}}}

            def fake_post(endpoint, body, max_wait=240.0):
                if endpoint == "search":
                    return {"contents": {"videoRenderer": {"videoId": "v1"}}}
                if "videoId" in body:
                    return {"microformat": {"playerMicroformatRenderer": {
                        "title": "video", "ownerChannelName": "channel"}}}
                return {"onResponseReceivedEndpoints": [
                    comment("c1", "first sufficiently long comment"),
                    comment("c2", "second sufficiently long comment"),
                ]}
            with mock.patch.object(sys, "argv", argv), mock.patch.object(youtube, "post", side_effect=fake_post), \
                    mock.patch.object(youtube, "comment_token", return_value="next"), \
                    mock.patch.object(youtube, "next_page_token", return_value=None), \
                    mock.patch.object(youtube.time, "sleep"):
                youtube.main()
            self.assertEqual(1, len((root / "out.jsonl").read_text(encoding="utf-8").splitlines()))

    def test_arctic_windows_uses_atomic_state_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "windows.json"
            config.write_text(json.dumps([{"sub": "python", "windows": [{"after": "2024-01-01", "before": "2024-01-02"}]}]), encoding="utf-8")
            argv = ["collect_arctic_windows.py", "--config", str(config), "--out", str(root / "out.jsonl"),
                    "--state", str(root / "state.json"), "--user-agent", "audit"]
            with mock.patch.object(sys, "argv", argv), \
                    mock.patch.object(windows, "fetch_window_page", return_value=[]), \
                    mock.patch.object(windows.common, "atomic_write_json", wraps=windows.common.atomic_write_json) as atomic:
                windows.main()
            self.assertTrue(atomic.called)

    def test_amazon_manifest_uses_reviewed_revision(self):
        revision = "0123456789abcdef0123456789abcdef01234567"
        response = mock.MagicMock()
        response.read.return_value = b"[]"
        response.__enter__ = mock.Mock(return_value=response)
        response.__exit__ = mock.Mock(return_value=False)
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(sys, "argv", ["amazon_reviews_2023_manifest.py", "--dataset-id", "dataset",
                                                "--revision", revision, "--out", str(Path(tmp) / "manifest.json")]), \
                mock.patch("urllib.request.urlopen", return_value=response) as urlopen:
            amazon_manifest.main()
        self.assertIn(revision, urlopen.call_args.args[0].full_url)


if __name__ == "__main__":
    unittest.main()
