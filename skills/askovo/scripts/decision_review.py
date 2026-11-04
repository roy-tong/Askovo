"""Decision review: a deterministic quality gate over one study's decision state.

The review does not decide anything and does not generate new business claims.
It reads what already exists — audit verdicts, the seven-node chain, demand
judgments, descriptive analysis and delivered artifacts — and reports whether
the current decision state is verifiable, falsifiable, bias-aware and fresh.

Every item is mechanical: no model call, no score of business success, no
substitute for semantic review or stakeholder sign-off.
"""
from __future__ import annotations

import copy
import hashlib
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
    depth_issues: List[str] = []
    for chain in chains:
        if not isinstance(chain, dict):
            continue
        nodes = chain.get("nodes") if isinstance(chain.get("nodes"), dict) else {}
        feature = nodes.get("feature") if isinstance(nodes.get("feature"), dict) else {}
        capabilities = feature.get("capabilities") if isinstance(feature.get("capabilities"), list) else []
        if not capabilities:
            depth_issues.append(f"{chain.get('id')} 的特性没有逐条说明")
        for name, label in (
            ("scene", "场景"), ("user", "用户"), ("pain", "痛点"), ("need", "需求"),
            ("feature", "特性"), ("product", "产品"), ("business", "商业"),
        ):
            node = nodes.get(name) if isinstance(nodes.get(name), dict) else {}
            if len(str(node.get("rationale") or "").strip()) < 20:
                depth_issues.append(f"{chain.get('id')} 的{label}环节缺少推导理由")
    items.append(_item(
        "evidence", "reasoning_depth",
        "warn" if depth_issues else "pass",
        "；".join(depth_issues) if depth_issues else "七环节均有推导理由，特性已逐条说明",
        "为每条特性写清做什么、为什么能解决、依据是什么" if depth_issues else "",
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


# --------------------------------------------------------------------------- #
# Versioned DecisionRecord history inside the canonical seven-node artifact
# --------------------------------------------------------------------------- #

DECISION_RECORD_KIND = "askovo.decision-record"
DECISION_RECORD_SCHEMA = "1.0"


def _fingerprint(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _canonical(study_dir: Path) -> tuple[Dict[str, Any], Dict[str, Any], Path]:
    study_dir = Path(study_dir).resolve()
    study_path = study_dir / "study.json"
    reasoning_path = study_dir / "04-findings" / "product-reasoning.json"
    if not study_path.is_file():
        raise ValueError(f"missing study.json under {study_dir}")
    if not reasoning_path.is_file():
        raise ValueError("missing 04-findings/product-reasoning.json; run `askovo chain` first")
    study = json.loads(study_path.read_text(encoding="utf-8"))
    reasoning = json.loads(reasoning_path.read_text(encoding="utf-8"))
    if not isinstance(study, dict) or not isinstance(reasoning, dict):
        raise ValueError("study.json and product-reasoning.json must be objects")
    return study, reasoning, reasoning_path


def _one_chain(reasoning: Dict[str, Any], chain_id: str) -> Dict[str, Any]:
    chains = reasoning.get("chains") if isinstance(reasoning.get("chains"), list) else []
    matches = [chain for chain in chains if isinstance(chain, dict) and str(chain.get("id")) == str(chain_id)]
    if not matches:
        raise ValueError(f"unknown chain {chain_id!r}; record a DecisionRecord against an existing seven-node chain")
    return matches[0]


def _chain_evidence_ids(chain: Dict[str, Any]) -> List[str]:
    values: List[str] = []
    nodes = chain.get("nodes") if isinstance(chain.get("nodes"), dict) else {}
    for node_name in sure_engine.REASONING_NODES:
        node = nodes.get(node_name) if isinstance(nodes.get(node_name), dict) else {}
        values.extend(str(item) for item in node.get("evidence_ids") or [])
    values.extend(str(item) for item in chain.get("counter_evidence_ids") or [])
    return list(dict.fromkeys(value for value in values if value))


def _hypothesis_projection(study: Dict[str, Any], hypothesis_id: str = "") -> List[Dict[str, Any]]:
    indexed = [(index, item) for index, item in enumerate(study.get("hypotheses") or []) if isinstance(item, dict)]
    if hypothesis_id:
        indexed = [(index, item) for index, item in indexed if str(item.get("id")) == str(hypothesis_id)]
        if not indexed:
            raise ValueError(f"unknown hypothesis {hypothesis_id!r}; use an id declared in study.json")
    return [{
        "id": item.get("id"),
        "statement": item.get("statement"),
        "falsified_if": item.get("falsified_if"),
        "source_ref": f"study.hypotheses[{index}]",
    } for index, item in indexed]


def _candidate_actions(study: Dict[str, Any], reasoning: Dict[str, Any], chain: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Project existing options/alternatives; do not create another option truth."""
    candidates: List[Dict[str, Any]] = []
    decision = study.get("decision") if isinstance(study.get("decision"), dict) else {}
    for index, option in enumerate(decision.get("options") or []):
        candidates.append({"action": str(option), "chain_id": "", "source_ref": f"study.decision.options[{index}]"})
    for chain_index, item in enumerate(reasoning.get("chains") or []):
        if not isinstance(item, dict):
            continue
        nodes = item.get("nodes") if isinstance(item.get("nodes"), dict) else {}
        business = nodes.get("business") if isinstance(nodes.get("business"), dict) else {}
        gate = business.get("gate") if isinstance(business.get("gate"), dict) else {}
        action = str(gate.get("decision") or business.get("statement") or item.get("title") or "")
        if action:
            candidates.append({
                "action": action,
                "chain_id": str(item.get("id") or ""),
                "source_ref": f"chains[{chain_index}].nodes.business",
            })
        feature = nodes.get("feature") if isinstance(nodes.get("feature"), dict) else {}
        for alt_index, alternative in enumerate(feature.get("alternatives_considered") or []):
            candidates.append({
                "action": str(alternative),
                "chain_id": str(item.get("id") or ""),
                "source_ref": f"chains[{chain_index}].nodes.feature.alternatives_considered[{alt_index}]",
            })
    unique: List[Dict[str, Any]] = []
    seen: set = set()
    for item in candidates:
        key = (item["chain_id"], item["action"])
        if not item["action"] or key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _registered_evidence_ids(study_dir: Path) -> set:
    path = Path(study_dir).resolve() / "02-data" / "evidence.jsonl"
    known: set = set()
    if not path.is_file():
        return known
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and item.get("record_id"):
            known.add(str(item["record_id"]))
    return known


def record_decision(
    study_dir: Path,
    *,
    chain_id: str,
    by: str,
    decision: str = "",
    hypothesis_id: str = "",
    observations: Any = (),
    evidence_ids: Any = (),
    revision: str = "",
    next_action: str = "",
) -> Dict[str, Any]:
    """Append an immutable historical projection without changing chain status.

    The current seven-node chain remains the only live product/business truth.
    Snapshots exist solely to replay what the named decision-maker saw at each
    version; observations never upgrade a node or a demand judgment.
    """
    operator = str(by or "").strip()
    if not operator:
        raise ValueError("decision record requires a named decision-maker via --by")
    study_dir = Path(study_dir).resolve()
    study, reasoning, reasoning_path = _canonical(study_dir)
    chain = _one_chain(reasoning, chain_id)
    records = reasoning.setdefault("decision_records", [])
    if not isinstance(records, list):
        raise ValueError("product-reasoning.json decision_records must be an array")
    previous = [item for item in records if isinstance(item, dict) and str(item.get("chain_id")) == str(chain_id)]
    previous.sort(key=lambda item: int(item.get("version") or 0))
    version = int(previous[-1].get("version") or 0) + 1 if previous else 1
    current_hypotheses = _hypothesis_projection(study, hypothesis_id)
    original = copy.deepcopy(previous[0].get("original_hypothesis")) if previous else copy.deepcopy(current_hypotheses)
    refs = [str(item).strip() for item in (evidence_ids or []) if str(item).strip()]
    unknown = sorted(set(refs) - _registered_evidence_ids(study_dir))
    if unknown:
        raise ValueError("observation evidence is not registered in 02-data/evidence.jsonl: " + ", ".join(unknown))
    observation_entries = [{
        "text": str(item).strip(),
        "evidence_ids": refs,
        "status": "recorded_observation_not_an_evidence_upgrade",
    } for item in (observations or []) if str(item).strip()]
    nodes = chain.get("nodes") if isinstance(chain.get("nodes"), dict) else {}
    business = nodes.get("business") if isinstance(nodes.get("business"), dict) else {}
    gate = business.get("gate") if isinstance(business.get("gate"), dict) else {}
    prioritization = chain.get("prioritization") if isinstance(chain.get("prioritization"), dict) else {}
    study_decision = study.get("decision") if isinstance(study.get("decision"), dict) else {}
    record_id = f"DR-{chain_id}-{version:03d}"
    record = {
        "kind": DECISION_RECORD_KIND,
        "schema_version": DECISION_RECORD_SCHEMA,
        "record_id": record_id,
        "chain_id": str(chain_id),
        "version": version,
        "parent_version": version - 1 if version > 1 else None,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "decision_maker": operator,
        "accountable_owner": str(
            prioritization.get("owner") or gate.get("owner") or study_decision.get("owner") or ""
        ),
        "decision": str(decision or gate.get("decision") or chain.get("status") or ""),
        "original_hypothesis": original or [],
        "hypotheses_at_version": current_hypotheses,
        "candidate_actions": _candidate_actions(study, reasoning, chain),
        "basis": {
            "canonical_chain_ref": f"chains[id={chain_id}]",
            "demand_judgment_id": chain.get("demand_judgment_id"),
            "context_key": chain.get("context_key"),
            "node_refs": [f"{chain_id}.{name}" for name in sure_engine.REASONING_NODES if name in nodes],
            "evidence_ids": _chain_evidence_ids(chain),
            "prioritization": copy.deepcopy(prioritization),
        },
        "observations": observation_entries,
        "observed_supporting_states": copy.deepcopy(chain.get("supporting_states") or {}),
        "revision": {
            "note": str(revision or ""),
            "parent_record_id": previous[-1].get("record_id") if previous else None,
            "change_log": copy.deepcopy(chain.get("change_log") or []),
        },
        "next_action": str(next_action or chain.get("next_test") or ""),
        "chain_fingerprint": _fingerprint(chain),
        "chain_snapshot": copy.deepcopy(chain),
        "boundary": (
            "Immutable replay projection of the canonical chain. Recording a decision or observation "
            "does not validate a node/judgment, establish causality, or imply release/commercial readiness."
        ),
    }
    records.append(record)
    reasoning_path.write_text(json.dumps(reasoning, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "status": "recorded",
        "record": record,
        "canonical_artifact": str(reasoning_path),
        "chain_status_unchanged": chain.get("status"),
        "replay_command": f"askovo decision replay {study_dir} --record-id {record_id} --json",
    }


def list_decision_records(study_dir: Path, *, chain_id: str = "") -> Dict[str, Any]:
    _, reasoning, path = _canonical(Path(study_dir))
    records = [item for item in reasoning.get("decision_records") or [] if isinstance(item, dict)]
    if chain_id:
        records = [item for item in records if str(item.get("chain_id")) == str(chain_id)]
    records.sort(key=lambda item: (str(item.get("chain_id")), int(item.get("version") or 0)))
    return {
        "kind": "askovo.decision-record-list",
        "canonical_artifact": str(path),
        "count": len(records),
        "records": [{key: item.get(key) for key in (
            "record_id", "chain_id", "version", "parent_version", "recorded_at",
            "decision_maker", "decision", "next_action", "chain_fingerprint",
        )} for item in records],
        "boundary": "Record metadata only; replay reads the historical chain snapshots in the same canonical artifact.",
    }


def _record_changes(previous: Optional[Dict[str, Any]], current: Dict[str, Any]) -> Dict[str, Any]:
    if previous is None:
        return {"type": "initial", "node_changes": []}
    before = previous.get("chain_snapshot") if isinstance(previous.get("chain_snapshot"), dict) else {}
    after = current.get("chain_snapshot") if isinstance(current.get("chain_snapshot"), dict) else {}
    before_nodes = before.get("nodes") if isinstance(before.get("nodes"), dict) else {}
    after_nodes = after.get("nodes") if isinstance(after.get("nodes"), dict) else {}
    node_changes: List[Dict[str, Any]] = []
    for name in sure_engine.REASONING_NODES:
        old = before_nodes.get(name) if isinstance(before_nodes.get(name), dict) else {}
        new = after_nodes.get(name) if isinstance(after_nodes.get(name), dict) else {}
        if _fingerprint(old) == _fingerprint(new):
            continue
        node_changes.append({
            "node": name,
            "before": {key: old.get(key) for key in ("statement", "rationale", "status", "evidence_ids")},
            "after": {key: new.get(key) for key in ("statement", "rationale", "status", "evidence_ids")},
        })
    old_evidence = set((previous.get("basis") or {}).get("evidence_ids") or [])
    new_evidence = set((current.get("basis") or {}).get("evidence_ids") or [])
    return {
        "type": "revision",
        "decision_before": previous.get("decision"),
        "decision_after": current.get("decision"),
        "next_action_before": previous.get("next_action"),
        "next_action_after": current.get("next_action"),
        "evidence_added": sorted(new_evidence - old_evidence),
        "evidence_removed": sorted(old_evidence - new_evidence),
        "node_changes": node_changes,
    }


def replay_decision(
    study_dir: Path,
    *,
    chain_id: str = "",
    record_id: str = "",
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """Replay original hypotheses, options, basis, observations and revisions."""
    study, reasoning, path = _canonical(Path(study_dir))
    records = [item for item in reasoning.get("decision_records") or [] if isinstance(item, dict)]
    if chain_id:
        records = [item for item in records if str(item.get("chain_id")) == str(chain_id)]
    if record_id:
        records = [item for item in records if str(item.get("record_id")) == str(record_id)]
    if version is not None:
        records = [item for item in records if int(item.get("version") or 0) == int(version)]
    records.sort(key=lambda item: (str(item.get("chain_id")), int(item.get("version") or 0)))
    if (chain_id or record_id or version is not None) and not records:
        raise ValueError("no DecisionRecord matched the requested chain/id/version")
    timeline: List[Dict[str, Any]] = []
    previous_by_chain: Dict[str, Dict[str, Any]] = {}
    for item in records:
        projected = copy.deepcopy(item)
        projected["changes_from_previous"] = _record_changes(previous_by_chain.get(str(item.get("chain_id"))), item)
        timeline.append(projected)
        previous_by_chain[str(item.get("chain_id"))] = item
    current_drift: List[Dict[str, Any]] = []
    for current_chain_id, latest in previous_by_chain.items():
        current = _one_chain(reasoning, current_chain_id)
        current_drift.append({
            "chain_id": current_chain_id,
            "record_id": latest.get("record_id"),
            "changed_since_record": _fingerprint(current) != latest.get("chain_fingerprint"),
            "current_chain_fingerprint": _fingerprint(current),
            "recorded_chain_fingerprint": latest.get("chain_fingerprint"),
            "current_status": current.get("status"),
            "current_next_action": current.get("next_test"),
        })
    payload = {
        "kind": "askovo.decision-replay",
        "schema_version": DECISION_RECORD_SCHEMA,
        "study_id": study.get("study_id"),
        "canonical_artifact": str(path),
        "status": "replayed" if timeline else "empty",
        "count": len(timeline),
        "timeline": timeline,
        "current_drift": current_drift,
        "boundary": (
            "Replay shows historical projections, not a second live truth. Current semantics remain in chains[]; "
            "observations and decided records never auto-validate text, prove causality or imply release readiness."
        ),
    }
    payload["markdown"] = render_decision_replay(payload)
    return payload


def render_decision_replay(payload: Dict[str, Any]) -> str:
    lines = [
        f"# 决策回放：{payload.get('study_id') or '未命名研究'}",
        "",
        f"- Canonical artifact：`{payload.get('canonical_artifact')}`",
        f"- 版本数：{payload.get('count', 0)}；历史记录不是第二套当前真相。",
        "",
    ]
    if not payload.get("timeline"):
        lines.append("尚无 DecisionRecord；先运行 `askovo decision record STUDY --chain PR01 --by NAME`。")
    for item in payload.get("timeline") or []:
        lines.extend([
            f"## {item.get('record_id')} · v{item.get('version')} · {item.get('chain_id')}",
            "",
            f"- 决策人：{item.get('decision_maker')}；负责人：{item.get('accountable_owner') or '未记录'}",
            f"- 决定：{item.get('decision') or '未记录'}",
            f"- 下一动作：{item.get('next_action') or '未记录'}",
            "- 原假设：",
        ])
        hypotheses = item.get("original_hypothesis") or []
        lines.extend(
            f"  - {entry.get('id')}：{entry.get('statement')}；证伪：{entry.get('falsified_if')}"
            for entry in hypotheses
        ) if hypotheses else lines.append("  - 未登记")
        lines.append("- 候选动作：")
        candidates = item.get("candidate_actions") or []
        lines.extend(
            f"  - {entry.get('action')}（{entry.get('source_ref')}）" for entry in candidates
        ) if candidates else lines.append("  - 未登记")
        basis = item.get("basis") if isinstance(item.get("basis"), dict) else {}
        lines.append(
            f"- 依据：{basis.get('canonical_chain_ref')}；需求判断 `{basis.get('demand_judgment_id') or '未关联'}`；"
            f"证据 {', '.join(basis.get('evidence_ids') or []) or '未登记'}"
        )
        lines.append("- 观察：")
        observations = item.get("observations") or []
        lines.extend(
            f"  - {entry.get('text')}（证据：{', '.join(entry.get('evidence_ids') or []) or '无'}；不自动升级）"
            for entry in observations
        ) if observations else lines.append("  - 本版本无新增观察；支撑三态见记录 observed_supporting_states")
        revision = item.get("revision") if isinstance(item.get("revision"), dict) else {}
        lines.append(
            f"- 修订：{revision.get('note') or '无新增说明'}；"
            f"关联 change_log {len(revision.get('change_log') or [])} 条"
        )
        changes = item.get("changes_from_previous") if isinstance(item.get("changes_from_previous"), dict) else {}
        lines.append(
            f"- 与上一版：{changes.get('type')}；节点变化 {len(changes.get('node_changes') or [])}；"
            f"证据新增 {', '.join(changes.get('evidence_added') or []) or '无'}；"
            f"证据移除 {', '.join(changes.get('evidence_removed') or []) or '无'}"
        )
        lines.append("")
    if payload.get("current_drift"):
        lines.extend(["## 与当前七节点链的差异", ""])
        for drift in payload["current_drift"]:
            lines.append(
                f"- {drift.get('chain_id')}：{'已变化' if drift.get('changed_since_record') else '未变化'}；"
                f"当前状态 `{drift.get('current_status')}`；当前下一动作：{drift.get('current_next_action')}"
            )
        lines.append("")
    lines.extend(["## 边界", "", str(payload.get("boundary") or ""), ""])
    return "\n".join(lines)


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
