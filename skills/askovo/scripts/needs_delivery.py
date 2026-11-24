"""Business-first requirements projection of the canonical reasoning chains."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


NODE_LABELS = {
    "scene": "场景",
    "user": "用户",
    "pain": "痛点",
    "need": "需求",
}

FIELD_LABELS = {
    "trigger": "触发",
    "environment": "环境",
    "task_context": "任务背景",
    "role": "角色",
    "state": "当前状态",
    "decision_role": "决策角色",
    "current_substitute": "当前替代做法",
    "friction_cost": "摩擦与代价",
    "consequence": "不解决的后果",
    "desired_outcome": "期望结果",
    "constraints": "约束",
    "measure": "衡量方式",
}


def _chains(reasoning: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(reasoning, dict):
        return []
    return [item for item in reasoning.get("chains") or [] if isinstance(item, dict)]


def _nodes(chain: dict[str, Any]) -> dict[str, dict[str, Any]]:
    nodes = chain.get("nodes")
    if not isinstance(nodes, dict):
        return {}
    return {name: value for name, value in nodes.items() if isinstance(value, dict)}


def _text(value: Any) -> str:
    if isinstance(value, list):
        return "；".join(_text(item) for item in value if _text(item))
    if isinstance(value, dict):
        return "；".join(f"{key}={_text(item)}" for key, item in value.items() if _text(item))
    return " ".join(str(value or "").split())


def _cell(value: Any) -> str:
    return _text(value).replace("|", "\\|") or "未记录"


COMPARISON_FIELDS = {
    "demand": {
        "scene": ("statement", "trigger", "environment", "task_context", "rationale"),
        "user": ("statement", "role", "state", "decision_role", "rationale"),
        "pain": ("statement", "current_substitute", "friction_cost", "consequence", "rationale"),
        "need": ("statement", "desired_outcome", "constraints", "measure", "rationale"),
    },
    "solution": {
        "feature": (
            "statement", "capability", "capabilities", "acceptance_conditions",
            "alternatives_considered", "rationale",
        ),
        "product": (
            "statement", "form", "scope", "non_goals", "acceptance_criteria", "rationale",
        ),
    },
    "business": {
        "business": (
            "statement", "market_definition", "geographies", "time_window",
            "included_markets", "excluded_markets", "target_segment", "segments",
            "payer", "positioning", "revenue_model", "pricing_hypothesis", "pricing",
            "channels", "competitive_alternatives", "cost_drivers", "market_estimates",
            "unit_economics_inputs", "success_metrics", "non_goals", "gate", "rationale",
        ),
    },
}

GROUP_TITLES = {
    "demand": "场景、痛点或需求变化",
    "solution": "特性或产品变化",
    "business": "商业变化",
}

GROUP_FIELD_LABELS = {
    "statement": "一句话判断",
    "rationale": "推导理由",
    "capability": "候选能力",
    "capabilities": "能力明细",
    "acceptance_conditions": "特性验收",
    "alternatives_considered": "替代方案",
    "form": "产品形态",
    "scope": "产品范围",
    "non_goals": "明确不做",
    "acceptance_criteria": "产品验收",
    "market_definition": "市场边界",
    "geographies": "区域",
    "time_window": "时间窗",
    "included_markets": "纳入市场",
    "excluded_markets": "排除市场",
    "target_segment": "目标人群",
    "segments": "细分市场",
    "payer": "付费者",
    "positioning": "定位",
    "revenue_model": "收入方式",
    "pricing_hypothesis": "定价假设",
    "pricing": "定价假设",
    "channels": "渠道",
    "competitive_alternatives": "竞争替代",
    "cost_drivers": "成本",
    "market_estimates": "市场估计",
    "unit_economics_inputs": "单位经济",
    "success_metrics": "成功指标",
    "gate": "资源门",
}


def load_baseline(reference: str | Path) -> tuple[dict[str, Any], str]:
    path = Path(reference).expanduser().resolve()
    if path.is_dir():
        path = path / "04-findings" / "product-reasoning.json"
    if not path.is_file():
        raise ValueError(
            f"baseline product-reasoning.json not found: {path}; "
            "provide a previous study directory or JSON file"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"cannot parse baseline product reasoning: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("chains"), list):
        raise ValueError("baseline product reasoning must be an object with a chains list")
    return payload, str(path)


def _chain_summary(chain: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(chain.get("id") or "PR?"),
        "title": str(chain.get("title") or "未命名需求链"),
        "status": str(chain.get("status") or ""),
    }


def compare(
    current: dict[str, Any] | None,
    baseline: dict[str, Any] | None,
) -> dict[str, Any]:
    current_chains = _chains(current)
    baseline_chains = _chains(baseline)
    current_by_id = {str(chain.get("id")): chain for chain in current_chains}
    baseline_by_id = {str(chain.get("id")): chain for chain in baseline_chains}
    added = [
        _chain_summary(chain) for chain in current_chains
        if str(chain.get("id")) not in baseline_by_id
    ]
    removed = [
        _chain_summary(chain) for chain in baseline_chains
        if str(chain.get("id")) not in current_by_id
    ]
    changes: dict[str, list[dict[str, Any]]] = {
        "demand": [], "solution": [], "business": [],
    }
    evidence_changes: list[dict[str, Any]] = []
    status_changes: list[dict[str, Any]] = []
    for chain in current_chains:
        chain_id = str(chain.get("id"))
        old_chain = baseline_by_id.get(chain_id)
        if old_chain is None:
            continue
        old_nodes = _nodes(old_chain)
        new_nodes = _nodes(chain)
        for group, node_fields in COMPARISON_FIELDS.items():
            for node_name, fields in node_fields.items():
                old_node = old_nodes.get(node_name, {})
                new_node = new_nodes.get(node_name, {})
                for field in fields:
                    if old_node.get(field) == new_node.get(field):
                        continue
                    changes[group].append({
                        "chain_id": chain_id,
                        "title": str(chain.get("title") or ""),
                        "node": node_name,
                        "field": field,
                        "before": old_node.get(field),
                        "after": new_node.get(field),
                    })
        for node_name in set(old_nodes) | set(new_nodes):
            old_node = old_nodes.get(node_name, {})
            new_node = new_nodes.get(node_name, {})
            if (old_node.get("evidence_ids") or []) != (new_node.get("evidence_ids") or []):
                evidence_changes.append({
                    "chain_id": chain_id,
                    "title": str(chain.get("title") or ""),
                    "node": node_name,
                    "before": old_node.get("evidence_ids") or [],
                    "after": new_node.get("evidence_ids") or [],
                })
            if old_node.get("status") != new_node.get("status"):
                status_changes.append({
                    "chain_id": chain_id,
                    "title": str(chain.get("title") or ""),
                    "node": node_name,
                    "before": old_node.get("status"),
                    "after": new_node.get("status"),
                })
        if old_chain.get("status") != chain.get("status"):
            status_changes.append({
                "chain_id": chain_id,
                "title": str(chain.get("title") or ""),
                "node": "chain",
                "before": old_chain.get("status"),
                "after": chain.get("status"),
            })
    return {
        "added": added,
        "removed": removed,
        "changes": changes,
        "evidence_changes": evidence_changes,
        "status_changes": status_changes,
        "counts": {
            "added": len(added),
            "removed": len(removed),
            "demand": len(changes["demand"]),
            "solution": len(changes["solution"]),
            "business": len(changes["business"]),
            "evidence": len(evidence_changes),
            "status": len(status_changes),
        },
    }


def _statement(node: dict[str, Any]) -> str:
    return _text(node.get("statement")) or "未记录"


def _chain_records(
    chain: dict[str, Any],
    records: dict[str, dict[str, Any]],
    node_names: set[str] | None = None,
) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for node_name, node in _nodes(chain).items():
        if node_names is not None and node_name not in node_names:
            continue
        for record_id in node.get("evidence_ids") or []:
            record_id = str(record_id)
            if record_id in seen or record_id not in records:
                continue
            seen.add(record_id)
            found.append(records[record_id])
    return found


def _record_time(record: dict[str, Any]) -> str:
    for field in ("captured_at", "source_date", "published_at", "created_at", "timestamp", "updated_at"):
        value = str(record.get(field) or "").strip()
        if value:
            return value[:10]
    return ""


def _data_basis(records: list[dict[str, Any]]) -> str:
    families = sorted({
        str(record.get("source_family") or "").strip()
        for record in records
        if str(record.get("source_family") or "").strip()
    })
    times = sorted({_record_time(record) for record in records if _record_time(record)})
    parts = [f"{len(records)} 条可核对记录"]
    if families:
        parts.append("来源 " + "、".join(families))
    if times:
        parts.append("时间窗 " + (times[0] if len(times) == 1 else f"{times[0]} 至 {times[-1]}"))
    return "- **数据基础**：" + "；".join(parts) + "；绑定不等于需求已验证。"


def _voice_lines(records: list[dict[str, Any]], limit: int = 2) -> list[str]:
    lines: list[str] = []
    for record in records:
        text = _text(record.get("text_excerpt") or record.get("quote") or record.get("text"))
        if not text:
            continue
        if not lines:
            lines.append("- **来自语料的声音**：")
        family = str(record.get("source_family") or "未知来源")
        lines.append(f"  - {family} · `{record.get('record_id')}`：“{text}”")
        if len(lines) > limit:
            break
    return lines


def _node_lines(node: dict[str, Any], node_name: str) -> list[str]:
    lines = [f"- **{NODE_LABELS[node_name]}**：{_statement(node)}"]
    for field, label in FIELD_LABELS.items():
        if field not in node:
            continue
        value = _text(node.get(field))
        if value:
            lines.append(f"  - {label}：{value}")
    return lines


def _research_appendix(
    study: dict[str, Any],
    reasoning: dict[str, Any] | None,
    evidence: dict[str, Any],
    audit_status: str = "not_run",
    baseline: dict[str, Any] | None = None,
    baseline_ref: str = "",
) -> str:
    chains = _chains(reasoning)
    comparison = compare(reasoning, baseline) if baseline is not None else None
    records = {
        str(record.get("record_id")): record
        for record in evidence.get("records") or []
        if isinstance(record, dict) and record.get("record_id")
    }
    lines = [
        "## 附录：研究依据与完整明细",
        "",
        "> 阅读顺序：先看场景—痛点—需求，再看需求—特性—产品，最后看特性—产品—商业。",
    ]
    if comparison is None:
        lines.append("> 未提供前后基线：本报告只描述当前需求，不断言哪些是新增、强化、弱化或消失。")
    else:
        lines.append(f"> 对照基线：`{baseline_ref}`；新增不等于已验证，移出当前链也不等于需求消失。")
    lines.append("")
    if audit_status != "pass":
        lines.extend([
            "> **审计未通过：本报告是研究草稿，不能作为已审核结论或签收依据。**",
            "",
        ])

    if comparison is not None:
        counts = comparison["counts"]
        lines.extend([
            "## 0. 需求变化总览",
            "",
            f"新增需求链 {counts['added']} · 移出需求链 {counts['removed']} · "
            f"场景/痛点/需求变化 {counts['demand']} 处 · 特性/产品变化 {counts['solution']} 处 · "
            f"商业变化 {counts['business']} 处。",
            "",
            "### 新增需求链",
            "",
        ])
        if comparison["added"]:
            for chain in comparison["added"]:
                lines.append(f"- `{chain['id']}` {chain['title']}：当前新增的需求链，仍需按原状态与人工复核边界阅读。")
        else:
            lines.append("- 无新增需求链。")
        lines.append("")

        for group in ("demand", "solution", "business"):
            lines.extend([f"### {GROUP_TITLES[group]}", ""])
            items = comparison["changes"][group]
            if group == "demand" and items:
                lines.append("- 需求表述变化按字段保留旧值与新值：")
            if not items:
                lines.append("- 无语义字段变化。")
            for change in items:
                field_label = FIELD_LABELS.get(change["field"]) or GROUP_FIELD_LABELS.get(change["field"], change["field"])
                node_label = NODE_LABELS.get(change["node"], "商业")
                lines.append(
                    f"- `{change['chain_id']}` · {node_label} / {field_label}："
                    f"{_text(change['before']) or '未记录'} → {_text(change['after']) or '未记录'}"
                )
            lines.append("")
            if group == "demand":
                lines.extend(["### 不再出现在当前链的需求", ""])
                if comparison["removed"]:
                    for chain in comparison["removed"]:
                        lines.append(f"- `{chain['id']}` {chain['title']}：只表示当前链不再包含它，不据此断言需求消失。")
                else:
                    lines.append("- 无移出需求链。")
                lines.append("")
        lines.extend([
            "### 证据与状态变化（不等于需求语义变化）",
            "",
            f"- 证据绑定变化 {counts['evidence']} 处；链/节点状态变化 {counts['status']} 处。它们提示复核，不单独构成新增需求。",
            "",
        ])
    else:
        lines.extend([
            "## 0. 当前需求总览",
            "",
            "| 链路 | 用户 | 场景 | 痛点 | 需求 | 已绑定记录 |",
            "|---|---|---|---|---|---:|",
        ])
        for chain in chains:
            nodes = _nodes(chain)
            chain_records = _chain_records(chain, records)
            lines.append(
                f"| `{_cell(chain.get('id'))}` {_cell(chain.get('title'))} "
                f"| {_cell(nodes.get('user', {}).get('role') or nodes.get('user', {}).get('statement'))} "
                f"| {_cell(nodes.get('scene', {}).get('statement'))} "
                f"| {_cell(nodes.get('pain', {}).get('statement'))} "
                f"| {_cell(nodes.get('need', {}).get('desired_outcome') or nodes.get('need', {}).get('statement'))} "
                f"| {len(chain_records)} |"
            )
        if not chains:
            lines.append("| — | — | — | — | 尚未建立需求链 | 0 |")
        lines.append("")

    lines.extend(["## 1. 场景—痛点—需求", ""])
    for chain in chains:
        nodes = _nodes(chain)
        lines.extend([f"### {chain.get('id', 'PR?')} · {chain.get('title', '未命名需求链')}", ""])
        for node_name in ("scene", "user", "pain", "need"):
            lines.extend(_node_lines(nodes.get(node_name, {}), node_name))
        demand_records = _chain_records(chain, records, {"scene", "user", "pain", "need"})
        lines.append(_data_basis(demand_records))
        lines.extend(_voice_lines(demand_records))
        lines.append("")

    lines.extend(["## 2. 需求—特性—产品", ""])
    for chain in chains:
        nodes = _nodes(chain)
        feature = nodes.get("feature", {})
        product = nodes.get("product", {})
        lines.extend([
            f"### {chain.get('id', 'PR?')} · {chain.get('title', '未命名需求链')}",
            "",
            f"- **候选特性**：{_statement(feature)}",
            f"- **为什么能回应需求**：{_text(feature.get('rationale')) or '未记录'}",
            f"- **产品形态**：{_statement(product)}",
            f"- **为什么是这个产品**：{_text(product.get('rationale')) or '未记录'}",
            f"- **产品边界**：{_text(product.get('non_goals')) or '未记录'}",
            "",
        ])

    lines.extend(["## 3. 特性—产品—商业", ""])
    for chain in chains:
        business = _nodes(chain).get("business", {})
        gate = business.get("gate") if isinstance(business.get("gate"), dict) else {}
        lines.extend([
            f"### {chain.get('id', 'PR?')} · {chain.get('title', '未命名需求链')}",
            "",
            f"- **商业假设**：{_statement(business)}",
            f"- **市场边界**：{_text(business.get('market_definition')) or '未记录'}",
            f"- **付费者假设**：{_text(business.get('payer')) or '未记录'}",
            f"- **定价假设**：{_text(business.get('pricing_hypothesis')) or '未记录'}",
            f"- **资源门**：{_text(gate.get('decision')) or '未记录'}",
            "",
        ])

    used = {
        str(record_id)
        for chain in chains
        for node in _nodes(chain).values()
        for record_id in node.get("evidence_ids") or []
    }
    unused_count = sum(1 for record_id in records if record_id not in used)
    lines.extend([
        "## 4. 新需求发现边界",
        "",
        f"- 当前有 {unused_count} 条已编码记录未进入需求链；它们只是待语义复核材料，**不自动算作新增需求**。",
        "- 新需求需要经过语义候选、人工复核、证据登记和需求链新增或更新；重新渲染报告不会创造新需求。",
        "- 记录数不是人数，来源命中不是需求成立，替代品购买也不是我方产品需求。",
        "",
        "## 附录：研究状态",
        "",
        f"- 结构审计：`{audit_status}`；它只检查结构与证据连接，不证明市场需求或商业成立。",
        "- 本报告是七节点需求链的只读投影，不补写链上不存在的用户、买家、价格、验收或产品结论。",
    ])
    return "\n".join(lines) + "\n"


BUSINESS_STATUS_LABELS = {
    "draft": "草稿，尚未形成业务判断",
    "hypothesis": "仅是假设，尚未验证",
    "needs-validation": "有线索，仍需验证",
    "validated": "已有较完整依据，仍需负责人复核",
    "decided": "已记录为当前选择，不代表市场已经验证",
    "rejected": "已否决",
    "deprioritized": "暂缓",
}

CHANGE_NODE_LABELS = {
    "scene": "场景",
    "user": "用户",
    "pain": "痛点",
    "need": "需求",
    "feature": "特性",
    "product": "产品",
    "business": "商业",
    "chain": "整体状态",
}


def _business_headline(
    chains: list[dict[str, Any]],
    comparison: dict[str, Any] | None,
) -> str:
    if comparison is None:
        return f"当前有 {len(chains)} 条需求方向；没有旧版对照，不能判断哪些是新增或变化。"
    counts = comparison["counts"]
    if not any(counts[key] for key in ("added", "removed", "demand", "solution", "business")):
        return "没有发现新增需求，也没有改变既有产品和商业判断。"
    return (
        f"发现 {counts['added']} 条新增需求方向、{counts['demand']} 处需求定义调整；"
        f"产品方案变化 {counts['solution']} 处，商业判断变化 {counts['business']} 处。"
    )


def _focus_chains(
    chains: list[dict[str, Any]],
    comparison: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if comparison is None:
        return list(chains)
    changed_ids = {item["id"] for item in comparison["added"]}
    for group in comparison["changes"].values():
        changed_ids.update(item["chain_id"] for item in group)
    focused = [chain for chain in chains if str(chain.get("id")) in changed_ids]
    focused.extend(chain for chain in chains if chain not in focused)
    return focused


def _business_card(chain: dict[str, Any], prefix: str = "") -> list[str]:
    nodes = _nodes(chain)
    user = nodes.get("user", {})
    scene = nodes.get("scene", {})
    pain = nodes.get("pain", {})
    need = nodes.get("need", {})
    role = _text(user.get("role") or user.get("statement")) or "未明确"
    scene_text = _text(scene.get("statement") or scene.get("trigger")) or "未明确"
    substitute = _text(pain.get("current_substitute")) or "未记录"
    friction = _text(pain.get("friction_cost") or pain.get("statement")) or "未记录"
    consequence = _text(pain.get("consequence")) or "未记录"
    outcome = _text(need.get("desired_outcome") or need.get("statement")) or "未记录"
    measure = _text(need.get("measure")) or "未记录"
    status = BUSINESS_STATUS_LABELS.get(str(chain.get("status") or ""), "当前状态待确认")
    return [
        f"### {prefix}{chain.get('title', '未命名需求方向')}",
        "",
        f"- **谁、在什么场景**：{role}；{scene_text}",
        f"- **现在怎么做**：{substitute}",
        f"- **卡在哪里**：{friction}",
        f"- **造成什么影响**：{consequence}",
        f"- **真正需要**：{outcome}",
        f"- **业务上怎么算有效**：{measure}",
        f"- **当前判断**：{status}",
        "",
    ]


def _append_change_cards(
    lines: list[str],
    comparison: dict[str, Any],
    group: str,
    prefix: str,
) -> None:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for change in comparison["changes"][group]:
        key = (change["chain_id"], change["title"])
        grouped.setdefault(key, []).append(change)
    for (_, title), changes in grouped.items():
        lines.extend([f"### {prefix}{title}", ""])
        for change in changes:
            field_label = FIELD_LABELS.get(change["field"]) or GROUP_FIELD_LABELS.get(
                change["field"], change["field"]
            )
            node_label = CHANGE_NODE_LABELS.get(change["node"], change["node"])
            lines.append(
                f"- **{node_label} / {field_label}**：以前：{_text(change['before']) or '未记录'}；"
                f"现在：{_text(change['after']) or '未记录'}。"
            )
        lines.append("")


def _business_projection(
    study: dict[str, Any],
    reasoning: dict[str, Any] | None,
    comparison: dict[str, Any] | None,
) -> dict[str, Any]:
    chains = _chains(reasoning)
    focused = _focus_chains(chains, comparison)
    headline = _business_headline(chains, comparison)
    lines = [
        "# 业务需求报告",
        "",
        "> 面向业务负责人、产品经理和需求分析人员。先读业务结论，再到附录核对研究细节。",
        "",
        f"研究主题：{study.get('title', '')}",
        "",
        "## 业务结论",
        "",
        f"- **{headline}**",
    ]
    if comparison is None:
        lines.append("- 本次先呈现当前需求；只有完成前后对照，才能判断新增、强化、弱化或移出。")
    elif not any(comparison["counts"][key] for key in ("added", "removed", "demand", "solution", "business")):
        lines.append("- 原需求方向、产品方案和商业假设保持原样；工具重跑本身不构成业务变化。")
        if comparison["counts"]["evidence"] or comparison["counts"]["status"]:
            lines.append("- 研究依据或状态有更新，需要负责人复核，但没有改写需求定义。")
    else:
        lines.append("- 新增方向仍需验证，不等于已经决定投入；变化按需求、方案、商业的顺序展开。")
    lines.append("")

    if comparison is None:
        lines.extend(["## 当前需求方向", ""])
        for chain in focused[:3]:
            lines.extend(_business_card(chain))
        if len(focused) > 3:
            lines.append(f"其余 {len(focused) - 3} 条需求方向见附录；这里按原研究顺序展示，不代表重新排序。")
            lines.append("")
    else:
        lines.extend(["## 需求变化", ""])
        if not comparison["added"] and not comparison["removed"] and not comparison["changes"]["demand"]:
            lines.extend(["没有新增、移出或改写需求方向。", ""])
        current_by_id = {str(chain.get("id")): chain for chain in chains}
        for added in comparison["added"]:
            chain = current_by_id.get(added["id"])
            if chain:
                lines.extend(_business_card(chain, "新增方向："))
        _append_change_cards(lines, comparison, "demand", "需求调整：")
        for removed in comparison["removed"]:
            lines.extend([
                f"### 不再跟踪：{removed['title']}",
                "",
                "这条方向不再出现在当前研究中，但不能据此断言用户需求已经消失。",
                "",
            ])

    lines.extend(["## 对产品方案的影响", ""])
    if comparison is not None:
        if comparison["changes"]["solution"]:
            _append_change_cards(lines, comparison, "solution", "方案调整：")
        else:
            lines.extend(["没有产品方案调整。", ""])
    else:
        for chain in focused[:3]:
            nodes = _nodes(chain)
            feature = nodes.get("feature", {})
            product = nodes.get("product", {})
            lines.extend([
                f"### {chain.get('title', '未命名需求方向')}",
                "",
                f"- **候选特性**：{_statement(feature)}",
                f"- **产品形态**：{_statement(product)}",
                f"- **为什么这样匹配**：{_text(feature.get('rationale')) or '未记录'}",
                "",
            ])

    lines.extend(["## 对商业判断的影响", ""])
    if comparison is not None:
        if comparison["changes"]["business"]:
            _append_change_cards(lines, comparison, "business", "商业调整：")
        else:
            lines.extend(["没有商业判断调整。", ""])
    else:
        for chain in focused[:3]:
            business = _nodes(chain).get("business", {})
            lines.append(f"- **{chain.get('title', '未命名需求方向')}**：{_statement(business)}")
            payer = _text(business.get("payer"))
            pricing = _text(business.get("pricing_hypothesis"))
            if payer or pricing:
                lines.append(f"  - 付费者与定价：{payer or '未记录'}；{pricing or '未记录'}")
        lines.append("")

    lines.extend(["## 下一步怎么推进", ""])
    next_actions: list[dict[str, Any]] = []
    for chain in focused:
        action = _text(chain.get("next_test"))
        stop_condition = _text(chain.get("failure_condition"))
        if not action and not stop_condition:
            continue
        next_actions.append({
            "title": str(chain.get("title") or "未命名需求方向"),
            "action": action,
            "measure": _text(_nodes(chain).get("need", {}).get("measure")),
            "stop_condition": stop_condition,
        })
    if next_actions:
        for item in next_actions[:3]:
            lines.extend([f"### {item['title']}", ""])
            if item["action"]:
                lines.append(f"- **推进动作**：{item['action']}")
            if item["measure"]:
                lines.append(f"- **怎么判断有效**：{item['measure']}")
            if item["stop_condition"]:
                lines.append(f"- **停止或调整条件**：{item['stop_condition']}")
            lines.append("")
        if len(next_actions) > 3:
            lines.append(f"其余 {len(next_actions) - 3} 条既定动作见附录；未由工具重新排列投资优先级。")
            lines.append("")
    else:
        lines.extend(["尚未登记下一步。先由负责人明确要验证的业务问题、动作和停止条件。", ""])
    lines.extend([
        "> 完整研究依据、原始引文和技术状态见附录。新增方向不等于已验证需求，最终投入由负责人决定。",
        "",
    ])
    return {
        "headline": headline,
        "text": "\n".join(lines),
        "next_actions": next_actions,
        "focus_chain_ids": [str(chain.get("id")) for chain in focused[:3]],
    }


def render(
    study: dict[str, Any],
    reasoning: dict[str, Any] | None,
    evidence: dict[str, Any],
    audit_status: str = "not_run",
    baseline: dict[str, Any] | None = None,
    baseline_ref: str = "",
) -> str:
    comparison = compare(reasoning, baseline) if baseline is not None else None
    business = _business_projection(study, reasoning, comparison)
    appendix = _research_appendix(
        study, reasoning, evidence, audit_status,
        baseline=baseline, baseline_ref=baseline_ref,
    )
    return business["text"] + "\n" + appendix
