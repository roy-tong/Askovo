# -*- coding: utf-8 -*-
"""交付文档的缺口文案：未提供的内容要写清影响和补充方式。

此前 BRD/MRD/PRD 把空列表直接 `json.dumps` 成 `[]`，plan 与决策包输出
`待确认`，读者看不出这是“没研究到”还是“没有”。本测试钉住统一文案：
`未提供｜影响：…｜补充方式：…` 或紧凑版 `未提供｜补充方式：…`，
空容器与 `None` 不再出现在正文；每篇文档开头列出“材料缺口”。
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/askovo/scripts"))
import sure_engine  # noqa: E402
sys.path.pop(0)

STUDY = {
    "study_id": "S1",
    "title": "合成缺口测试",
    "route": {"domain_label": "消费硬件", "stage_label": "概念验证"},
    "decision": {"question": "是否投入做这款设备？"},
    "scope": {"allowed_sources": ["reddit"]},
}

GAP_MARK = "未提供｜"


def record(record_id: str = "R01", level: str = "E2") -> dict:
    return {
        "record_id": record_id,
        "evidence_level": level,
        "context_key": "ctx-1",
        "source_family": "reddit",
        "text_excerpt": f"{record_id} 的用户原话",
        "quote": f"{record_id} 的用户原话",
        "captured_at": "2026-11-01",
        "url": f"https://example.com/{record_id}",
    }


def node(statement: str, status: str = "hypothesis", evidence_ids=None, **extra) -> dict:
    payload = {
        "statement": statement,
        "rationale": f"{statement} 的推理依据",
        "status": status,
        "evidence_ids": list(evidence_ids or []),
    }
    payload.update(extra)
    return payload


def sparse_business() -> dict:
    return node(
        "把设备卖给需要省钱的家庭",
        target_segment="价格敏感家庭",
        pricing_hypothesis="199 元/月试点",
    )


def full_business() -> dict:
    return node(
        "把设备卖给需要省钱的家庭",
        status="validated",
        evidence_ids=["R01"],
        market_definition="愿意为省电付费的家庭",
        geographies=["中国"],
        time_window="2026-09 至 2026-11",
        included_markets=["一线城市家庭"],
        excluded_markets=["商用楼宇"],
        target_segment="价格敏感家庭",
        segments=[{"name": "价格敏感家庭", "size": "约 200 万户"}],
        payer="家庭采购者",
        positioning="比智能电表更便宜、免安装",
        competitive_alternatives=["手动查电费账单"],
        channels=["电商旗舰店"],
        pricing_hypothesis="199 元/月试点",
        pricing=[{"amount": 199, "currency": "CNY", "unit": "户", "period": "月"}],
        market_estimates=[
            {
                "population": "一线城市家庭",
                "time_window": "2026",
                "unit": "户",
                "formula": "户数 × 付费意愿",
                "source": "自建抽样",
                "scope": "仅试点城市",
            }
        ],
        assumptions=["家庭愿意为省电付费"],
        gate={
            "stage": "G2",
            "decision": "pilot",
            "owner": "家庭业务负责人",
            "resource_commitment": "2 人 3 个月",
            "revisit_trigger": "续费率低于 50%",
        },
    )


def chain(business: dict, **overrides) -> dict:
    payload = {
        "id": "PR1",
        "title": "家庭省电设备",
        "status": "open",
        "context_key": "ctx-1",
        "demand_judgment_id": "D01",
        "nodes": {
            "scene": node("电价上涨时家庭开始找省电办法", evidence_ids=["R01"]),
            "user": node("有固定电费预算的家庭采购者", evidence_ids=["R01"]),
            "pain": node("不知道哪些电器最耗电", evidence_ids=["R01"]),
            "need": node("需要可执行的省电建议", evidence_ids=["R01"]),
            "feature": node(
                "实时分项用电监测",
                evidence_ids=["R01"],
                capability="按电器拆分用电并给出建议",
                capabilities=[
                    {"name": "实时监测", "what": None, "solves": "不知道哪些电器耗电"},
                    {"name": "账单预测", "what": "按历史账单预测下月费用"},
                ],
                acceptance_conditions=["分项误差不超过 10%"],
            ),
            "product": node(
                "带 App 的插座式监测设备",
                evidence_ids=["R01"],
                form="插座硬件 + 手机 App",
                scope="单户最多 8 个插座",
                non_goals=["不做全屋布线"],
                acceptance_criteria=["连续 7 天无断连"],
            ),
            "business": business,
        },
        "next_test": "30 天内做 10 户试点并记录续费意愿",
        "failure_condition": "试点续费率低于 30%",
        "alternative_explanations": ["也可能只是电价新闻带来的短期关注"],
        "gaps": ["尚未核对家庭的实际付费记录"],
        "prioritization": {"rationale": "证据最完整"},
    }
    payload.update(overrides)
    return payload


def render(func, *args) -> str:
    return "\n".join(func(*args))


class BrdGapNoteTests(unittest.TestCase):
    def test_brd_sparse_chain_has_gap_block(self) -> None:
        text = render(sure_engine._brd_decision_lines, {"chains": [chain(sparse_business())]})

        self.assertIn("### PR1 · 把设备卖给需要省钱的家庭", text)
        self.assertIn("**材料缺口（本篇未提供的内容）**", text)
        self.assertIn(
            "- PR1 · 决策人：未提供｜影响：无法确定谁对投入负责｜补充方式：补写对这次投入负责的人",
            text,
        )
        self.assertIn(
            "- PR1 · 商业证据：未提供｜影响：商业判断没有可核对的成交或付费依据",
            text,
        )
        self.assertIn("- 决策人：未提供｜影响：无法确定谁对投入负责", text)
        self.assertIn("> 缺口不是结论：补齐前，相应判断保持待验证。", text)
        for token in ("待填写", "待确认", "[]", "{}", "None"):
            self.assertNotIn(token, text)

    def test_brd_full_chain_has_no_gap_block(self) -> None:
        text = render(sure_engine._brd_decision_lines, {"chains": [chain(full_business())]})

        self.assertNotIn("材料缺口", text)
        self.assertIn("- 决策人：家庭业务负责人", text)
        self.assertIn("- 资源承诺：2 人 3 个月", text)
        self.assertIn("- 复审触发：续费率低于 50%", text)
        self.assertIn("- 商业证据：`R01`", text)
        self.assertIn("- 需求判断：`D01`", text)
        self.assertIn("`G2` / `pilot`", text)
        for token in (GAP_MARK, "待填写", "待确认", "[]", "{}", "None"):
            self.assertNotIn(token, text)


class MrdGapNoteTests(unittest.TestCase):
    def test_mrd_never_prints_empty_containers(self) -> None:
        sparse = render(sure_engine._mrd_lines, {"chains": [chain(sparse_business())]})

        for label in ("市场定义", "地理范围", "时间窗", "价格口径", "市场估计口径"):
            self.assertIn(f"- PR1 · {label}：{GAP_MARK}", sparse)
        for label in ("地理范围", "价格口径", "市场估计口径"):
            self.assertIn(f"- {label}：{GAP_MARK}", sparse)
        self.assertIn("- 目标细分：价格敏感家庭", sparse)
        for token in ("待填写", "待确认", "[]", "{}", "None"):
            self.assertNotIn(token, sparse)

        full = render(sure_engine._mrd_lines, {"chains": [chain(full_business())]})
        self.assertNotIn("材料缺口", full)
        self.assertIn("地理范围：中国", full)
        self.assertIn("amount：199", full)
        self.assertIn("population：一线城市家庭", full)
        for token in (GAP_MARK, "待填写", "待确认", "[]", "{}", "None"):
            self.assertNotIn(token, full)


class PrdGapNoteTests(unittest.TestCase):
    def test_prd_lists_capability_gaps_once(self) -> None:
        text = render(sure_engine._prd_lines, {"chains": [chain(sparse_business())]})

        self.assertIn("**材料缺口（本篇未提供的内容）**", text)
        self.assertEqual(1, text.count("逐条能力说明"))
        self.assertIn(
            "- PR1 · 逐条能力说明：未提供｜影响：无法判断每条能力解决哪个需求", text
        )
        self.assertIn(
            "- 逐条能力 实时监测：未提供｜补充方式：补写每条能力做什么、对应哪个需求"
            "（对应：不知道哪些电器耗电）",
            text,
        )
        self.assertIn("- 逐条能力 账单预测：按历史账单预测下月费用", text)
        self.assertIn("- 非目标（不做什么）：不做全屋布线", text)
        for token in ("待填写", "待确认", "[]", "{}", "None"):
            self.assertNotIn(token, text)


class PlanHeaderGapTests(unittest.TestCase):
    def test_plan_header_uses_gap_notes(self) -> None:
        sparse = sparse_business()
        reasoning = {"chains": [chain(sparse)]}
        reasoning["chains"][0]["nodes"]["scene"]["statement"] = None
        reasoning["chains"][0]["nodes"]["user"]["statement"] = "待填写"
        text = render(
            sure_engine._plan_lines,
            STUDY,
            reasoning,
            {"records": [record()]},
            "not_run",
        )

        self.assertIn("- 负责人：未提供｜补充方式：补写决策负责人", text)
        self.assertIn("截止：未提供｜补充方式：补写截止时间", text)
        self.assertIn(
            "| 场景 | 未提供｜补充方式：补写该环节的一句话结论 |", text
        )
        for token in ("待填写", "待确认", "[]", "{}", "None"):
            self.assertNotIn(token, text)


class NonReportDeliveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.study_dir = Path(self._tmp.name)
        (self.study_dir / "04-findings").mkdir(parents=True)
        (self.study_dir / "study.json").write_text(
            json.dumps(STUDY, ensure_ascii=False), encoding="utf-8"
        )
        (self.study_dir / "04-findings/product-reasoning.json").write_text(
            json.dumps({"chains": [chain(sparse_business())]}, ensure_ascii=False),
            encoding="utf-8",
        )
        self.evidence = {
            "count": 1,
            "collected_count": 0,
            "by_form": {"quote": 1},
            "by_claim": {"pain": 1},
            "records": [record()],
        }

    def test_non_report_delivery_reuses_risk_section(self) -> None:
        result = sure_engine._deliver_artifact(
            self.study_dir, kind="memo", evidence=self.evidence
        )

        self.assertEqual("written", result["status"])
        text = (self.study_dir / "06-report/memo.md").read_text(encoding="utf-8")
        self.assertIn("## 反证、缺口与下一步", text)
        self.assertIn("- 也可能只是电价新闻带来的短期关注", text)
        self.assertIn("- 尚未核对家庭的实际付费记录", text)
        self.assertIn("**下一验证**：30 天内做 10 户试点并记录续费意愿", text)
        for token in ("建议（做/不做/调整哪个节点", "缺口（按推理节点和推导关系列"):
            self.assertNotIn(token, text)

    def test_decision_fallback_has_no_template_prompts(self) -> None:
        sure_engine._deliver_artifact(self.study_dir, kind="memo", evidence=self.evidence)
        text = (self.study_dir / "06-report/memo.md").read_text(encoding="utf-8")

        self.assertIn("- 产品判断：带 App 的插座式监测设备", text)
        self.assertIn("- 商业判断：把设备卖给需要省钱的家庭", text)
        self.assertIn("- 取舍与代价：", text)
        for token in ("待填写", "待确认", "建议研读", "请补充"):
            self.assertNotIn(token, text)

    def test_delivery_without_reasoning_states_gap_plainly(self) -> None:
        (self.study_dir / "04-findings/product-reasoning.json").unlink()

        sure_engine._deliver_artifact(self.study_dir, kind="memo", evidence=self.evidence)
        text = (self.study_dir / "06-report/memo.md").read_text(encoding="utf-8")

        self.assertIn("本次交付没有可投影的七节点推理链", text)
        self.assertIn("尚未建立推理主链，暂无已登记的反证、缺口与下一验证", text)
        self.assertNotIn("材料缺口", text)


class DeliveryMissingTests(unittest.TestCase):
    def test_delivery_missing_treats_placeholders_as_missing(self) -> None:
        for value in (
            None,
            "",
            "   ",
            "待填写",
            "待确认（等负责人补充）",
            "TBD",
            " none ",
            "N/A",
            [],
            {},
            [None, ""],
            {"owner": None, "deadline": "待填写"},
        ):
            with self.subTest(value=value):
                self.assertTrue(sure_engine._delivery_missing(value))

        for value in (0, False, "0", "已确认", ["中国"], {"owner": "张三"}):
            with self.subTest(value=value):
                self.assertFalse(sure_engine._delivery_missing(value))

    def test_delivery_value_skips_missing_items(self) -> None:
        self.assertEqual(
            "owner：张三", sure_engine._delivery_value({"owner": "张三", "deadline": None})
        )
        self.assertEqual("甲；乙", sure_engine._delivery_value(["甲", "", None, "乙"]))
        self.assertEqual("0", sure_engine._delivery_value(0))


if __name__ == "__main__":
    unittest.main()
