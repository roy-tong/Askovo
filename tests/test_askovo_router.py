from __future__ import annotations

import csv
import json
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/askovo/scripts/askovo.py"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(CLI), *args], check=False, capture_output=True, text=True)


def route(need: str, *extra: str) -> dict:
    completed = run_cli("route", need, "--json", *extra)
    if completed.returncode != 0:
        raise AssertionError(completed.stderr + completed.stdout)
    return json.loads(completed.stdout)


def complete_design(target: Path, sources: list[str]) -> None:
    path = target / "study.json"
    study = json.loads(path.read_text(encoding="utf-8"))
    study["decision"].update({
        "owner": "Synthetic research owner",
        "deadline": "2027-12-31",
        "options": ["Run a synthetic pilot", "Stop the concept"],
        "minimum_evidence": ["Synthetic problem, solution and behavior chain"],
    })
    study["scope"].update({
        "target_users": ["Synthetic users"],
        "markets": ["synthetic"],
        "languages": ["en"],
        "source_time_window": {"start": "2026-01-01", "end": "2026-12-31"},
        "allowed_sources": sources,
    })
    study["hypotheses"] = [{"id": "H1", "statement": "Synthetic hypothesis", "falsified_if": "Synthetic falsifier"}]
    study["stopping_rules"] = ["Stop after the synthetic fixture"]
    study["restart_rules"] = ["Restart with a revised design"]
    path.write_text(json.dumps(study, ensure_ascii=False), encoding="utf-8")


class RouterTests(unittest.TestCase):
    def test_bare_natural_language_request_routes(self) -> None:
        completed = run_cli("手机相机夜景和续航", "--dry-run")
        self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)
        self.assertIn("手机 / 平板 / 可穿戴", completed.stdout)

    def test_bare_english_request_routes(self) -> None:
        completed = run_cli("SaaS retention churn", "--dry-run", "--json")
        self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)
        self.assertEqual("software", json.loads(completed.stdout)["domain"])

    def test_next_commands_keep_untrusted_text_in_one_argument(self) -> None:
        need = '手机"; echo SHELL_MARKER; echo "'
        data = route(need)
        argv = shlex.split(data["next_commands"][0])
        self.assertEqual(need, argv[2])
        self.assertNotIn("echo", argv[3:])
        self.assertNotIn("SHELL_MARKER", argv[3:])

    def test_detects_five_product_domains(self) -> None:
        cases = {
            "SaaS 订阅留存下降，想看看用户为什么不续费": "software",
            "家用摄像头夜间告警误报，想验证样机": "hardware",
            "新口味饮料的包装和复购": "consumer",
            "座舱语音和 ADAS 接管体验": "automotive",
            "手机相机夜景和续航": "mobile",
        }
        for need, expected in cases.items():
            with self.subTest(need=need):
                self.assertEqual(expected, route(need)["domain"])

    def test_detects_stage_and_intent(self) -> None:
        data = route("苹果手机新品的哪些平台有用户抱怨数据")
        self.assertEqual("mobile", data["domain"])
        self.assertEqual("sources", data["intent"])
        data = route("分析一下这批 SaaS 用户的评论")
        self.assertEqual("analyze", data["intent"])

    def test_unknown_domain_requests_a_choice(self) -> None:
        completed = run_cli("route", "帮我做个研究", "--json")
        self.assertEqual(2, completed.returncode)
        data = json.loads(completed.stdout)
        self.assertEqual("needs_domain", data["status"])
        self.assertEqual(5, len(data["domain_options"]))

    def test_road_test_is_safety_gated(self) -> None:
        data = route("汽车开放道路接管测试")
        self.assertEqual("automotive", data["domain"])
        self.assertEqual("review", data["safety_gate"])
        self.assertTrue(any(item["flag"] == "road_test" for item in data["risk_flags"]))

    def test_english_high_risk_terms_are_gated(self) -> None:
        data = route("research with children about food ingestion and skin contact", "--domain", "consumer")
        flags = {item["flag"] for item in data["risk_flags"]}
        self.assertEqual({"minors", "food_ingest", "skin_contact"}, flags)
        self.assertEqual("review", data["safety_gate"])

    def test_do_safety_gate_then_ack_creates_study(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "car"
            blocked = run_cli("do", "汽车开放道路接管测试", "--study", str(target))
            self.assertEqual(4, blocked.returncode, blocked.stderr)
            self.assertTrue((target / "route.md").is_file())
            allowed = run_cli("do", "汽车开放道路接管测试", "--study", str(target), "--ack-risk", "--json")
            self.assertEqual(0, allowed.returncode, allowed.stderr + allowed.stdout)
            study = json.loads((target / "study.json").read_text(encoding="utf-8"))
            self.assertTrue(study["safety_acknowledged"])
            self.assertEqual("automotive", study["product_domain"])

    def test_do_creates_workspace_plan_and_instruments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "hardware"
            completed = run_cli("do", "家用摄像头夜间告警误报，想验证样机", "--study", str(target), "--json")
            self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)
            payload = json.loads(completed.stdout)
            self.assertEqual("hardware", payload["domain"])
            self.assertTrue((target / "study.json").is_file())
            self.assertTrue((target / "01-sources/research-plan.md").is_file())
            self.assertTrue((target / "method-choice.json").is_file())
            self.assertTrue((target / "01-sources/platform-plan.json").is_file())
            platform_plan = json.loads((target / "01-sources/platform-plan.json").read_text(encoding="utf-8"))
            self.assertTrue(platform_plan["recommended"])
            self.assertTrue(list((target / "01-sources/instruments").iterdir()))
            with (target / "01-sources/source-plan.csv").open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)
            self.assertIn("cap_share", reader.fieldnames)
            self.assertEqual(8, sum(int(row["target_records"]) for row in rows))
            self.assertEqual("prototype_test", rows[0]["source_family"])
            design_check = run_cli("check", str(target), "--stage", "design")
            design = json.loads(design_check.stdout)
            source_check = next(check for check in design["checks"] if check["id"] == "source_plan")
            self.assertEqual("pass", source_check["status"], design_check.stdout)

    def test_platform_radar_prefers_relevant_sources(self) -> None:
        completed = run_cli("platforms", "家用摄像头夜间告警的用户抱怨", "--domain", "hardware", "--bulk", "--json")
        self.assertEqual(0, completed.returncode, completed.stderr)
        data = json.loads(completed.stdout)
        ids = [item["id"] for item in data["recommended"]]
        self.assertIn("reddit", ids)
        self.assertNotIn("github", ids)
        software = json.loads(
            run_cli("platforms", "SaaS 用户在 GitHub 和论坛上的抱怨", "--domain", "software", "--bulk", "--json").stdout
        )
        software_ids = [item["id"] for item in software["recommended"]]
        self.assertIn("github", software_ids)

    def test_platform_radar_boosts_named_platforms(self) -> None:
        consumer = json.loads(
            run_cli("platforms", "美妆用户在 Instagram 和小红书的评论", "--json").stdout
        )
        self.assertEqual("consumer", consumer["domain"])
        self.assertEqual("instagram", consumer["recommended"][0]["id"])
        self.assertTrue(any(item["id"] == "xiaohongshu" for item in consumer["blocked"]))

    def test_collect_requires_completed_design(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "study"
            run_cli("do", "智能硬件样机验证", "--study", str(target))
            fixture = Path(directory) / "fixture.jsonl"
            fixture.write_text(json.dumps({"id": "r1", "text": "synthetic"}) + "\n", encoding="utf-8")
            completed = run_cli(
                "collect", str(target), "--platform", "reddit", "--query", "camera", "--fixture", str(fixture),
            )
            self.assertEqual(1, completed.returncode)
            self.assertEqual("design_gate_failed", json.loads(completed.stdout)["status"])
            self.assertFalse((target / "02-data/normalized.jsonl").exists())

    def test_authorized_export_works_for_blocked_platform(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "study"
            run_cli("do", "美妆用户评论", "--study", str(target))
            complete_design(target, ["xiaohongshu"])
            fixture = Path(directory) / "export.jsonl"
            fixture.write_text(
                json.dumps({"id": "xhs-1", "text": "包装好看但漏液", "author": "a"}) + "\n",
                encoding="utf-8",
            )
            completed = run_cli(
                "collect", str(target), "--platform", "xiaohongshu",
                "--query", "包装", "--limit", "1", "--fixture", str(fixture),
            )
            self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)
            manifest = json.loads(Path(json.loads(completed.stdout)["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual("authorized_export", manifest["access_basis"])

    def test_blocked_platform_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "study"
            run_cli("do", "智能硬件样机验证", "--study", str(target))
            complete_design(target, ["kickstarter"])
            completed = run_cli("collect", str(target), "--platform", "kickstarter", "--query", "camera")
            self.assertEqual(3, completed.returncode, completed.stderr + completed.stdout)
            self.assertIn("blocked", completed.stdout)


class CollectionAndAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.target = Path(self._tmp.name) / "study"
        completed = run_cli("do", "家用摄像头夜间告警的用户抱怨", "--study", str(self.target), "--json")
        self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)
        complete_design(self.target, ["reddit", "github"])
        fixture = Path(self._tmp.name) / "fixture.jsonl"
        fixture.write_text(
            "\n".join(
                json.dumps(item)
                for item in [
                    {"id": "r1", "title": "False alarms", "text": "Night alerts fire for cats; I turned them off.", "author": "u1", "created_at": "2026-09-01T10:00:00Z"},
                    {"id": "r2", "title": "Grainy night vision", "text": "I cannot tell a person from a bush at night.", "author": "u2", "created_at": "2026-09-03T10:00:00Z"},
                    {"id": "r3", "title": "Price", "text": "Alerts work; the subscription is too expensive.", "author": "u3", "created_at": "2026-09-05T10:00:00Z"},
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        self.fixture = fixture

    def test_collect_fixture_analyze_and_deliver(self) -> None:
        collected = run_cli(
            "collect", str(self.target), "--platform", "reddit", "--query", "night alert",
            "--limit", "3", "--fixture", str(self.fixture),
        )
        self.assertEqual(0, collected.returncode, collected.stderr + collected.stdout)
        payload = json.loads(collected.stdout)
        self.assertEqual(3, payload["records"])
        self.assertTrue(Path(payload["manifest"]).is_file())
        manifest = json.loads(Path(payload["manifest"]).read_text(encoding="utf-8"))
        self.assertEqual(3, manifest["requested_records"])
        self.assertEqual(3, manifest["reached_records"])
        self.assertEqual(3, manifest["written_records"])
        raw_rows = [json.loads(line) for line in Path(payload["raw_file"]).read_text(encoding="utf-8").splitlines()]
        self.assertEqual("r1", raw_rows[0]["source_fields"]["id"])
        self.assertEqual(manifest["collection_run_id"], raw_rows[0]["collection_run_id"])
        normalized_rows = [json.loads(line) for line in (self.target / "02-data/normalized.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(manifest["collection_run_id"], normalized_rows[0]["collection_run_id"])
        self.assertEqual("authorized-export", normalized_rows[0]["connector_id"])

        analyzed = run_cli("analyze", str(self.target), "--question", "false alarm at night")
        self.assertEqual(0, analyzed.returncode, analyzed.stderr)
        analysis = json.loads((self.target / "04-findings/analysis.json").read_text(encoding="utf-8"))
        self.assertEqual(3, analysis["records"])
        self.assertEqual(3, analysis["by_platform"]["reddit"])
        self.assertTrue(analysis["question_matches"])

        delivered = run_cli("deliver", str(self.target), "--kind", "memo")
        self.assertEqual(0, delivered.returncode, delivered.stderr)
        memo = (self.target / "06-report/memo.md").read_text(encoding="utf-8")
        self.assertIn("r1", memo)
        self.assertIn("草稿", memo)

    def test_same_fixture_id_on_two_platforms_does_not_collide(self) -> None:
        fixture = Path(self._tmp.name) / "shared.jsonl"
        fixture.write_text(json.dumps({"id": "shared-id", "text": "same upstream id"}) + "\n", encoding="utf-8")
        for platform in ("reddit", "github"):
            completed = run_cli(
                "collect", str(self.target), "--platform", platform, "--query", "shared",
                "--limit", "1", "--fixture", str(fixture),
            )
            self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)
            self.assertEqual(1, json.loads(completed.stdout)["normalized_added"])
        lines = (self.target / "02-data/normalized.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(2, len(lines))
        self.assertEqual(
            {"reddit:shared-id", "github:shared-id"},
            {json.loads(line)["record_id"] for line in lines},
        )

    def test_dedup_uses_text_hash_and_preserves_id_conflicts(self) -> None:
        duplicate = Path(self._tmp.name) / "duplicate.jsonl"
        duplicate.write_text(
            json.dumps({"id": "a", "text": "identical synthetic text"}) + "\n"
            + json.dumps({"id": "b", "text": "identical synthetic text"}) + "\n",
            encoding="utf-8",
        )
        first = run_cli(
            "collect", str(self.target), "--platform", "reddit", "--query", "dedup", "--fixture", str(duplicate),
        )
        self.assertEqual(0, first.returncode, first.stdout + first.stderr)
        first_payload = json.loads(first.stdout)
        self.assertEqual(1, first_payload["normalized_added"])
        manifest = json.loads(Path(first_payload["manifest"]).read_text(encoding="utf-8"))
        self.assertEqual(1, manifest["blocked_or_dropped"]["duplicate_text"])
        self.assertEqual(2, len(Path(first_payload["raw_file"]).read_text(encoding="utf-8").splitlines()))

        conflict = Path(self._tmp.name) / "conflict.jsonl"
        conflict.write_text(json.dumps({"id": "a", "text": "different content for the same id"}) + "\n", encoding="utf-8")
        second = run_cli(
            "collect", str(self.target), "--platform", "reddit", "--query", "dedup", "--fixture", str(conflict),
        )
        second_payload = json.loads(second.stdout)
        self.assertEqual(0, second_payload["normalized_added"])
        self.assertEqual(1, second_payload["id_conflicts"])
        conflict_manifest = json.loads(Path(second_payload["manifest"]).read_text(encoding="utf-8"))
        self.assertEqual(1, conflict_manifest["blocked_or_dropped"]["id_conflicts"])
        self.assertIn("different content", Path(second_payload["raw_file"]).read_text(encoding="utf-8"))

    def test_report_handles_missing_evidence_after_collection(self) -> None:
        collected = run_cli(
            "collect", str(self.target), "--platform", "reddit", "--query", "night alert",
            "--limit", "1", "--fixture", str(self.fixture),
        )
        self.assertEqual(0, collected.returncode, collected.stderr + collected.stdout)
        self.assertFalse((self.target / "02-data/evidence.jsonl").exists())
        completed = run_cli("report", str(self.target))
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertEqual("fail", json.loads(completed.stdout)["audit_status"])

    def test_doctor_and_catalog(self) -> None:
        doctor = run_cli("doctor")
        self.assertEqual(0, doctor.returncode, doctor.stderr + doctor.stdout)
        self.assertIn("method-catalog", doctor.stdout)
        catalog = json.loads(run_cli("catalog", "--json").stdout)
        self.assertGreaterEqual(len(catalog["methods"]), 20)


if __name__ == "__main__":
    unittest.main()
