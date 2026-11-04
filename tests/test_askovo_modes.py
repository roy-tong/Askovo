from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/askovo/scripts/askovo.py"
NODES = ["scene", "user", "pain", "need", "feature", "product", "business"]


def _load_engine():
    spec = importlib.util.spec_from_file_location(
        "sure_engine_mode_tests", ROOT / "skills/askovo/scripts/sure_engine.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load sure_engine.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ENGINE = _load_engine()


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def mode_contract(need: str, *extra: str) -> dict:
    completed = run_cli("mode", need, "--json", *extra)
    if completed.returncode != 0:
        raise AssertionError(completed.stderr + completed.stdout)
    return json.loads(completed.stdout)


class ResearchModeTests(unittest.TestCase):
    def test_opportunity_request_uses_discover_from_scene(self) -> None:
        data = mode_contract("端侧 AI 摄影创业机会")
        self.assertEqual("discover", data["mode"])
        self.assertEqual("机会发现", data["mode_label"])
        self.assertEqual("scene", data["entry_node"])
        self.assertEqual("场景", data["entry_label"])
        self.assertEqual(NODES, data["node_order"])
        self.assertEqual([], data["upstream_nodes"])
        self.assertEqual("text", data["mode_source"])

    def test_validate_paid_hypothesis_enters_business(self) -> None:
        data = mode_contract("验证端侧摄影 App 是否值得做，用户是否愿意付费")
        self.assertEqual("validate", data["mode"])
        self.assertEqual("假设验证", data["mode_label"])
        self.assertEqual("business", data["entry_node"])
        self.assertEqual("商业", data["entry_label"])
        self.assertEqual("text", data["mode_source"])
        self.assertEqual(
            ["scene", "user", "pain", "need", "feature", "product"],
            data["upstream_nodes"],
        )
        self.assertEqual(
            ["business", "scene", "user", "pain", "need", "feature", "product"],
            data["node_order"],
        )

    def test_validate_request_with_discovery_stage_hint_stays_validate(self) -> None:
        data = mode_contract("验证端侧摄影 App 是否值得做")
        self.assertEqual("validate", data["mode"])
        self.assertEqual("text", data["mode_source"])
        self.assertEqual("need", data["entry_node"])

    def test_future_home_robot_opportunity_uses_discover(self) -> None:
        data = mode_contract("研究未来家庭机器人有哪些机会")
        self.assertEqual("discover", data["mode"])
        self.assertEqual("scene", data["entry_node"])
        self.assertEqual([], data["upstream_nodes"])

    def test_validate_feature_request_enters_feature(self) -> None:
        data = mode_contract("验证这个新功能方案是否成立")
        self.assertEqual("validate", data["mode"])
        self.assertEqual("text", data["mode_source"])
        self.assertEqual("feature", data["entry_node"])
        self.assertEqual(
            ["scene", "user", "pain", "need"],
            data["upstream_nodes"],
        )

    def test_conversion_decline_uses_optimize_from_product(self) -> None:
        data = mode_contract("为什么我们的注册转化下降")
        self.assertEqual("optimize", data["mode"])
        self.assertEqual("text", data["mode_source"])
        self.assertEqual("产品迭代", data["mode_label"])
        self.assertEqual("product", data["entry_node"])
        self.assertEqual(
            ["scene", "user", "pain", "need", "feature"],
            data["upstream_nodes"],
        )
        self.assertEqual(
            ["product", "business", "scene", "user", "pain", "need", "feature"],
            data["node_order"],
        )

    def test_existing_product_next_round_uses_optimize(self) -> None:
        data = mode_contract("根据仓库 Issue 和现有功能，研究 AI 产品下一轮做什么")
        self.assertEqual("optimize", data["mode"])
        self.assertEqual("product", data["entry_node"])
        self.assertEqual("text", data["mode_source"])

    def test_explicit_mode_overrides_text(self) -> None:
        data = mode_contract("为什么我们的注册转化下降", "--mode", "validate")
        self.assertEqual("validate", data["mode"])
        self.assertEqual("explicit", data["mode_source"])
        self.assertEqual("need", data["entry_node"])

    def test_explicit_stage_overrides_text(self) -> None:
        data = mode_contract("验证端侧摄影 App 是否值得做", "--stage", "postlaunch")
        self.assertEqual("optimize", data["mode"])
        self.assertEqual("stage", data["mode_source"])
        self.assertEqual("product", data["entry_node"])

    def test_explicit_stage_without_text_signal_uses_stage(self) -> None:
        data = mode_contract("看看这个产品", "--stage", "postlaunch")
        self.assertEqual("optimize", data["mode"])
        self.assertEqual("stage", data["mode_source"])
        self.assertEqual("product", data["entry_node"])

    def test_detect_research_mode_sources(self) -> None:
        explicit = ENGINE.detect_research_mode(
            "为什么我们的注册转化下降", mode="validate"
        )
        self.assertEqual("explicit", explicit["source"])
        self.assertEqual(1.0, explicit["confidence"])
        staged = ENGINE.detect_research_mode("端侧摄影 App 的假设是否成立", stage="pricing")
        self.assertEqual("validate", staged["mode"])
        self.assertEqual("stage", staged["source"])
        self.assertEqual(0.85, staged["confidence"])
        text = ENGINE.detect_research_mode("端侧 AI 摄影创业机会")
        self.assertEqual("discover", text["mode"])
        self.assertEqual("text", text["source"])
        self.assertGreater(text["confidence"], 0.3)
        default = ENGINE.detect_research_mode("帮我看看这个产品")
        self.assertEqual("discover", default["mode"])
        self.assertEqual("default", default["source"])
        self.assertEqual(0.3, default["confidence"])

    def test_text_beats_keyword_inferred_stage(self) -> None:
        data = ENGINE.detect_research_mode(
            "验证端侧摄影 App 是否值得做",
            stage="discovery",
            stage_source="keywords",
        )
        self.assertEqual("validate", data["mode"])
        self.assertEqual("text", data["source"])
        keyword_stage = ENGINE.detect_research_mode(
            "看看这个产品", stage="postlaunch", stage_source="keywords"
        )
        self.assertEqual("optimize", keyword_stage["mode"])
        self.assertEqual("stage", keyword_stage["source"])
        self.assertEqual(0.6, keyword_stage["confidence"])
        default_stage = ENGINE.detect_research_mode(
            "看看这个产品", stage="postlaunch", stage_source="default"
        )
        self.assertEqual("default", default_stage["source"])
        self.assertEqual(0.3, default_stage["confidence"])

    def test_stage_mapping_sets_mode(self) -> None:
        pricing = mode_contract("端侧摄影 App 的假设是否成立", "--stage", "pricing")
        self.assertEqual("validate", pricing["mode"])
        postlaunch = mode_contract("端侧摄影 App 的假设是否成立", "--stage", "postlaunch")
        self.assertEqual("optimize", postlaunch["mode"])

    def test_route_needs_domain_still_exposes_research_mode(self) -> None:
        completed = run_cli("route", "研究端侧 AI 摄影的创业机会", "--json")
        self.assertEqual(2, completed.returncode, completed.stderr)
        data = json.loads(completed.stdout)
        self.assertEqual("needs_domain", data["status"])
        contract = data["research_mode"]
        self.assertEqual("discover", contract["mode"])
        self.assertEqual("scene", contract["entry_node"])
        self.assertEqual(7, len(contract["node_order"]))
        self.assertEqual([], contract["upstream_nodes"])

    def test_route_routed_branch_exposes_research_mode(self) -> None:
        completed = run_cli("route", "手机端侧 AI 摄影的创业机会", "--json")
        self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)
        data = json.loads(completed.stdout)
        self.assertEqual("routed", data["status"])
        self.assertEqual("discover", data["research_mode"]["mode"])
        self.assertEqual(7, len(data["research_mode"]["node_order"]))
        self.assertEqual([], data["research_mode"]["upstream_nodes"])

    def test_route_text_signal_beats_inferred_stage(self) -> None:
        completed = run_cli("route", "手机验证端侧摄影 App 是否值得做", "--json")
        self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)
        data = json.loads(completed.stdout)
        self.assertEqual("discovery", data["stage"])
        self.assertEqual("validate", data["research_mode"]["mode"])
        self.assertEqual("text", data["research_mode"]["mode_source"])
        self.assertEqual("need", data["research_mode"]["entry_node"])

    def test_route_without_text_signal_uses_inferred_stage(self) -> None:
        completed = run_cli("route", "手机上市后表现", "--json")
        self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)
        data = json.loads(completed.stdout)
        self.assertEqual("postlaunch", data["stage"])
        self.assertEqual("optimize", data["research_mode"]["mode"])
        self.assertEqual("stage", data["research_mode"]["mode_source"])

    def test_route_research_mode_follows_stage_entry(self) -> None:
        completed = run_cli(
            "route",
            "手机端侧摄影 App 是否值得做，用户是否愿意付费",
            "--stage",
            "validation",
            "--json",
        )
        self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)
        data = json.loads(completed.stdout)
        self.assertEqual("validation", data["stage"])
        contract = data["research_mode"]
        self.assertEqual("validate", contract["mode"])
        self.assertEqual("stage", contract["mode_source"])
        self.assertEqual("business", contract["entry_node"])
        self.assertEqual(
            ["scene", "user", "pain", "need", "feature", "product"],
            contract["upstream_nodes"],
        )
        self.assertEqual(7, len(contract["node_order"]))
        self.assertEqual("business", contract["node_order"][0])

    def test_json_contract_completeness_and_boundary(self) -> None:
        data = mode_contract("验证端侧摄影 App 是否值得做，用户是否愿意付费")
        required = {
            "mode",
            "mode_label",
            "mode_source",
            "entry_node",
            "entry_label",
            "node_order",
            "upstream_nodes",
            "why_entry",
            "questions",
            "first_actions",
            "stop_conditions",
            "boundary",
        }
        self.assertTrue(required.issubset(data))
        self.assertEqual(set(NODES), set(data["node_order"]))
        self.assertEqual(7, len(data["node_order"]))
        self.assertTrue(3 <= len(data["questions"]) <= 5)
        self.assertTrue(3 <= len(data["first_actions"]) <= 5)
        self.assertTrue(2 <= len(data["stop_conditions"]) <= 4)
        self.assertTrue(all(data["questions"]))
        self.assertTrue(all(data["first_actions"]))
        self.assertTrue(all(data["stop_conditions"]))
        self.assertIn("不豁免", data["boundary"])
        self.assertIn("假设", data["boundary"])
        self.assertIn("事实", data["boundary"])

    def test_do_persists_research_mode_in_study(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            study_dir = Path(tmp) / "study"
            completed = run_cli(
                "do", "手机端侧摄影 App 是否值得做，用户愿意付费吗",
                "--domain", "mobile", "--stage", "validation",
                "--study", str(study_dir), "--json",
            )
            self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)
            study = json.loads((study_dir / "study.json").read_text(encoding="utf-8"))
            contract = study["research_mode"]
            self.assertEqual("validate", contract["mode"])
            self.assertEqual("business", contract["entry_node"])
            self.assertEqual(7, len(contract["node_order"]))
            self.assertEqual(["scene", "user", "pain", "need", "feature", "product"],
                             contract["upstream_nodes"])

    def test_default_markdown_sections(self) -> None:
        completed = run_cli("mode", "为什么我们的注册转化下降")
        self.assertEqual(0, completed.returncode, completed.stderr)
        for heading in (
            "# Askovo 研究模式",
            "## 模式与入口",
            "## 为什么从这里进",
            "## 节点顺序",
            "## 要回答的问题",
            "## 先做的动作",
            "## 停止条件",
            "## 边界",
        ):
            self.assertIn(heading, completed.stdout)
        self.assertIn("产品迭代", completed.stdout)
        self.assertIn("来源 `text`", completed.stdout)
        self.assertIn("入口只决定先回答什么", completed.stdout)


if __name__ == "__main__":
    unittest.main()
