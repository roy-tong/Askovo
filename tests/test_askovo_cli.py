from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/askovo/scripts/askovo.py"
LEGACY_VALIDATOR = ROOT / "skills/askovo/scripts/validate_study.py"
SAMPLE = ROOT / "examples/sample-study"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def configure_social_sample(target: Path) -> None:
    study_path = target / "study.json"
    study = json.loads(study_path.read_text(encoding="utf-8"))
    study["source_adapters"] = {
        "reddit": {
            "enabled": True,
            "researcher_role": "external_third_party",
            "connector_id": "reddit-praw",
            "connector_revision": "855f48e075935a052b1d71243e60e41cbc260ced",
            "connector_license": "BSD-2-Clause",
            "collection_mode": "historical_search",
            "access_basis": "official_api",
            "policy_status": "approved_for_study",
            "terms_reviewed_at": "2026-08-27",
            "data_rights_reviewed_at": "2026-08-27",
            "data_rights_basis": "Synthetic fixture; no platform data",
            "retention_rule": "Synthetic fixture only",
            "min_unique_subreddits": 1,
            "min_unique_threads": 1,
            "max_subreddit_share": 1.0,
            "max_thread_share": 1.0,
            "require_original_source": True,
            "treat_ai_summaries_as_discovery_only": True,
        },
        "x": {
            "enabled": True,
            "researcher_role": "external_third_party",
            "connector_id": "x-tweepy",
            "connector_revision": "c1978d643ecce491929084e4290b35f57e4921ad",
            "connector_license": "MIT",
            "collection_mode": "historical_search",
            "access_basis": "official_api",
            "policy_status": "approved_for_study",
            "terms_reviewed_at": "2026-08-27",
            "data_rights_reviewed_at": "2026-08-27",
            "data_rights_basis": "Synthetic fixture; no platform data",
            "retention_rule": "Synthetic fixture only",
            "min_unique_conversations": 1,
            "min_unique_days": 1,
            "max_conversation_share": 1.0,
            "max_repost_share": 1.0,
            "max_single_day_share": 1.0,
            "require_original_source": True,
            "treat_ai_summaries_as_discovery_only": True,
        },
        "youtube": {
            "enabled": True,
            "researcher_role": "external_third_party",
            "connector_id": "youtube-google-api-python-client",
            "connector_revision": "b0089df6768a806c3d837f71b5ba7eca79934e5a",
            "connector_license": "Apache-2.0",
            "collection_mode": "historical_search",
            "access_basis": "official_api",
            "policy_status": "approved_for_study",
            "terms_reviewed_at": "2026-08-27",
            "data_rights_reviewed_at": "2026-08-27",
            "data_rights_basis": "Synthetic fixture; no platform data",
            "retention_rule": "Synthetic fixture only",
            "min_unique_channels": 1,
            "min_unique_videos": 1,
            "max_channel_share": 1.0,
            "max_video_share": 1.0,
            "require_original_source": True,
            "treat_ai_summaries_as_discovery_only": True,
        },
    }
    study_path.write_text(json.dumps(study, ensure_ascii=False), encoding="utf-8")

    source_plan = target / "01-sources/source-plan.csv"
    source_plan.write_text(
        source_plan.read_text(encoding="utf-8")
        + "open_scene,reddit,synthetic reddit route,1,0.40,available,synthetic route\n"
        + "direct_solution,x,synthetic x route,1,0.40,available,synthetic route\n"
        + "post_purchase_support,youtube,synthetic youtube route,1,0.40,available,synthetic route\n",
        encoding="utf-8",
    )

    evidence_path = target / "02-data/evidence.jsonl"
    records = [json.loads(line) for line in evidence_path.read_text(encoding="utf-8").splitlines()]
    records[0].update(
        {
            "source_family": "reddit",
            "source_platform": "reddit",
            "source_channel": "r/synthetic",
            "source_url": "https://example.invalid/r/synthetic/comments/thread/post",
            "thread_id": "thread-1",
            "reddit_item_id": "post-1",
            "source_content_type": "post",
            "source_query": "synthetic problem",
            "source_sort": "new",
            "source_time_filter": "year",
            "created_at": "2026-08-01T00:00:00Z",
            "collected_at": "2026-08-27T00:00:00Z",
            "content_status": "present",
            "collection_run_id": "reddit-praw-synthetic-01",
            "connector_id": "reddit-praw",
            "connector_revision": "855f48e075935a052b1d71243e60e41cbc260ced",
        }
    )
    records[2].update(
        {
            "source_family": "x",
            "source_platform": "x",
            "source_url": "https://example.invalid/x/post-1",
            "x_post_id": "x-post-1",
            "conversation_id": "x-conversation-1",
            "x_post_type": "original",
            "source_query": "synthetic acceptance",
            "source_search_mode": "recent",
            "created_at": "2026-08-02T00:00:00Z",
            "collected_at": "2026-08-27T00:00:00Z",
            "last_verified_at": "2026-08-27T00:00:00Z",
            "content_status": "present",
            "collection_run_id": "x-tweepy-synthetic-01",
            "connector_id": "x-tweepy",
            "connector_revision": "c1978d643ecce491929084e4290b35f57e4921ad",
        }
    )
    records[5].update(
        {
            "source_family": "youtube",
            "source_platform": "youtube",
            "source_channel": "UC_SYNTHETIC",
            "source_url": "https://example.invalid/youtube/video-1?lc=comment-1",
            "youtube_video_id": "video-1",
            "youtube_item_id": "comment-1",
            "youtube_content_type": "top_level_comment",
            "comment_thread_id": "comment-thread-1",
            "source_query": "synthetic retained use",
            "source_order": "time",
            "created_at": "2026-08-03T00:00:00Z",
            "collected_at": "2026-08-27T00:00:00Z",
            "last_verified_at": "2026-08-27T00:00:00Z",
            "refresh_due_at": "2099-01-01T00:00:00Z",
            "content_status": "present",
            "collection_run_id": "youtube-api-synthetic-01",
            "connector_id": "youtube-google-api-python-client",
            "connector_revision": "b0089df6768a806c3d837f71b5ba7eca79934e5a",
        }
    )
    evidence_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )


def configure_amazon_historical_sample(target: Path) -> None:
    study_path = target / "study.json"
    study = json.loads(study_path.read_text(encoding="utf-8"))
    study["source_adapters"] = {
        "amazon": {
            "enabled": True,
            "researcher_role": "external_third_party",
            "connector_id": "amazon-reviews-2023",
            "connector_revision": "b18fdf54bd46013d60799684f7a4eb80d8501d1a",
            "connector_license": "MIT",
            "collection_mode": "historical_search",
            "access_basis": "historical_dataset",
            "policy_status": "historical_data_only",
            "terms_reviewed_at": "2026-08-27",
            "data_rights_reviewed_at": "2026-08-27",
            "data_rights_basis": "Synthetic fixture; no Amazon content",
            "retention_rule": "Synthetic fixture only",
            "min_unique_products": 1,
            "min_unique_stores": 1,
            "min_unique_brands": 1,
            "max_product_share": 1.0,
            "max_store_share": 1.0,
            "max_brand_share": 1.0,
            "max_single_month_share": 1.0,
            "require_variant_id": True,
            "require_original_source": True,
            "treat_ai_summaries_as_discovery_only": True,
        }
    }
    study_path.write_text(json.dumps(study, ensure_ascii=False), encoding="utf-8")

    source_plan = target / "01-sources/source-plan.csv"
    source_plan.write_text(
        source_plan.read_text(encoding="utf-8")
        + "open_scene,amazon,synthetic historical review route,1,1.0,available,synthetic route\n",
        encoding="utf-8",
    )
    evidence_path = target / "02-data/evidence.jsonl"
    records = [json.loads(line) for line in evidence_path.read_text(encoding="utf-8").splitlines()]
    records[0].update(
        {
            "source_family": "amazon",
            "collection_run_id": "amazon-historical-synthetic-01",
            "connector_id": "amazon-reviews-2023",
            "connector_revision": "b18fdf54bd46013d60799684f7a4eb80d8501d1a",
            "source_platform": "amazon",
            "source_url": "https://example.invalid/amazon/historical-review",
            "commerce_product_id": "PARENT-ASIN-SYNTHETIC",
            "commerce_variant_id": "ASIN-SYNTHETIC",
            "commerce_store_id": "STORE-SYNTHETIC",
            "commerce_brand": "Synthetic brand",
            "commerce_record_id": "REVIEW-SYNTHETIC-01",
            "commerce_content_type": "review",
            "commerce_transaction_status": "verified_purchase",
            "source_completeness": "full_text",
            "source_query": "synthetic historical fixture",
            "created_at": "2023-08-01T00:00:00Z",
            "collected_at": "2026-08-27T00:00:00Z",
            "content_status": "present",
        }
    )
    evidence_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )


class AskvoCliTests(unittest.TestCase):
    def test_sample_study_passes_full_check_and_writes_reports(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "sample"
            shutil.copytree(SAMPLE, target)
            completed = run_cli("check", str(target), "--stage", "full", "--write-report")
            payload = json.loads(completed.stdout)
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            self.assertEqual("pass", payload["status"])
            self.assertEqual(7, payload["metrics"]["evidence_records"])
            self.assertTrue((target / "05-audit/latest.json").is_file())
            self.assertTrue((target / "05-audit/latest.md").is_file())

    def test_init_creates_standard_tree_without_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "new-study"
            created = run_cli(
                "init",
                str(target),
                "--study-id",
                "repair-guidance",
                "--title",
                "Repair guidance",
                "--decision",
                "Whether to prototype hands-free guidance",
                "--platform",
                "reddit",
                "--platform",
                "youtube",
            )
            self.assertEqual(0, created.returncode, created.stdout + created.stderr)
            expected = [
                "study.json",
                "01-sources/source-plan.csv",
                "02-data/evidence.jsonl",
                "03-codebook/codebook.csv",
                "04-findings/demand-judgments.json",
                "04-findings/product-reasoning.json",
                "01-sources/reddit-routes.csv",
                "01-sources/youtube-routes.csv",
                "01-sources/collection-manifest-template.json",
                "02-data/raw/raw-connector-envelope-template.jsonl",
            ]
            self.assertTrue(all((target / path).exists() for path in expected))
            initialized_study = json.loads((target / "study.json").read_text(encoding="utf-8"))
            self.assertEqual("2.0", initialized_study["product_reasoning_version"])
            self.assertEqual(
                ["product_manager", "user_researcher", "user_operations", "market_researcher", "market_analyst", "requirements_analyst", "business_analyst"],
                initialized_study["delivery"]["audiences"],
            )
            self.assertTrue(initialized_study["source_adapters"]["reddit"]["enabled"])
            self.assertTrue(initialized_study["source_adapters"]["youtube"]["enabled"])
            design_check = run_cli("check", str(target), "--stage", "design")
            self.assertEqual(1, design_check.returncode)
            self.assertIn("row 2 has empty source_family", design_check.stdout)
            second = run_cli(
                "init",
                str(target),
                "--study-id",
                "other",
                "--title",
                "Other",
                "--decision",
                "Other decision",
            )
            self.assertEqual(2, second.returncode)
            self.assertIn("refusing to overwrite", second.stderr)

    def test_validated_judgment_without_commercial_evidence_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "sample"
            shutil.copytree(SAMPLE, target)
            path = target / "04-findings/demand-judgments.json"
            judgments = json.loads(path.read_text(encoding="utf-8"))
            judgments[0]["commercial_evidence_ids"] = []
            path.write_text(json.dumps(judgments), encoding="utf-8")
            completed = run_cli("check", str(target), "--stage", "full")
            self.assertEqual(1, completed.returncode)
            self.assertIn("lacks commercial evidence", completed.stdout)

    def test_duplicate_record_id_fails_evidence_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "sample"
            shutil.copytree(SAMPLE, target)
            path = target / "02-data/evidence.jsonl"
            first = path.read_text(encoding="utf-8").splitlines()[0]
            path.write_text(path.read_text(encoding="utf-8") + first + "\n", encoding="utf-8")
            completed = run_cli("check", str(target), "--stage", "evidence")
            self.assertEqual(1, completed.returncode)
            self.assertIn("duplicate record_id", completed.stdout)

    def test_legacy_validator_still_checks_full_study(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(LEGACY_VALIDATOR), str(SAMPLE)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertEqual("pass", json.loads(completed.stdout)["status"])

    def test_reddit_x_and_youtube_adapters_pass_with_required_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "sample"
            shutil.copytree(SAMPLE, target)
            configure_social_sample(target)
            completed = run_cli("check", str(target), "--stage", "full")
            payload = json.loads(completed.stdout)
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            self.assertEqual("pass", payload["status"])
            self.assertEqual(1, payload["metrics"]["reddit"]["unique_threads"])
            self.assertEqual(1, payload["metrics"]["x"]["unique_conversations"])
            self.assertEqual(1, payload["metrics"]["youtube"]["unique_videos"])

    def test_x_repost_cannot_be_claimed_above_e0(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "sample"
            shutil.copytree(SAMPLE, target)
            configure_social_sample(target)
            path = target / "02-data/evidence.jsonl"
            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            records[2]["x_post_type"] = "repost"
            path.write_text(
                "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8"
            )
            completed = run_cli("check", str(target), "--stage", "evidence")
            self.assertEqual(1, completed.returncode)
            self.assertIn("is a repost and may only be coded E0", completed.stdout)

    def test_expired_youtube_record_fails_refresh_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "sample"
            shutil.copytree(SAMPLE, target)
            configure_social_sample(target)
            path = target / "02-data/evidence.jsonl"
            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            records[5]["refresh_due_at"] = "2020-01-01T00:00:00Z"
            path.write_text(
                "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8"
            )
            completed = run_cli("check", str(target), "--stage", "evidence")
            self.assertEqual(1, completed.returncode)
            self.assertIn("refresh_due_at has passed", completed.stdout)

    def test_connector_registry_hides_blocked_projects_by_default(self) -> None:
        supported = run_cli("connectors", "--platform", "x")
        self.assertEqual(0, supported.returncode, supported.stdout + supported.stderr)
        supported_payload = json.loads(supported.stdout)
        self.assertEqual(["x-tweepy"], [item["id"] for item in supported_payload["connectors"]])

        reviewed = run_cli("connectors", "--platform", "x", "--include-blocked")
        self.assertEqual(0, reviewed.returncode, reviewed.stdout + reviewed.stderr)
        reviewed_payload = json.loads(reviewed.stdout)
        self.assertEqual(
            {"x-tweepy", "x-snscrape", "x-twikit"},
            {item["id"] for item in reviewed_payload["connectors"]},
        )

    def test_blocked_open_source_connector_fails_design_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "sample"
            shutil.copytree(SAMPLE, target)
            configure_social_sample(target)
            study_path = target / "study.json"
            study = json.loads(study_path.read_text(encoding="utf-8"))
            study["source_adapters"]["x"].update(
                {
                    "connector_id": "x-twikit",
                    "connector_revision": "c3b7220866f8582009fe2d1155b6fe92192a2711",
                    "connector_license": "MIT",
                }
            )
            study_path.write_text(json.dumps(study), encoding="utf-8")
            completed = run_cli("check", str(target), "--stage", "design")
            self.assertEqual(1, completed.returncode)
            self.assertIn("connector x-twikit is blocked", completed.stdout)

    def test_historical_amazon_connector_passes_with_pinned_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "sample"
            shutil.copytree(SAMPLE, target)
            configure_amazon_historical_sample(target)
            completed = run_cli("check", str(target), "--stage", "full")
            payload = json.loads(completed.stdout)
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            self.assertEqual("pass", payload["status"])
            self.assertEqual(1, payload["metrics"]["amazon"]["unique_products"])

    def test_jd_registry_exposes_only_blocked_candidate(self) -> None:
        supported = run_cli("connectors", "--platform", "jd")
        self.assertEqual(0, supported.returncode, supported.stdout + supported.stderr)
        self.assertEqual(0, json.loads(supported.stdout)["count"])

        reviewed = run_cli("connectors", "--platform", "jd", "--include-blocked")
        self.assertEqual(0, reviewed.returncode, reviewed.stdout + reviewed.stderr)
        self.assertEqual(
            ["jd-comment-spider"],
            [item["id"] for item in json.loads(reviewed.stdout)["connectors"]],
        )


class PlanSignalsReportTests(unittest.TestCase):
    def test_plan_overseas_study_allocates_quotas_and_tasks(self) -> None:
        import csv as csv_module

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "overseas"
            completed = run_cli(
                "plan",
                str(target),
                "--goal",
                "AI glasses complaints overseas",
                "--region",
                "overseas",
                "--sample-size",
                "100000",
                "--platform-types",
                "forum,social,video",
                "--market",
                "us",
            )
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(["reddit", "x", "youtube"], payload["feasible_platforms"])
            self.assertEqual(100000, sum(payload["platform_quotas"].values()))

            study = json.loads((target / "study.json").read_text(encoding="utf-8"))
            self.assertEqual(1000, study["quality_gates"]["min_evidence_records"])
            self.assertEqual(["overseas", "us"], study["scope"]["markets"])
            self.assertEqual(["reddit", "x", "youtube"], study["scope"]["allowed_sources"])
            self.assertEqual(100000, study["plan"]["sample_target"])
            self.assertTrue(study["source_adapters"]["reddit"]["enabled"])
            self.assertTrue(study["source_adapters"]["x"]["enabled"])
            self.assertTrue(study["source_adapters"]["youtube"]["enabled"])

            with (target / "01-sources/reddit-routes.csv").open(encoding="utf-8-sig", newline="") as handle:
                reddit_rows = list(csv_module.DictReader(handle))
            self.assertEqual(
                payload["platform_quotas"]["reddit"],
                sum(int(row["target_records"]) for row in reddit_rows),
            )
            with (target / "01-sources/source-plan.csv").open(encoding="utf-8-sig", newline="") as handle:
                plan_rows = list(csv_module.DictReader(handle))
            self.assertEqual(15, len(plan_rows))
            self.assertEqual(
                payload["platform_quotas"]["x"],
                sum(
                    int(row["target_records"])
                    for row in plan_rows
                    if row["source_family"] == "x"
                ),
            )

            feasibility = json.loads(
                (target / "01-sources/feasibility.json").read_text(encoding="utf-8")
            )
            self.assertEqual(3, len([p for p in feasibility["platforms"] if p["status"] == "enabled"]))
            tasks = (target / "01-sources/tasks.md").read_text(encoding="utf-8")
            self.assertIn("reddit-praw", tasks)
            self.assertIn("2026-09-30", tasks)

            design_check = run_cli("check", str(target), "--stage", "design")
            self.assertEqual(1, design_check.returncode)

    def test_plan_rejects_impossible_quota_without_creating_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "too-small"
            completed = run_cli(
                "plan", str(target), "--goal", "AI glasses complaints", "--region", "overseas",
                "--sample-size", "1", "--platform-types", "forum,social,video",
            )
            self.assertEqual(2, completed.returncode)
            self.assertFalse(target.exists())

    def test_plan_validates_time_window_before_creating_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "time-window"
            base_args = (
                "plan", str(target), "--goal", "AI glasses complaints", "--region", "overseas",
                "--sample-size", "1000", "--platform-types", "social",
            )
            invalid = run_cli(*base_args, "--time-window", "not-a-window")
            self.assertEqual(2, invalid.returncode)
            self.assertFalse(target.exists())
            valid = run_cli(*base_args, "--time-window", "2025-01-01:2026-08-31")
            self.assertEqual(0, valid.returncode, valid.stdout + valid.stderr)

    def test_plan_cn_ecommerce_fails_visibly_without_workaround(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "cn-ecommerce"
            completed = run_cli(
                "plan",
                str(target),
                "--goal",
                "国产 AI 眼镜电商评论",
                "--region",
                "cn",
                "--sample-size",
                "50000",
                "--platform-types",
                "ecommerce",
            )
            self.assertEqual(3, completed.returncode)
            payload = json.loads(completed.stdout)
            self.assertEqual([], payload["feasible_platforms"])
            statuses = {
                item["platform"]: item["status"] for item in payload["unavailable_platforms"]
            }
            self.assertEqual({"jd": "blocked", "taobao": "blocked"}, statuses)
            study = json.loads((target / "study.json").read_text(encoding="utf-8"))
            self.assertEqual([], study["plan"]["feasible_platforms"])
            self.assertEqual(2, len(study["plan"]["unavailable_platforms"]))
            tasks = (target / "01-sources/tasks.md").read_text(encoding="utf-8")
            self.assertIn("Unavailable routes", tasks)

    def test_plan_rejects_unknown_platform_type(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            completed = run_cli(
                "plan",
                str(Path(directory) / "bad"),
                "--goal",
                "x",
                "--region",
                "overseas",
                "--sample-size",
                "1000",
                "--platform-types",
                "telepathy",
            )
            self.assertEqual(2, completed.returncode)
            self.assertIn("unknown platform types", completed.stderr)

    def test_signals_computes_deterministic_corpus_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "sample"
            shutil.copytree(SAMPLE, target)
            completed = run_cli("signals", str(target))
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(7, payload["record_count"])
            self.assertEqual(2, payload["chain_readiness"]["problem_E1_E2"])
            self.assertEqual("pass", payload["gates"]["min_evidence_records"]["status"])
            self.assertTrue((target / "04-findings/signals.json").is_file())

    def test_report_assembles_passing_sample_study(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "sample"
            shutil.copytree(SAMPLE, target)
            completed = run_cli("report", str(target))
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual("pass", payload["audit_status"])
            self.assertEqual(1, payload["judgments"])
            text = (target / "06-report/research-status.md").read_text(encoding="utf-8")
            self.assertIn("调研报告", text)
            self.assertIn("## 2. 产品与商业推理主链", text)
            self.assertIn("## 4. 数据质量与关键信号", text)
            self.assertIn("## 5. 需求判断", text)
            self.assertIn("禁止推断", text)

    def test_report_recomputes_stale_passing_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "sample"
            shutil.copytree(SAMPLE, target)
            checked = run_cli("check", str(target), "--stage", "full", "--write-report")
            self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)
            (target / "02-data/evidence.jsonl").write_text("", encoding="utf-8")
            completed = run_cli("report", str(target))
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            self.assertEqual("fail", json.loads(completed.stdout)["audit_status"])
            self.assertIn("未通过", (target / "06-report/research-status.md").read_text(encoding="utf-8"))

    def test_report_warns_when_full_check_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "fresh"
            planned = run_cli(
                "plan",
                str(target),
                "--goal",
                "AI glasses complaints",
                "--region",
                "overseas",
                "--sample-size",
                "2000",
                "--platform-types",
                "social",
            )
            self.assertEqual(0, planned.returncode, planned.stdout + planned.stderr)
            completed = run_cli("report", str(target))
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual("fail", payload["audit_status"])
            text = (target / "06-report/research-status.md").read_text(encoding="utf-8")
            self.assertIn("未通过", text)
            self.assertIn("研究状态输出", text)


class UnnamedExperienceTests(unittest.TestCase):
    LEXICON_FIXTURE = (
        "term,term_type,grounding_path,definition,source_anchor,expected_signal,status,notes\n"
        "rumbly,proto_word,edge_language,low-frequency body-felt vibration word,thread-anchor,E1 problem language,candidate,\n"
        "waves,proto_word,edge_language,slow rhythmic sensation metaphor,thread-anchor,E1 problem language,candidate,\n"
        "tingling,proto_word,edge_language,light prickling sensation word,thread-anchor,E1 problem language,candidate,\n"
        "shower-stream,behavior,substitute_behavior,DIY water stream for body sensation,diy-post,E2 substitute friction,candidate,\n"
        "massage-gun,behavior,substitute_behavior,repurposed device for vibration,diy-post,E2 substitute friction,candidate,\n"
        "vibration-frequency,dimension,psychophysical,stimulus frequency axis,paper-anchor,hypothesis frame,candidate,\n"
    )

    def test_plan_unnamed_mode_gates_the_lexicon_at_design(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "unnamed"
            planned = run_cli(
                "plan",
                str(target),
                "--goal",
                "unnamed body sensation",
                "--region",
                "overseas",
                "--sample-size",
                "3000",
                "--platform-types",
                "forum",
                "--mode",
                "unnamed-experience",
            )
            self.assertEqual(0, planned.returncode, planned.stdout + planned.stderr)
            study = json.loads((target / "study.json").read_text(encoding="utf-8"))
            self.assertEqual("unnamed_experience", study["plan"]["mode"])
            self.assertEqual(12000, study["plan"]["raw_target_estimate"])
            self.assertTrue((target / "01-sources/lexicon.csv").is_file())
            self.assertTrue((target / "01-sources/experience-space.csv").is_file())
            self.assertIn("Phase 0 grounding", (target / "01-sources/tasks.md").read_text(encoding="utf-8"))

            empty = run_cli("check", str(target), "--stage", "design")
            self.assertEqual(1, empty.returncode)
            empty_payload = json.loads(empty.stdout)
            lexicon_check = next(
                item for item in empty_payload["checks"] if item["id"] == "lexicon_grounding"
            )
            self.assertEqual("fail", lexicon_check["status"])
            self.assertIn("below the required 5", lexicon_check["detail"])

            (target / "01-sources/lexicon.csv").write_text(self.LEXICON_FIXTURE, encoding="utf-8")
            (target / "01-sources/experience-space.csv").write_text(
                "dimension,range_low,range_high,unit,covered_by_existing,coverage_note,evidence_refs\n"
                "frequency,10,300,hz,no,no product coverage in corpus,\n",
                encoding="utf-8",
            )
            filled = run_cli("check", str(target), "--stage", "design")
            filled_payload = json.loads(filled.stdout)
            lexicon_check = next(
                item for item in filled_payload["checks"] if item["id"] == "lexicon_grounding"
            )
            self.assertEqual("pass", lexicon_check["status"])

    def test_lexicon_reports_yield_fossils_and_sufficiency(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "sample"
            shutil.copytree(SAMPLE, target)
            (target / "01-sources/lexicon.csv").write_text(self.LEXICON_FIXTURE, encoding="utf-8")
            evidence_path = target / "02-data/evidence.jsonl"
            records = [json.loads(line) for line in evidence_path.read_text(encoding="utf-8").splitlines()]
            records[0]["lexicon_terms"] = ["rumbly"]
            records[0]["grounding_path"] = "edge_language"
            records[2]["lexicon_terms"] = ["rumbly", "waves"]
            records[2]["grounding_path"] = "edge_language"
            records[5]["lexicon_terms"] = ["tingling"]
            records[5]["grounding_path"] = "substitute_behavior"
            evidence_path.write_text(
                "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
                encoding="utf-8",
            )

            insufficient = run_cli("lexicon", str(target), "--min-per-term", "2")
            self.assertEqual(1, insufficient.returncode)
            payload = json.loads(insufficient.stdout)
            self.assertEqual("insufficient", payload["sufficiency"]["status"])
            self.assertIn("waves", payload["sufficiency"]["insufficient_terms"])
            self.assertEqual(1, payload["demand_fossil_records"])
            self.assertEqual(2, payload["terms"]["rumbly"]["records"])
            self.assertIn("shower-stream", payload["zero_yield_terms"])
            self.assertTrue((target / "04-findings/lexicon-yield.json").is_file())

            relaxed = run_cli(
                "lexicon",
                str(target),
                "--min-per-term",
                "1",
            )
            self.assertEqual(1, relaxed.returncode)
            self.assertIn(
                "shower-stream", json.loads(relaxed.stdout)["sufficiency"]["insufficient_terms"]
            )

            (target / "01-sources/lexicon.csv").write_text(
                "term,term_type,grounding_path,definition,source_anchor,expected_signal,status,notes\n"
                "rumbly,proto_word,edge_language,low-frequency word,thread-anchor,E1,candidate,\n"
                "waves,proto_word,edge_language,slow rhythmic metaphor,thread-anchor,E1,candidate,\n",
                encoding="utf-8",
            )
            sufficient = run_cli("lexicon", str(target), "--min-per-term", "1")
            self.assertEqual(0, sufficient.returncode)
            self.assertEqual("sufficient", json.loads(sufficient.stdout)["sufficiency"]["status"])

    def test_lexicon_without_lexicon_file_is_a_usage_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "sample"
            shutil.copytree(SAMPLE, target)
            completed = run_cli("lexicon", str(target))
            self.assertEqual(2, completed.returncode)
            self.assertIn("unnamed-experience", completed.stderr)

    def test_report_includes_grounding_section_when_yield_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "sample"
            shutil.copytree(SAMPLE, target)
            (target / "01-sources/lexicon.csv").write_text(self.LEXICON_FIXTURE, encoding="utf-8")
            run_cli("lexicon", str(target))
            completed = run_cli("report", str(target))
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            text = (target / "06-report/research-status.md").read_text(encoding="utf-8")
            self.assertIn("命名前研究信号", text)
            self.assertIn("需求化石", text)


class AuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.target = Path(self._tmp.name) / "sample"
        shutil.copytree(SAMPLE, self.target)

    def test_version_reads_repo_version_file(self) -> None:
        expected = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        completed = run_cli("--version")
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(f"Askovo {expected}", completed.stdout.strip())

    def test_plan_records_current_method_version(self) -> None:
        target = Path(self._tmp.name) / "planned"
        completed = run_cli(
            "plan",
            str(target),
            "--goal",
            "AI glasses dissent",
            "--region",
            "overseas",
            "--sample-size",
            "1000",
            "--platform-types",
            "forum,social,video",
        )
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        study = json.loads((target / "study.json").read_text(encoding="utf-8"))
        expected = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertEqual(expected, study["method_version"])

    def test_demo_runs_bundled_sample_in_temp_dir(self) -> None:
        completed = run_cli("demo")
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("Askovo 审计", completed.stdout)
        self.assertIn("pass", completed.stdout)
        self.assertFalse((ROOT / "examples/sample-study/05-audit/audit.json").exists())

    def test_audit_passes_sample_and_writes_artifacts(self) -> None:
        completed = run_cli("audit", str(self.target))
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        payload = json.loads((self.target / "05-audit/audit.json").read_text(encoding="utf-8"))
        self.assertEqual("pass", payload["status"])
        self.assertEqual("supported", payload["claims"][0]["verdict"])
        self.assertTrue((self.target / "05-audit/audit.md").is_file())
        self.assertIn("可支持", (self.target / "05-audit/audit.md").read_text(encoding="utf-8"))

    def test_audit_flags_a_validated_claim_that_exceeds_evidence(self) -> None:
        judgments_path = self.target / "04-findings/demand-judgments.json"
        judgments = json.loads(judgments_path.read_text(encoding="utf-8"))
        judgments[0]["commercial_evidence_ids"] = []
        judgments_path.write_text(json.dumps(judgments, ensure_ascii=False, indent=2), encoding="utf-8")
        completed = run_cli("audit", str(self.target))
        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        payload = json.loads((self.target / "05-audit/audit.json").read_text(encoding="utf-8"))
        self.assertEqual("exceeds_evidence", payload["claims"][0]["verdict"])
        self.assertTrue(any("commercial" in reason for reason in payload["claims"][0]["reasons"]))

    def test_audit_rejects_evidence_from_another_decision_context(self) -> None:
        evidence_path = self.target / "02-data/evidence.jsonl"
        records = [json.loads(line) for line in evidence_path.read_text(encoding="utf-8").splitlines()]
        for record in records[:4]:
            record["context_key"] = "unrelated-product-context"
        evidence_path.write_text(
            "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
            encoding="utf-8",
        )
        completed = run_cli("audit", str(self.target))
        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        payload = json.loads((self.target / "05-audit/audit.json").read_text(encoding="utf-8"))
        self.assertEqual("exceeds_evidence", payload["claims"][0]["verdict"])
        self.assertTrue(any("context_key" in reason for reason in payload["claims"][0]["reasons"]))

    def test_audit_unknown_claim_filter_is_a_usage_error(self) -> None:
        completed = run_cli("audit", str(self.target), "--claim", "no-such-claim")
        self.assertEqual(2, completed.returncode)
        self.assertIn("no claim matched", completed.stderr)

    def test_study_template_has_no_hardcoded_version(self) -> None:
        template = (
            ROOT
            / "skills/askovo/assets/study-template/study.json"
        ).read_text(encoding="utf-8")
        self.assertIn('"{{method_version}}"', template)
        self.assertNotIn("askovo 1.6", template)


if __name__ == "__main__":
    unittest.main()
