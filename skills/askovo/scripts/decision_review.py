"""Decision review: a deterministic quality gate over one study's decision state.

The review does not decide anything and does not generate new business claims.
It reads what already exists — audit verdicts, the seven-node chain, demand
judgments, descriptive analysis and delivered artifacts — and reports whether
the current decision state is verifiable, falsifiable, bias-aware and fresh.

Every item is mechanical: no model call, no score of business success, no
substitute for semantic review or stakeholder sign-off.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import research_loop
import sure_engine

REVIEW_JSON = Path("05-audit/decision-review.json")
REVIEW_MD = Path("05-audit/decision-review.md")
DIMENSIONS = ("audit", "evidence", "decision", "falsifiability", "bias", "deliverables")
DIMENSION_LABELS = {
    "audit": "审计门",
    "evidence": "证据与判断",
    "decision": "决策就绪",
    "falsifiability": "可证伪与下一步",
    "bias": "偏差与覆盖",
    "deliverables": "交付物核验",
}
REPORT_DIR = "06-report"
BOUNDARY_MARKERS = ("## 边界", "## Boundary", "不证明", "does not prove")


def _load(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        text = value.strip().casefold()
        return not text or text in {"tbd", "todo", "待填写", "待确认", "待补充"} or text.startswith(
            ("tbd", "todo", "待填写", "待确认", "待补充"))
    if isinstance(value, (list, dict)):
        return not value
    return False


def _item(dimension: str, item_id: str, status: str, detail: str, next_action: str = "") -> Dict[str, Any]:
    return {
        "dimension": dimension,
        "id": item_id,
        "status": status,
        "detail": detail,
        "next_action": next_action,
    }


def _claim_items(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    mapping = {"supported": "pass", "open": "warn", "exceeds_evidence": "fail",
               "rejected": "info", "deprioritized": "info"}
    for claim in payload.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        reasons = "；".join(str(value) for value in claim.get("reasons") or []) or "无阻断原因"
        items.append(_item(
            "evidence",
            f"claim:{claim.get('id')}",
            mapping.get(str(claim.get("verdict")), "info"),
            f"{claim.get('title') or claim.get('id')} → {claim.get('verdict')}（{reasons}）",
            str(claim.get("next_test") or ""),
        ))
    if not items:
        items.append(_item(
            "evidence", "claims", "warn", "没有登记需求判断，无法核对证据",
            "先写 04-findings/demand-judgments.json"))
    return items


def _decision_items(study: Dict[str, Any], reasoning: Dict[str, Any]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    decision = study.get("decision") if isinstance(study.get("decision"), dict) else {}
    question = decision.get("question")
    items.append(_item(
        "decision", "decision_question",
        "fail" if _missing(question) else "pass",
        f"决策问题：{question}" if not _missing(question) else "缺决策问题",
        "写清要做的选择" if _missing(question) else "",
    ))
    for field_name, label in (("owner", "决策负责人"), ("deadline", "决策截止时间")):
        value = decision.get(field_name)
        items.append(_item(
            "decision", f"decision_{field_name}",
            "warn" if _missing(value) else "pass",
            f"{label}：{value}" if not _missing(value) else f"缺{label}",
            f"补{label}" if _missing(value) else "",
        ))
    options = decision.get("options") if isinstance(decision.get("options"), list) else []
    items.append(_item(
        "decision", "decision_options",
        "pass" if len(options) >= 2 else "fail",
        f"备选方案 {len(options)} 个：" + "；".join(str(item) for item in options[:5]),
        "至少两个真实备选，否则不是决策" if len(options) < 2 else "",
    ))
    minimum = decision.get("minimum_evidence") if isinstance(decision.get("minimum_evidence"), list) else []
    items.append(_item(
        "decision", "decision_minimum_evidence",
        "pass" if minimum else "warn",
        f"最低证据清单 {len(minimum)} 项" if minimum else "没有声明最低证据清单",
        "声明做决定前必须看到什么证据" if not minimum else "",
    ))

    chains = reasoning.get("chains") if isinstance(reasoning.get("chains"), list) else []
    decided = [chain for chain in chains if isinstance(chain, dict) and chain.get("status") == "decided"]
    items.append(_item(
        "decision", "chain_decided",
        "pass" if decided else "warn",
        f"已 decided 的主链：{', '.join(str(c.get('id')) for c in decided)}" if decided
        else "没有 decided 主链；决策包只能列缺口，不能给建议",
        "" if decided else "把证据足够的主链推到 decided，或明确停在 needs-validation",
    ))
    gates = []
    for chain in chains:
        if not isinstance(chain, dict):
            continue
        node = chain.get("nodes") if isinstance(chain.get("nodes"), dict) else {}
        business = node.get("business") if isinstance(node.get("business"), dict) else {}
        gate = business.get("gate") if isinstance(business.get("gate"), dict) else {}
        gates.append(str(gate.get("decision") or ""))
    opened = [value for value in gates if value and value not in ("hypothesis",)]
    items.append(_item(
        "decision", "business_gate",
        "pass" if opened else "warn",
        f"商业门状态：{', '.join(sorted(set(gates))) or '未填写'}",
        "" if opened else "商业门仍是 hypothesis；商业判断不能只靠产品推理",
    ))
    return items


def _falsifiability_items(study: Dict[str, Any], reasoning: Dict[str, Any]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    hypotheses = study.get("hypotheses") if isinstance(study.get("hypotheses"), list) else []
    for hypothesis in hypotheses:
        if not isinstance(hypothesis, dict):
            continue
        falsified = hypothesis.get("falsified_if")
        items.append(_item(
            "falsifiability", f"hypothesis:{hypothesis.get('id')}",
            "fail" if _missing(falsified) else "pass",
            f"{hypothesis.get('id')} 证伪条件：{falsified}" if not _missing(falsified)
            else f"{hypothesis.get('id')} 没有证伪条件",
            "写出什么结果会让你放弃该假设" if _missing(falsified) else "",
        ))
    chains = reasoning.get("chains") if isinstance(reasoning.get("chains"), list) else []
    for chain in chains:
        if not isinstance(chain, dict):
            continue
        chain_id = str(chain.get("id") or "chain")
        next_test = chain.get("next_test")
        items.append(_item(
            "falsifiability", f"chain:{chain_id}:next_test",
            "pass" if not _missing(next_test) else "warn",
            f"{chain_id} 下一步验证：{next_test}" if not _missing(next_test)
            else f"{chain_id} 没有 next_test",
            "" if not _missing(next_test) else "写最小验证动作",
        ))
        gaps = chain.get("gaps") if isinstance(chain.get("gaps"), list) else []
        if not gaps:
            items.append(_item(
                "falsifiability", f"chain:{chain_id}:gaps", "warn",
                f"{chain_id} 没有记录缺口；完整不等于没有未知",
                "记录已知缺口与反证"))
        alternatives = chain.get("alternative_explanations")
        if chain.get("status") in ("decided", "validated") and not alternatives:
            items.append(_item(
                "falsifiability", f"chain:{chain_id}:alternatives", "warn",
                f"{chain_id} 已得出结论，但没有记录其它解释",
                "写下被排除的解释及其证据"))
    return items


def _bias_items(payload: Dict[str, Any], analysis: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    signals = payload.get("signals") if isinstance(payload.get("signals"), dict) else {}
    gates = signals.get("gates") if isinstance(signals.get("gates"), dict) else {}
    if not gates:
        items.append(_item("bias", "signals", "warn", "没有可用的语料信号，无法核对偏差", "先采集或导入材料"))
        return items
    minimum = gates.get("min_evidence_records")
    if isinstance(minimum, dict):
        status = "pass" if minimum.get("status") == "pass" else "fail"
        items.append(_item(
            "bias", "min_evidence_records", status,
            f"记录数 {minimum.get('observed')} / 最低 {minimum.get('required')}",
            "" if status == "pass" else "证据量不足，不能进入决策"))
    family = gates.get("max_source_family_share")
    if isinstance(family, dict) and family.get("status") != "pass":
        items.append(_item(
            "bias", "source_concentration", "warn",
            f"单一来源占比 {float(family.get('observed') or 0):.0%} 超过上限 "
            f"{float(family.get('limit') or 0):.0%}",
            "换来源或分层抽样，不要在同源上加量"))
    duplicate = gates.get("max_normalized_duplicate_rate")
    if isinstance(duplicate, dict) and duplicate.get("status") != "pass":
        items.append(_item(
            "bias", "duplicate_rate", "warn",
            f"重复率 {float(duplicate.get('observed') or 0):.1%} 超过上限",
            "去重后再判断"))
    roles = gates.get("required_corpus_roles")
    if isinstance(roles, dict):
        missing = sorted(name for name, value in roles.items()
                         if isinstance(value, dict) and value.get("status") != "pass")
        if missing:
            items.append(_item(
                "bias", "corpus_roles", "warn",
                "缺语料角色：" + ", ".join(missing),
                "按角色补设计，不要用同类材料填满"))
    coverage = analysis.get("time_coverage") if isinstance(analysis, dict) else None
    if isinstance(coverage, dict) and coverage.get("outside_window"):
        items.append(_item(
            "bias", "time_window", "warn",
            f"{coverage.get('outside_window')} 条记录在声明时间窗口之外",
            "单独解释窗口外记录，或修正研究窗口"))
    if not items:
        items.append(_item("bias", "signals", "pass", "来源、角色、重复率与时间覆盖未触发阈值"))
    return items


def _deliverables(study_dir: Path) -> List[Dict[str, Any]]:
    report_dir = study_dir / REPORT_DIR
    files = sorted(report_dir.glob("*.md")) if report_dir.is_dir() else []
    if not files:
        return [_item("deliverables", "reports", "warn", "尚未生成交付物", "先 deliver 一个角色产物")]
    newest_source = 0.0
    for pattern in ("04-findings/*.json", "05-audit/audit.json", "02-data/*.jsonl"):
        for path in study_dir.glob(pattern):
            newest_source = max(newest_source, path.stat().st_mtime)
    items: List[Dict[str, Any]] = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        stale = path.stat().st_mtime < newest_source
        has_boundary = any(marker in text for marker in BOUNDARY_MARKERS)
        status = "pass" if not stale and has_boundary else "warn"
        reasons = []
        if stale:
            reasons.append("早于最新证据/审计，可能过期")
        if not has_boundary:
            reasons.append("缺边界声明")
        items.append(_item(
            "deliverables", f"report:{path.name}", status,
            f"{path.name}：" + ("；".join(reasons) if reasons else "生成时间与边界声明正常"),
            "重新 deliver 并保留边界" if reasons else "",
        ))
    return items


def review(study_dir: Path) -> Dict[str, Any]:
    """Build the decision review, write JSON/Markdown and return the summary."""
    study_dir = Path(study_dir).resolve()
    cli = research_loop.cli_module()
    payload = cli.audit_payload(study_dir)
    study = _load(study_dir / "study.json") or {}
    reasoning = _load(study_dir / "04-findings" / "product-reasoning.json") or {}
    analysis = _load(study_dir / "04-findings" / "analysis.json")

    items: List[Dict[str, Any]] = []
    failing_checks = [check for check in payload.get("checks") or [] if check.get("status") == "fail"]
    if failing_checks:
        items.append(_item(
            "audit", "audit_gate", "fail",
            "审计失败项：" + "；".join(f"{check.get('id')}: {check.get('detail')}" for check in failing_checks[:5]),
            "先修复审计失败项，再谈决策质量"))
    else:
        items.append(_item("audit", "audit_gate", "pass", "审计门通过"))
    items.extend(_claim_items(payload))
    items.extend(_decision_items(study, reasoning))
    items.extend(_falsifiability_items(study, reasoning))
    items.extend(_bias_items(payload, analysis))
    items.extend(_deliverables(study_dir))

    counts = {status: sum(1 for item in items if item["status"] == status)
              for status in ("fail", "warn", "pass", "info")}
    overall = "fail" if counts["fail"] else ("needs_work" if counts["warn"] else "pass")
    review_payload = {
        "schema_version": "1.0",
        "kind": "askovo.decision-review",
        "study_id": str(study.get("study_id") or ""),
        "study_title": str(study.get("title") or ""),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": overall,
        "counts": counts,
        "dimensions": {
            dimension: [item for item in items if item["dimension"] == dimension]
            for dimension in DIMENSIONS
        },
        "items": items,
        "boundary": (
            "复盘只核对现有材料是否可验证、可证伪、覆盖与新鲜；不判断业务成败，不替代语义复核、"
            "财务/市场评审和业务签收。"
        ),
    }
    json_path = study_dir / REVIEW_JSON
    md_path = study_dir / REVIEW_MD
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(review_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown = _render(review_payload, items)
    md_path.write_text(markdown, encoding="utf-8")
    review_payload["json_path"] = str(json_path)
    review_payload["markdown_path"] = str(md_path)
    return review_payload


def _render(payload: Dict[str, Any], items: List[Dict[str, Any]]) -> str:
    icon = {"pass": "通过", "warn": "待补强", "fail": "不通过", "info": "说明"}
    lines = [
        f"# 决策复盘：{payload.get('study_title') or payload.get('study_id')}",
        "",
        f"- 结论：{icon.get(payload['status'], payload['status'])}"
        f"（不通过 {payload['counts']['fail']}、待补强 {payload['counts']['warn']}）",
        "- 这是对现有材料质量的机械核对，不是业务成败判断。",
        "",
    ]
    for dimension in DIMENSIONS:
        lines.extend([f"## {DIMENSION_LABELS.get(dimension, dimension)}", ""])
        entries = [item for item in items if item["dimension"] == dimension]
        if not entries:
            lines.append("- 无检查项。")
        for item in entries:
            lines.append(f"- [{icon.get(item['status'], item['status'])}] {item['detail']}")
            if item.get("next_action"):
                lines.append(f"  - 下一步：{item['next_action']}")
        lines.append("")
    lines.extend(["## 边界", "", payload["boundary"], ""])
    return "\n".join(lines)
