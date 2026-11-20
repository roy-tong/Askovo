# -*- coding: utf-8 -*-
"""交付物结论门禁：没有商业证据或审计未过时，不把假设写成结论。

此前 `deliver --kind plan` 无条件输出 `**结论：<business statement>**`，
即使 business 节点仍是 hypothesis、没有绑定任何 E4+/E5 商业证据，或者
full audit 未通过。本测试钉住门禁：(1) business validated + 合格 E4+/E5
商业证据 + full audit pass 才给正式结论；(2) 其余情况输出“当前判断 +
缺口 + 下一步补证动作”。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/askovo/scripts"))
import sure_engine  # noqa: E402
sys.path.pop(0)

STUDY = {
    "study_id": "S1",
    "title": "合成门禁测试",
    "route": {"domain_label": "消费硬件", "stage_label": "概念验证"},
    "decision": {"question": "是否投入做这款设备？", "owner": "产品负责人", "deadline": "2026-12-31"},
    "scope": {"allowed_sources": ["reddit"]},
}


def record(record_id: str, level: str, context_key: str = "ctx-1") -> dict:
    return {
        "record_id": record_id,
        "evidence_level": level,
        "context_key": context_key,
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


def chain(
    chain_id: str = "PR1",
    business_status: str = "hypothesis",
    business_evidence=(),
    context_key: str = "ctx-1",
    all_evidence=(),
) -> dict:
    ids = list(all_evidence)
    business = node(
        "把设备卖给需要省钱的家庭",
        business_status,
        business_evidence,
        target_segment="价格敏感家庭",
        payer="家庭采购者",
        revenue_model="硬件一次性收入 + 订阅",
        pricing_hypothesis="199 元/月试点",
        assumptions=["家庭愿意为省电付费"],
        gate={"decision": "试点续费率 ≥ 60%"},
    )
    return {
        "id": chain_id,
        "title": "家庭省电设备",
        "status": "open",
        "context_key": context_key,
        "nodes": {
            "scene": node("电价上涨时家庭开始找省电办法", evidence_ids=ids),
            "user": node("有固定电费预算的家庭采购者", evidence_ids=ids),
            "pain": node("不知道哪些电器最耗电", evidence_ids=ids),
            "need": node("需要可执行的省电建议", evidence_ids=ids),
            "feature": node("实时分项用电监测", evidence_ids=ids),
            "product": node("带 App 的插座式监测设备", evidence_ids=ids),
            "business": business,
        },
        "next_test": "30 天内做 10 户试点并记录续费意愿",
        "failure_condition": "试点续费率低于 30%",
        "prioritization": {"rationale": "证据最完整"},
    }


def plan_text(reasoning: dict, records: list, audit_status: str = "not_run") -> str:
    evidence = {"records": records}
    return "\n".join(
        sure_engine._plan_lines(STUDY, reasoning, evidence, audit_status=audit_status)
    )


class DeliveryConclusionGateTests(unittest.TestCase):
    def test_insufficient_evidence_has_no_formal_conclusion(self) -> None:
        reasoning = {"chains": [chain(all_evidence=["R01"])]}
        text = plan_text(reasoning, [record("R01", "E2")], audit_status="pass")

        self.assertNotIn("**结论：", text)
        self.assertIn("**当前判断：证据不足**", text)
        self.assertIn("商业环节仍处于「假设」状态，未完成验证", text)
        self.assertIn("缺少合格的商业证据", text)
        self.assertIn("当前没有绑定证据", text)
        self.assertIn("bind-evidence", text)
        self.assertIn("缺口是什么", text)
        self.assertIn("下一步补证动作", text)

    def test_validated_business_without_commercial_evidence_still_gated(self) -> None:
        reasoning = {"chains": [chain(business_status="validated", business_evidence=["R01"],
                                     all_evidence=["R01"])]}
        text = plan_text(reasoning, [record("R01", "E2")], audit_status="pass")

        self.assertNotIn("**结论：", text)
        self.assertIn("**当前判断：证据不足**", text)
        self.assertIn("缺少合格的商业证据", text)
        self.assertNotIn("商业环节仍处于", text)

    def test_validated_business_with_commercial_evidence_and_audit_pass_has_conclusion(self) -> None:
        reasoning = {"chains": [chain(business_status="validated",
                                     business_evidence=["R04", "R06"],
                                     all_evidence=["R01", "R04", "R06"])]}
        text = plan_text(
            reasoning,
            [record("R01", "E2"), record("R04", "E4+"), record("R06", "E5")],
            audit_status="pass",
        )

        self.assertIn("**结论：把设备卖给需要省钱的家庭**", text)
        self.assertNotIn("**当前判断：", text)

    def test_audit_not_pass_does_not_render_formal_conclusion(self) -> None:
        reasoning = {"chains": [chain(business_status="validated",
                                     business_evidence=["R04"],
                                     all_evidence=["R04"])]}
        records = [record("R04", "E4+")]
        for status, label in (("not_run", "未运行"), ("fail", "未通过")):
            with self.subTest(audit_status=status):
                text = plan_text(reasoning, records, audit_status=status)
                self.assertNotIn("**结论：", text)
                self.assertIn("**当前判断：完整检查未通过，不作为正式结论**", text)
                self.assertIn(f"状态为「{label}」", text)
                self.assertIn("askovo check S1 --stage full", text)

    def test_default_audit_status_is_not_run(self) -> None:
        reasoning = {"chains": [chain(business_status="validated",
                                     business_evidence=["R04"],
                                     all_evidence=["R04"])]}
        evidence = {"records": [record("R04", "E4+")]}
        text = "\n".join(sure_engine._plan_lines(STUDY, reasoning, evidence))

        self.assertNotIn("**结论：", text)
        self.assertIn("**当前判断：完整检查未通过，不作为正式结论**", text)
        self.assertIn("状态为「未运行」", text)

    def test_gated_plan_body_keeps_engine_vocabulary_out(self) -> None:
        reasoning = {"chains": [chain(all_evidence=["R01"])]}
        text = plan_text(reasoning, [record("R01", "E2")], audit_status="pass")
        body = text[: text.index("## 附录")]

        for token in ("E2", "E4+", "E4-", "hypothesis", "needs-validation", "context_key"):
            self.assertNotIn(token, body)

    def test_multi_chain_gates_each_chain_independently(self) -> None:
        qualified = chain("PR1", business_status="validated", business_evidence=["R04"],
                          all_evidence=["R04"])
        hypothesis = chain("PR2", business_status="hypothesis", all_evidence=["R01"])
        reasoning = {"chains": [qualified, hypothesis]}
        text = plan_text(
            reasoning,
            [record("R01", "E4+"), record("R04", "E4+")],
            audit_status="pass",
        )

        self.assertIn("## 0. 多链结论与推进建议", text)
        self.assertIn("| 链路 | 状态 |", text)
        self.assertEqual(1, text.count("**结论："))
        self.assertIn("**当前判断：证据不足**", text)
        self.assertIn("### 结论 · PR1", text)
        self.assertIn("### 结论 · PR2", text)


if __name__ == "__main__":
    unittest.main()
