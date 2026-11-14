from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/askovo/scripts"
CLI = SCRIPTS / "askovo.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


roles = load_module("role_catalog_under_test", SCRIPTS / "role_catalog.py")
delivery = load_module("delivery_projection_under_test", SCRIPTS / "delivery_projection.py")


def run_cli(*arguments: str):
    return subprocess.run(
        [sys.executable, str(CLI), *arguments],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )


def make_study(study: Path, chain_count: int = 1) -> dict:
    study.mkdir(parents=True)
    chains = []
    for index in range(1, chain_count + 1):
        chains.append({
            "id": f"PR{index:02d}",
            "title": f"candidate-{index}",
            "nodes": {node: {"statement": f"statement-{index}-{node}", "rationale": "test rationale", "evidence_ids": [], "assumptions": []} for node in roles.CHAIN_NODES},
        })
    reasoning = {"chains": chains}
    (study / "04-findings").mkdir()
    (study / "04-findings/product-reasoning.json").write_text(json.dumps(reasoning), encoding="utf-8")
    (study / "04-findings/demand-judgments.json").write_text("[]\n", encoding="utf-8")
    (study / "02-data").mkdir()
    (study / "02-data/evidence.jsonl").write_text("", encoding="utf-8")
    (study / "study.json").write_text(json.dumps({
        "study_id": "role-test",
        "title": "AI Agent 任务研究",
        "product_domain": "software",
        "lifecycle_stage": "concept",
        "industry_context": "ai_native",
        "decision": {"question": "是否进入受限原型测试"},
    }, ensure_ascii=False), encoding="utf-8")
    return reasoning


class RoleCatalogTests(unittest.TestCase):
    def test_complete_80_role_10_stage_10_industry_contract(self) -> None:
        self.assertEqual([], roles.validate_catalog())
        self.assertEqual(80, len(roles.roles()))
        self.assertEqual(10, len(roles.lifecycles()))
        self.assertEqual(10, len(roles.industries()))
        self.assertEqual({f"R{number:02d}" for number in range(1, 81)}, set(roles.role_index()))
        expected_names = (
            "市场研究", "产业与行业研究", "类目与品类研究", "竞品与竞争情报", "趋势与未来研究", "技术与专利情报", "政策与法规研究", "商业与经济可行性",
            "用户体验研究", "消费者洞察", "定性研究", "定量研究", "人种志与场景研究", "用户行为研究", "需求发现与分析", "用户细分与画像", "用户旅程与任务分析", "客户之声与反馈研究", "企业客户需求研究", "购买决策与价格研究", "购物者与零售研究", "人因与人体工学研究", "感官与感性研究", "无障碍与特殊人群研究",
            "产品战略与产品组合", "通用产品管理", "消费软件产品管理", "企业软件产品管理", "AI 产品管理", "硬件产品管理", "消费品产品管理", "平台与生态产品管理", "技术产品管理", "增长与商业化产品管理", "需求与业务系统分析",
            "产品创新管理", "设计战略", "产品概念设计", "服务设计", "客户体验设计", "共创与参与式设计", "商业模式设计", "未来与思辨设计",
            "用户体验设计", "信息架构设计", "交互设计", "用户界面设计", "视觉与品牌体验设计", "内容与信息体验设计", "UX 文案与微交互文案", "设计系统与组件设计", "对话与 AI 交互设计", "空间、动态与沉浸式交互", "无障碍与包容性设计", "原型与体验工程",
            "工业设计", "色彩材料工艺设计", "机械与结构设计", "电子与硬件设计", "嵌入式与固件设计", "系统架构与系统工程", "实体人机交互设计", "专业物理性能设计", "材料与制造工艺设计", "包装结构与产品防护设计",
            "配方与产品研发", "食品饮料产品开发", "感官体验与产品性能设计", "香精、香氛与风味设计", "服装、面料与版型设计", "商品包装与陈列体验设计",
            "概念与商业验证", "可用性与体验评测", "真实场景与用户试用", "工程与产品可靠性验证", "产品安全、质量与合规验证", "产品开发与项目管理", "产品生命周期与品类经营", "研究运营与研究知识管理", "设计运营与设计资产管理",
        )
        self.assertEqual(list(expected_names), [role["name_zh"] for role in roles.roles()])
        for role in roles.roles():
            self.assertGreaterEqual(len(role["responsibilities"]), 3, role["id"])
            self.assertGreaterEqual(len(role["kpis"]), 3, role["id"])
            self.assertGreaterEqual(len(role["sop"]), 5, role["id"])
            self.assertGreaterEqual(len(role["deliverables"]), 2, role["id"])
            self.assertTrue(set(role["chain_nodes"]).issubset(set(roles.CHAIN_NODES)))
            for kpi in role["kpis"]:
                self.assertTrue(kpi["formula"].strip())
                self.assertTrue(kpi["guardrail"].strip())

    def test_role_lookup_search_and_industry_overlay(self) -> None:
        self.assertEqual("R09", roles.normalize_role("UX Researcher"))
        role = roles.resolve_role("09", "medical_health")
        self.assertEqual("medical_health", role["industry_context"]["id"])
        gates = " ".join(role["resolved_gates"])
        self.assertIn("预期用户", gates)
        self.assertIn("伦理", " ".join(role["resolved_human_boundaries"]))
        results = roles.list_roles(query="服务蓝图")
        self.assertIn("R39", {item["id"] for item in results})
        self.assertEqual(8, len(roles.list_roles(lifecycle="L01")))

    def test_recommendation_uses_industry_and_stage_without_inventing_findings(self) -> None:
        plan = roles.recommend_roles("设计 Agent 摄影应用的概念、工具确认与失败恢复", "ai_native", "concept")
        self.assertEqual("R29", plan["lead_role_id"])
        self.assertEqual("design", plan["task"]["id"])
        ids = {item["id"] for item in plan["assignments"]}
        self.assertIn("R52", ids)
        self.assertIn("R38", ids)
        self.assertLessEqual(plan["scope"]["selected_count"], 5)
        self.assertEqual("方案说明 + 设计/工程规格", plan["output_plan"]["expression"]["format"])
        self.assertTrue(plan["output_plan"]["primary"]["name"])
        self.assertTrue(plan["orchestration_only"])
        self.assertEqual("04-findings/product-reasoning.json", plan["canonical_reasoning"])
        cpg = roles.recommend_roles("洗衣液配方样品与包装概念", "cpg", "prototype")
        self.assertEqual("R66", cpg["lead_role_id"])
        self.assertIn("L07", {item["id"] for item in cpg["lifecycles"]})
        self.assertLessEqual(cpg["scope"]["selected_count"], 5)
        decision = roles.recommend_roles("是否值得为远程宠物主人做付费试点", "consumer_software", "validation")
        self.assertEqual("decide", decision["task"]["id"])
        self.assertLessEqual(decision["scope"]["selected_count"], 3)
        self.assertEqual("决策备忘 / Business Case", decision["output_plan"]["expression"]["format"])

    def test_cli_list_show_recommend_and_template(self) -> None:
        listed = run_cli("roles", "list", "--lifecycle", "L01", "--json")
        self.assertEqual(0, listed.returncode, listed.stderr)
        payload = json.loads(listed.stdout)
        self.assertEqual(8, payload["count"])
        self.assertEqual(10, len(payload["industries"]))
        shown = run_cli("roles", "show", "R29", "--industry", "ai_native", "--json")
        self.assertEqual(0, shown.returncode, shown.stderr)
        role = json.loads(shown.stdout)
        self.assertGreaterEqual(len(role["sop"]), 5)
        self.assertIn("AI", role["name_en"] + " " + role["name_zh"])
        recommended = run_cli("roles", "recommend", "仓储搬运机器人现场工序与 ROI", "--stage", "concept", "--task", "decide", "--scale", "lean", "--json")
        self.assertEqual(0, recommended.returncode, recommended.stderr)
        recommended_payload = json.loads(recommended.stdout)
        self.assertEqual("industrial_robotics", recommended_payload["industry"]["id"])
        self.assertEqual("decide", recommended_payload["task"]["id"])
        self.assertEqual("lean", recommended_payload["scope"]["mode"])
        self.assertIn("结论与推荐", recommended_payload["output_plan"]["expression"]["structure"])
        template = run_cli("roles", "template", "R09", "--industry", "enterprise_software", "--json")
        self.assertEqual(0, template.returncode, template.stderr)
        rendered = json.loads(template.stdout)
        self.assertEqual("unreviewed", rendered["review_status"])
        self.assertIn("不是研究结论", rendered["markdown"])
        self.assertIn("第二事实源", rendered["markdown"])

    def test_scaffold_writes_execution_pack_but_never_changes_reasoning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            study = Path(directory) / "study"
            study.mkdir()
            reasoning = study / "04-findings/product-reasoning.json"
            reasoning.parent.mkdir()
            reasoning.write_text(json.dumps({"chains": [{
                "id": "PR01",
                "nodes": {node: {"statement": "hypothesis", "evidence_ids": []} for node in roles.CHAIN_NODES},
            }]}), encoding="utf-8")
            before = hashlib.sha256(reasoning.read_bytes()).hexdigest()
            (study / "study.json").write_text(json.dumps({
                "study_id": "role-test",
                "title": "AI Agent 任务研究",
                "product_domain": "software",
                "lifecycle_stage": "concept",
                "industry_context": "ai_native",
                "decision": {"question": "是否进入受限原型测试"},
            }, ensure_ascii=False), encoding="utf-8")
            completed = run_cli("roles", "scaffold", str(study), "--role", "R29", "--role", "R52", "--json")
            self.assertEqual(0, completed.returncode, completed.stderr)
            result = json.loads(completed.stdout)
            self.assertEqual(["R29", "R52"], result["role_ids"])
            self.assertTrue(result["canonical_reasoning_unchanged"])
            self.assertEqual(before, hashlib.sha256(reasoning.read_bytes()).hexdigest())
            plan = json.loads(Path(result["workplan"]).read_text(encoding="utf-8"))
            self.assertTrue(plan["orchestration_only"])
            self.assertIsNone(plan["roles"][0]["kpi_targets"][0]["target"])
            self.assertEqual("not_started", plan["roles"][0]["sop_status"][0]["work_status"])
            self.assertEqual("bound", plan["roles"][0]["chain_targets"][0]["binding_status"])
            self.assertEqual("PR01", plan["roles"][0]["chain_targets"][0]["chain_id"])
            self.assertEqual(64, len(plan["catalog_sha256"]))
            self.assertNotIn("kpis", plan["roles"][0])
            self.assertNotIn("sop", plan["roles"][0])
            self.assertEqual("decide", plan["task"]["id"])
            self.assertEqual("决策备忘 / Business Case", plan["output_plan"]["expression"]["format"])
            self.assertTrue(plan["output_plan"]["primary"]["deliverable_id"])
            self.assertGreaterEqual(len(result["templates"]), 1)
            self.assertLessEqual(len(result["templates"]), 3)
            markdown = Path(result["workplan_markdown"]).read_text(encoding="utf-8")
            self.assertIn("RACI", markdown)
            self.assertIn("KPI", markdown)
            self.assertIn("输出与表达合同", markdown)
            duplicate = run_cli("roles", "scaffold", str(study), "--role", "R29", "--json")
            self.assertEqual(2, duplicate.returncode)
            self.assertIn("exists", json.loads(duplicate.stdout)["reason"])

    def test_all_templates_is_explicit_and_adaptive_scaffold_uses_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            study = Path(directory) / "study"
            make_study(study)
            completed = run_cli(
                "roles", "scaffold", str(study),
                "--task", "design", "--scale", "lean", "--all-templates", "--json",
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            result = json.loads(completed.stdout)
            self.assertEqual("design", result["task"]["id"])
            self.assertEqual("lean", result["scope"]["mode"])
            self.assertLessEqual(len(result["role_ids"]), 3)
            self.assertGreaterEqual(len(result["templates"]), 4)
            plan = json.loads(Path(result["workplan"]).read_text(encoding="utf-8"))
            self.assertTrue(plan["all_templates"])
            self.assertEqual("design", plan["task"]["id"])
            self.assertTrue(plan["output_plan"]["expression"]["structure"])

    def test_role_delivery_is_read_only_chain_projection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            study = Path(directory) / "sample"
            shutil.copytree(ROOT / "examples/sample-study", study)
            reasoning = study / "04-findings/product-reasoning.json"
            before = hashlib.sha256(reasoning.read_bytes()).hexdigest()
            completed = run_cli("deliver", str(study), "--kind", "role", "--role", "R09")
            self.assertEqual(0, completed.returncode, completed.stderr)
            result = json.loads(completed.stdout)
            self.assertTrue(result["canonical_projection"])
            self.assertTrue(result["work_notes_separate"])
            self.assertEqual(["PR01"], result["projected_chain_ids"])
            content = Path(result["path"]).read_text(encoding="utf-8")
            self.assertIn("04-findings/product-reasoning.json#chains/PR01/nodes/user", content)
            self.assertIn("岗位工作备注（不是主链结论）", content)
            self.assertEqual(before, hashlib.sha256(reasoning.read_bytes()).hexdigest())
            missing = run_cli("deliver", str(study), "--kind", "role")
            self.assertEqual(1, missing.returncode)
            self.assertEqual("blocked", json.loads(missing.stdout)["status"])

    def test_role_projection_keeps_multiple_chains_and_domain_detection_conflicts(self) -> None:
        reasoning = {"chains": [
            {"id": "PR01", "nodes": {"user": {"statement": "first", "evidence_ids": []}}},
            {"id": "PR02", "nodes": {"user": {"statement": "second", "evidence_ids": []}}},
        ]}
        with self.assertRaises(ValueError):
            roles.project_role_deliverable(
                {"title": "test", "product_domain": "software", "industry_context": "consumer_software"},
                reasoning, {"records": []}, "R09",
            )
        projected = roles.project_role_deliverable(
            {"title": "test", "product_domain": "software", "industry_context": "consumer_software"},
            reasoning,
            {"records": []},
            "R09",
            chain_id="PR02",
        )
        self.assertEqual(["PR02"], projected["projected_chain_ids"])
        self.assertNotIn("first", projected["markdown"])
        self.assertIn("second", projected["markdown"])
        detected = roles.detect_industry("AI 眼镜夜景与续航", "mobile")
        self.assertEqual("smart_hardware", detected["id"])
        self.assertIn("ai_native", {item["id"] for item in detected["capability_overlays"]})
        with self.assertRaises(ValueError):
            roles.project_role_deliverable({"title": "empty"}, None, {"records": []}, "R09")

    def test_bound_workplan_lifecycle_freshness_and_stale_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            study = Path(directory) / "study"
            reasoning = make_study(study)
            scaffolded = run_cli("roles", "scaffold", str(study), "--role", "R52", "--json")
            self.assertEqual(0, scaffolded.returncode, scaffolded.stderr)
            workplan_path = study / "01-sources" / "role-workbench" / "workplan.json"
            workplan = json.loads(workplan_path.read_text(encoding="utf-8"))
            self.assertEqual([], roles.validate_workplan(workplan, reasoning))
            delivered = run_cli("deliver", str(study), "--kind", "role", "--role", "R52")
            self.assertEqual(0, delivered.returncode, delivered.stderr)
            result = json.loads(delivered.stdout)
            self.assertTrue(result["workplan_bound"])
            self.assertEqual("PR01", result["chain_id"])
            self.assertEqual("06-report", Path(result["path"]).parent.name)
            self.assertTrue(Path(result["path"]).name.startswith("role-R52-D"))
            content = Path(result["path"]).read_text(encoding="utf-8")
            self.assertIn("editable=false", content)
            self.assertIn("输出与表达合同", content)
            self.assertIn("决策备忘 / Business Case", content)
            self.assertIn("## 边界", content)
            lifecycle = run_cli("deliver", str(study), "--kind", "lifecycle")
            self.assertEqual(0, lifecycle.returncode, lifecycle.stderr)
            lifecycle_result = json.loads(lifecycle.stdout)
            self.assertTrue(lifecycle_result["workplan_bound"])
            board = Path(lifecycle_result["path"]).read_text(encoding="utf-8")
            for number in range(1, 11):
                self.assertIn(f"## L{number:02d}", board)
            self.assertIn("不证明", board)
            os.utime(result["path"], (0, 0))
            summary = delivery.build_chat_summary(
                study,
                "role",
                result,
                study=json.loads((study / "study.json").read_text(encoding="utf-8")),
                reasoning=reasoning,
                evidence={"records": []},
                audit_info={"status": "pass", "checks": []},
            )
            self.assertEqual("stale", summary["freshness"]["status"])
            self.assertIn("asset:role-catalog.json", summary["freshness"]["stale_inputs"])
            self.assertIn("--role R52", summary["reproduce_command"])
            self.assertIn("--chain PR01", summary["reproduce_command"])
            stale_plan = copy.deepcopy(workplan)
            stale_plan["catalog_sha256"] = "0" * 64
            self.assertIn("catalog_stale", " ".join(roles.validate_workplan(stale_plan, reasoning)))
            workplan_path.write_text(json.dumps(stale_plan), encoding="utf-8")
            audited = run_cli("audit", str(study), "--json")
            self.assertEqual(1, audited.returncode)
            self.assertIn("role_workplan", audited.stdout)
            with self.assertRaises(ValueError):
                roles.scaffold_workplan(study, ["R52"], force=True)

    def test_scaffold_requires_chain_and_cleans_atomic_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            empty = Path(directory) / "empty"
            make_study(empty, chain_count=0)
            with self.assertRaisesRegex(ValueError, "at least one"):
                roles.scaffold_workplan(empty, ["R29"])
            multi = Path(directory) / "multi"
            make_study(multi, chain_count=2)
            with self.assertRaisesRegex(ValueError, "--chain"):
                roles.scaffold_workplan(multi, ["R29"])
            with mock.patch.object(roles.os, "replace", side_effect=OSError("simulated disk failure")):
                with self.assertRaisesRegex(OSError, "simulated disk failure"):
                    roles.scaffold_workplan(multi, ["R29"], chain_id="PR02")
            self.assertFalse((multi / "01-sources" / "role-workbench").exists())
            self.assertEqual([], list((multi / "01-sources").glob(".role-workbench-*")))

    def test_commercial_kpi_target_requires_business_metric_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            study = Path(directory) / "study"
            reasoning = make_study(study)
            roles.scaffold_workplan(study, ["R34"])
            path = study / "01-sources" / "role-workbench" / "workplan.json"
            plan = json.loads(path.read_text(encoding="utf-8"))
            assignment = plan["roles"][0]
            definitions = {item["id"]: item for item in roles.role_index()["R34"]["kpis"]}
            commercial = next(target for target in assignment["kpi_targets"] if any(
                term in definitions[target["kpi_id"]]["name"].casefold()
                for term in ("收入", "复购", "roi", "转化", "毛利", "营收", "付费", "revenue", "retention")
            ))
            commercial.update({
                "target": 1,
                "time_window": "2026-Q4",
                "denominator": "eligible cohort",
                "data_source_ref": "metric-source-1",
                "owner": "growth-owner",
            })
            errors = roles.validate_workplan(plan, reasoning)
            self.assertIn("business_metric_ref", " ".join(errors))
            commercial["business_metric_ref"] = "PR01.business.success_metrics/M01"
            self.assertEqual([], roles.validate_workplan(plan, reasoning))

    def test_ascii_keyword_boundaries_do_not_create_false_ai_hits(self) -> None:
        self.assertEqual("consumer_software", roles.detect_industry("said", "software")["id"])
        detected = roles.detect_industry("AI native app", "software")
        self.assertEqual("ai_native", detected["id"])
        hardware_plan = roles.recommend_roles("AI 眼镜夜景与续航的设计方案", stage="discovery", base_domain="mobile")
        self.assertEqual("smart_hardware", hardware_plan["industry"]["id"])
        self.assertEqual("design", hardware_plan["task"]["id"])
        self.assertIn("R29", {item["id"] for item in hardware_plan["assignments"]})
        self.assertIn("R52", {item["id"] for item in hardware_plan["assignments"]})
        self.assertLessEqual(len(hardware_plan["assignments"]), 6)

    def test_task_sized_team_and_adaptive_output_contract(self) -> None:
        discovery = roles.recommend_roles(
            "家用摄像头夜间误报的用户不满与替代方案", "smart_hardware", "discovery",
        )
        self.assertEqual("discover", discovery["task"]["id"])
        self.assertEqual("研究简报 / 机会地图", discovery["output_plan"]["expression"]["format"])
        self.assertLessEqual(discovery["scope"]["selected_count"], 3)
        self.assertEqual("lean", discovery["scope"]["mode"])
        self.assertIn("覆盖缺口", " ".join(discovery["output_plan"]["expression"]["structure"]))
        self.assertTrue(discovery["deferred_roles"])

        validation = roles.recommend_roles(
            "智能相机 DVT 可靠性与安全验证", "smart_hardware", "validation",
        )
        self.assertEqual("validate", validation["task"]["id"])
        self.assertEqual("R75", validation["lead_role_id"])
        self.assertEqual("cross_functional", validation["scope"]["mode"])
        self.assertEqual("分层验证报告 + 放行/缺口清单", validation["output_plan"]["expression"]["format"])
        self.assertLessEqual(validation["scope"]["selected_count"], 6)

        lean = roles.recommend_roles(
            "仓储搬运机器人现场工序与 ROI 决策", "industrial_robotics", "concept", scale="lean",
        )
        self.assertEqual("decide", lean["task"]["id"])
        self.assertEqual("lean", lean["scope"]["mode"])
        self.assertLessEqual(len(lean["assignments"]), 3)
        self.assertEqual("决策备忘 / Business Case", lean["output_plan"]["expression"]["format"])
        self.assertTrue(lean["output_plan"]["expression"]["industry_output_exemplars"])
        self.assertTrue(lean["output_plan"]["expression"]["avoid"])

    def test_fullstack_persona_brings_product_accountability_into_lean_team(self) -> None:
        plan = roles.recommend_roles(
            "我是后端研发，转型全栈要自己挖掘用户需求和设计产品", "consumer_software",
        )
        self.assertEqual("discover", plan["task"]["id"])
        self.assertEqual("lean", plan["scope"]["mode"])
        self.assertLessEqual(len(plan["assignments"]), 3)
        self.assertEqual("R09", plan["lead_role_id"])
        by_id = {item["id"]: item for item in plan["assignments"]}
        self.assertIn("R26", by_id)
        self.assertIn("任务触发：转型全栈研发的产品职责", by_id["R26"]["reason"])
        self.assertTrue(plan["orchestration_only"])

        baseline = roles.recommend_roles(
            "用户对现有工具的不满与替代方案研究", "consumer_software",
        )
        self.assertNotIn(
            "任务触发：转型全栈研发的产品职责",
            [item.get("reason", "") for item in baseline["assignments"]],
        )

        recommended = run_cli(
            "roles", "recommend",
            "我是后端研发，转型全栈要自己挖掘用户需求和设计产品", "--json",
        )
        self.assertEqual(0, recommended.returncode, recommended.stderr)
        payload = json.loads(recommended.stdout)
        reasons = {item["id"]: item["reason"] for item in payload["assignments"]}
        self.assertIn("任务触发：转型全栈研发的产品职责", reasons.get("R26", ""))


if __name__ == "__main__":
    unittest.main()
