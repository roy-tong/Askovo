#!/usr/bin/env python3
"""Read-only single-judgment evidence page for an Askovo study.

The page is an L0 projection of ``04-findings/product-reasoning.json`` plus the
evidence, demand judgment, decision review and decision snapshots it points at.
It never edits canonical artifacts, registers evidence, approves a decision,
re-runs a test or contacts the network. Commands shown on the page are for a
human to copy; the page itself executes nothing.
"""

from __future__ import annotations

import html
import json
import shlex
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import decision_brief
import decision_review
import research_delta
import sure_engine

SCHEMA = "askovo.evidence-page/1"
GENERATOR = "skills.askovo.scripts.evidence_page"
GENERATOR_VERSION = "1"
STUDY_REF = "study.json"
CANONICAL_REF = decision_brief.CANONICAL_REF
JUDGMENTS_REF = "04-findings/demand-judgments.json"
EVIDENCE_REF = "02-data/evidence.jsonl"
REVIEW_REF = decision_brief.REVIEW_REF
SNAPSHOT_REF = research_delta.DELTAS_RELATIVE / research_delta.DECISION_SNAPSHOTS_SUBDIR

BOUNDARY = (
    "本页是 04-findings/product-reasoning.json 及所引证据的 L0 只读投影："
    "不重写主链、不登记证据、不批准决定、不重跑测试、不发送任何外部动作。"
    "页面上的命令仅供人工复制执行。反证与 needs_re_review 是复核信号，不是自动裁决。"
)

_STATE_ORDER = ("failed", "empty", "stale", "partial", "review_required", "ready")
_STATE_LABELS = {
    "ready": "可读",
    "review_required": "需要重审",
    "partial": "部分字段/引用缺失",
    "stale": "已过期",
    "empty": "空",
    "failed": "失败",
}
_STATE_TONES = {
    "ready": "ok",
    "review_required": "warn",
    "partial": "warn",
    "stale": "bad",
    "empty": "muted",
    "failed": "bad",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _as_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _read_json(path: Path) -> Tuple[Any, str, str]:
    """Return (payload, status, detail) with status in ok/missing/error."""
    if not path.is_file():
        return None, "missing", f"缺少 {path.name}"
    try:
        return json.loads(path.read_text(encoding="utf-8")), "ok", ""
    except (OSError, json.JSONDecodeError) as exc:
        return None, "error", f"{path.name} 无法读取：{type(exc).__name__}: {exc}"


def _read_evidence(path: Path) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    records: Dict[str, Dict[str, Any]] = {}
    faults: List[Dict[str, Any]] = []
    if not path.is_file():
        return records, faults
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return records, [{
            "code": "SOURCE_UNREADABLE",
            "detail": f"{path.name} 无法读取：{type(exc).__name__}: {exc}",
        }]
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            faults.append({
                "code": "SOURCE_UNREADABLE",
                "detail": f"{path.name} 第 {number} 行不是合法 JSON：{exc}",
            })
            continue
        if not isinstance(item, dict) or not item.get("record_id"):
            faults.append({
                "code": "FIELD_UNREGISTERED",
                "detail": f"{path.name} 第 {number} 行缺少 record_id，未计入证据",
            })
            continue
        records[str(item["record_id"])] = item
    return records, faults


_STATE_BY_CODE = {
    "FAILED": "failed",
    "EMPTY": "empty",
    "STALE": "stale",
    "INPUT_DRIFT": "stale",
    "BROKEN_REFERENCE": "stale",
    "PARTIAL": "partial",
    "MISSING_LINK": "partial",
    "EVIDENCE_UNQUALIFIED": "partial",
    "FIELD_UNREGISTERED": "partial",
    "SOURCE_UNREADABLE": "partial",
    "REVIEW_REQUIRED": "review_required",
}


def _state(page_states: List[Dict[str, str]]) -> str:
    mapped = {_STATE_BY_CODE.get(item["code"], item["code"]) for item in page_states}
    for candidate in _STATE_ORDER:
        if candidate in mapped:
            return candidate
    return "ready"


def _add_state(states: List[Dict[str, str]], code: str, detail: str = "",
               detail_code: str = "") -> None:
    item = {"code": code, "detail": detail}
    if detail_code:
        item["detail_code"] = detail_code
    states.append(item)


def _node_label(node_id: str) -> str:
    return sure_engine.REASONING_NODE_LABELS.get(node_id, node_id)


def _pick_judgment(judgments: List[Dict[str, Any]], judgment_id: str) -> Optional[Dict[str, Any]]:
    if not judgment_id:
        return None
    for judgment in judgments:
        if _text(judgment.get("id")) == judgment_id:
            return judgment
    return None


def _pick_hypotheses(study: Dict[str, Any], chain: Dict[str, Any]) -> List[Dict[str, Any]]:
    hypotheses = [item for item in study.get("hypotheses") or [] if isinstance(item, dict)]
    registered = [str(value) for value in chain.get("hypothesis_ids") or []]
    if registered:
        return [{"id": _text(item.get("id")), "statement": _text(item.get("statement")),
                 "falsified_if": _text(item.get("falsified_if")),
                 "link_basis": "chain.hypothesis_ids"}
                for item in hypotheses if _text(item.get("id")) in registered]
    return [{"id": _text(item.get("id")), "statement": _text(item.get("statement")),
             "falsified_if": _text(item.get("falsified_if")),
             "link_basis": "study.hypotheses（主链未登记 hypothesis_ids）"}
            for item in hypotheses]


def _evidence_entry(record_id: str, records: Dict[str, Dict[str, Any]],
                    *, registered_as: str, chain_context: str) -> Dict[str, Any]:
    record = records.get(record_id)
    if record is None:
        return {
            "record_id": record_id,
            "exists": False,
            "qualified": False,
            "registered_as": registered_as,
            "context_key": "",
            "context_matches_chain": None,
        }
    context_key = _text(record.get("context_key"))
    return {
        "record_id": record_id,
        "exists": True,
        "qualified": sure_engine.is_qualified_evidence(record),
        "registered_as": registered_as,
        "user_role": _text(record.get("user_role")),
        "scene_trigger": _text(record.get("scene_trigger")),
        "task_outcome": _text(record.get("task_outcome")),
        "current_substitute": _text(record.get("current_substitute")),
        "friction_cost": _text(record.get("friction_cost")),
        "consequence": _text(record.get("consequence")),
        "evidence_level": _text(record.get("evidence_level")),
        "evidence_basis": _text(record.get("evidence_basis")),
        "corpus_role": _text(record.get("corpus_role")),
        "source_family": _text(record.get("source_family")),
        "source_ref": _text(record.get("source_ref")),
        "context_key": context_key,
        "context_matches_chain": (context_key == chain_context) if chain_context else None,
    }


def _snapshots(study_dir: Path, states: List[Dict[str, str]],
               faults: List[Dict[str, Any]]) -> Dict[str, Any]:
    directory = study_dir / SNAPSHOT_REF
    items: List[Dict[str, Any]] = []
    if not directory.is_dir():
        return {"directory": str(SNAPSHOT_REF), "available": False, "items": items}
    for path in sorted(directory.glob("*.json")):
        payload, status, detail = _read_json(path)
        if status != "ok" or not isinstance(payload, dict):
            faults.append({"code": "SOURCE_UNREADABLE",
                           "detail": f"{path.name}：{detail or '内容不是对象'}"})
            _add_state(states, "SOURCE_UNREADABLE", f"决定快照 {path.name} 不可读",
                       "SOURCE_UNREADABLE")
            continue
        items.append({
            "decision_id": _text(payload.get("decision_id")) or path.stem,
            "approved_at": _text(payload.get("approved_at")),
            "approved_by": _text(payload.get("approved_by")),
            "chosen_option": _text(payload.get("chosen_option")),
            "version": _text(payload.get("version")),
            "needs_re_review_at_approval": payload.get("needs_re_review_at_approval"),
            "current_review_status": _text(payload.get("current_review_status")),
            "approval_ref": _text(payload.get("approval_ref")),
            "supersedes": _text(payload.get("supersedes")),
            "identity_basis": _text(payload.get("identity_basis")),
            "path": str(path),
        })
    return {"directory": str(SNAPSHOT_REF), "available": True, "items": items}


def _all_decision_records(study_dir: Path) -> List[Dict[str, Any]]:
    """Read DecisionRecords for chain selection; unreadable records select nothing."""
    try:
        payload = decision_review.list_decision_records(study_dir)
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    records = payload.get("records") if isinstance(payload, dict) else None
    return [item for item in records if isinstance(item, dict)] \
        if isinstance(records, list) else []


def _decision_records(study_dir: Path, chain_id: str,
                      states: List[Dict[str, str]]) -> Dict[str, Any]:
    try:
        payload = decision_review.list_decision_records(study_dir, chain_id=chain_id)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"available": False, "count": None, "records": [],
                "detail": f"{type(exc).__name__}: {exc}"}
    records = payload.get("records") if isinstance(payload, dict) else None
    return {
        "available": True,
        "count": len(records) if isinstance(records, list) else None,
        "records": records if isinstance(records, list) else [],
    }


def _commands(study_dir: Path, chain_id: str, node_id: str) -> List[str]:
    root = shlex.quote(str(study_dir))
    chain = shlex.quote(chain_id) if chain_id else "<CHAIN_ID>"
    return [
        f"askovo page {root} --chain {chain} --node {node_id} --html evidence-page.html",
        f"askovo brief {root} --chain {chain} --format md",
        f"askovo delta status {root}",
        f"askovo deliver {root} --kind web",
    ]


def build_evidence_page(study_dir: Path, chain_id: str = "", node_id: str = "",
                        *, now: Optional[str] = None) -> Dict[str, Any]:
    """Project one chain node into a read-only evidence page."""
    study_dir = Path(study_dir).resolve()
    requested_chain = _text(chain_id)
    requested_node = _text(node_id) or "scene"

    states: List[Dict[str, str]] = []
    faults: List[Dict[str, Any]] = []
    notes: List[str] = []
    warnings: List[str] = []
    missing: List[str] = []

    study, study_status, study_detail = _read_json(study_dir / STUDY_REF)
    if study_status == "missing":
        _add_state(states, "FAILED", study_detail, "SOURCE_UNREADABLE")
        study = {}
    elif study_status == "error" or not isinstance(study, dict):
        _add_state(states, "FAILED", study_detail, "SOURCE_UNREADABLE")
        study = {}

    reasoning, reasoning_status, reasoning_detail = _read_json(study_dir / CANONICAL_REF)
    if reasoning_status == "missing":
        _add_state(states, "EMPTY", f"缺少主链 {CANONICAL_REF}；页面没有可投影的判断",
                   "EMPTY")
        reasoning = {}
    elif reasoning_status == "error" or not isinstance(reasoning, dict):
        _add_state(states, "FAILED", reasoning_detail, "SOURCE_UNREADABLE")
        reasoning = {}

    chains = [item for item in reasoning.get("chains") or [] if isinstance(item, dict)]
    chain, chain_source = decision_review.select_chain(
        chains, chain_id=requested_chain, records=_all_decision_records(study_dir))
    if chain is None and reasoning:
        if chain_source == "missing":
            available = ", ".join(_text(item.get("id")) for item in chains) or "无"
            _add_state(states, "EMPTY",
                       f"主链 {requested_chain!r} 不存在；当前可读主链：{available}", "EMPTY")
        elif not chains:
            _add_state(states, "EMPTY", "canonical 主链里没有 chains 记录", "EMPTY")
        elif chain_source == "missing_decision":
            _add_state(states, "STALE",
                       "最新 DecisionRecord 指向的主链不在 canonical 主链里；"
                       "页面不默认回退到第一条链，请核对 DecisionRecord 或显式 --chain",
                       "BROKEN_REFERENCE")
        else:
            _add_state(states, "EMPTY",
                       f"canonical 主链含 {len(chains)} 条候选链且没有 DecisionRecord 选中；"
                       "页面不默认展开第一条，请用 --chain 显式选择", "EMPTY")

    chain_id_value = _text(chain.get("id")) if chain else requested_chain
    chain_context = _text(chain.get("context_key")) if chain else ""

    records, evidence_faults = _read_evidence(study_dir / EVIDENCE_REF)
    faults.extend(evidence_faults)
    for fault in evidence_faults:
        if fault["code"] == "SOURCE_UNREADABLE":
            _add_state(states, "SOURCE_UNREADABLE", fault["detail"], "SOURCE_UNREADABLE")

    judgments, judgments_status, judgments_detail = _read_json(study_dir / JUDGMENTS_REF)
    if judgments_status == "error" or (judgments is not None and not isinstance(judgments, list)):
        _add_state(states, "SOURCE_UNREADABLE", judgments_detail or "需求判断不是列表",
                   "SOURCE_UNREADABLE")
        judgments = []
    elif judgments_status == "missing":
        judgments = []
        notes.append(f"未登记 {JUDGMENTS_REF}；页面不推断关联的需求判断。")
    judgment = _pick_judgment(judgments, _text(chain.get("demand_judgment_id")) if chain else "")
    if chain and _text(chain.get("demand_judgment_id")) and judgment is None:
        _add_state(states, "PARTIAL",
                   f"主链关联的需求判断 {chain.get('demand_judgment_id')} 未登记", "MISSING_LINK")

    review, review_status, review_detail = _read_json(study_dir / REVIEW_REF)
    if review_status == "error":
        _add_state(states, "SOURCE_UNREADABLE", review_detail, "SOURCE_UNREADABLE")
        review = None
    elif review_status == "missing":
        notes.append(f"未登记 {REVIEW_REF}；页面不把未复核当作已复核。")
    fingerprints: Dict[str, str] = {}
    if isinstance(review, dict):
        raw = ((review.get("input_fingerprints") or {}).get("evidence") or {})
        if isinstance(raw, dict):
            fingerprints = {str(key): str(value) for key, value in raw.items()}

    node_raw: Dict[str, Any] = {}
    node_valid = requested_node in sure_engine.REASONING_NODES
    if not node_valid:
        _add_state(states, "FIELD_UNREGISTERED",
                   f"未知节点 {requested_node!r}；可用节点：" +
                   ", ".join(sure_engine.REASONING_NODES), "FIELD_UNREGISTERED")
    elif chain is not None:
        nodes = chain.get("nodes") if isinstance(chain.get("nodes"), dict) else {}
        candidate = nodes.get(requested_node)
        if isinstance(candidate, dict):
            node_raw = candidate
        else:
            _add_state(states, "EMPTY",
                       f"主链 {chain_id_value} 没有登记节点 {requested_node}", "EMPTY")

    support_ids = _as_list(node_raw.get("evidence_ids"))
    supporting = [_evidence_entry(record_id, records, registered_as="node.evidence_ids",
                                  chain_context=chain_context)
                  for record_id in support_ids]

    judgment_counter_ids = _as_list(judgment.get("counter_evidence_ids")) if judgment else []
    chain_counter_ids = _as_list(chain.get("counter_evidence_ids")) if chain else []
    counter_ids: List[str] = []
    for record_id in chain_counter_ids + judgment_counter_ids:
        if record_id not in counter_ids:
            counter_ids.append(record_id)
    counter = []
    for record_id in counter_ids:
        entry = _evidence_entry(record_id, records, registered_as="counter_evidence",
                                chain_context=chain_context)
        entry["registered_on_chain"] = record_id in chain_counter_ids
        entry["registered_in_judgment"] = record_id in judgment_counter_ids
        entry["overlaps_with_supporting"] = record_id in support_ids
        counter.append(entry)

    for entry in supporting + counter:
        if not entry.get("exists") or entry.get("qualified"):
            continue
        record_id = entry["record_id"]
        detail = (f"{record_id} 未通过证据资格门"
                  f"（evidence_level={entry.get('evidence_level') or '未登记'}，"
                  "不在 E0–E5 登记范围）；不作为合格支撑/反证证据")
        _add_state(states, "EVIDENCE_UNQUALIFIED", detail, "EVIDENCE_UNQUALIFIED")
        faults.append({"code": "EVIDENCE_UNQUALIFIED", "record_id": record_id,
                       "detail": detail})

    if node_raw:
        if not _text(node_raw.get("statement")):
            _add_state(states, "FIELD_UNREGISTERED", f"{requested_node}.statement 未登记",
                       "FIELD_UNREGISTERED")
            missing.append(f"{requested_node}.statement")
        if not _text(node_raw.get("rationale")):
            _add_state(states, "PARTIAL", f"{requested_node}.rationale 未登记（推理边不完整）",
                       "FIELD_UNREGISTERED")
            missing.append(f"{requested_node}.rationale")

    missing_refs = [entry["record_id"] for entry in supporting + counter if not entry["exists"]]
    for record_id in missing_refs:
        missing.append(record_id)
    mismatched = [entry["record_id"] for entry in supporting + counter
                  if entry.get("context_matches_chain") is False]
    if mismatched:
        warnings.append("以下证据的 context_key 与主链不一致：" + ", ".join(mismatched))

    stale: List[Dict[str, Any]] = []
    if chain is not None:
        stale = decision_brief.stale_reasons(
            study_dir, [chain], [item for item in judgments if isinstance(item, dict)],
            set(records), previous_fingerprints=fingerprints)
    for reason in stale:
        code = _text(reason.get("detail_code")) or "STALE"
        _add_state(states, "STALE", _text(reason.get("detail")) or code, code)

    signal = decision_brief.review_signal(chain) if chain else {
        "needs_re_review": False, "counter_evidence_ids": [], "reasons": []}
    if signal["needs_re_review"]:
        _add_state(states, "REVIEW_REQUIRED",
                   "已登记反证：" + ", ".join(signal["counter_evidence_ids"]), "REVIEW_REQUIRED")

    supporting_states = chain.get("supporting_states") if chain else {}
    if not isinstance(supporting_states, dict):
        supporting_states = {}

    decision = None
    if chain is not None:
        study_decision = study.get("decision") if isinstance(study.get("decision"), dict) else {}
        decision = {
            "question": _text(study_decision.get("question")),
            "owner": _text(study_decision.get("owner")),
            "deadline": _text(study_decision.get("deadline")),
            "options": _as_list(study_decision.get("options")),
            "minimum_evidence": _as_list(study_decision.get("minimum_evidence")),
            "chain_status": _text(chain.get("status")),
            "confidence": _text(chain.get("confidence")),
            "supporting_states": {
                "delivery": supporting_states.get("delivery") or {},
                "outcome": supporting_states.get("outcome") or {},
                "causal": supporting_states.get("causal") or {},
            },
            "human_review": chain.get("human_review") if isinstance(
                chain.get("human_review"), dict) else {},
            "needs_re_review": bool(signal["needs_re_review"]),
            "counter_evidence_ids": list(signal["counter_evidence_ids"]),
            "review_reasons": list(signal["reasons"]),
        }

    node = None
    if node_raw:
        node = {
            "id": requested_node,
            "label": _node_label(requested_node),
            "position": (sure_engine.REASONING_NODES.index(requested_node) + 1),
            "status": _text(node_raw.get("status")),
            "statement": _text(node_raw.get("statement")),
            "rationale": _text(node_raw.get("rationale")),
            "assumptions": _as_list(node_raw.get("assumptions")),
            "fields": {str(key): value for key, value in node_raw.items()
                       if key not in ("statement", "rationale", "status", "evidence_ids",
                                      "assumptions")},
            "evidence_ids": support_ids,
        }

    navigation_nodes = []
    node_map = {}
    if chain is not None:
        raw_nodes = chain.get("nodes") if isinstance(chain.get("nodes"), dict) else {}
        node_map = {name: raw_nodes.get(name) if isinstance(raw_nodes.get(name), dict) else {}
                    for name in sure_engine.REASONING_NODES}
    for name in sure_engine.REASONING_NODES:
        raw = node_map.get(name) or {}
        evidence_ids = _as_list(raw.get("evidence_ids"))
        navigation_nodes.append({
            "id": name,
            "label": _node_label(name),
            "status": _text(raw.get("status")),
            "statement": _text(raw.get("statement")),
            "evidence_count": len(evidence_ids) if raw else None,
            "evidence_ids": evidence_ids,
            "current": name == requested_node,
        })

    navigation = {
        "nodes": navigation_nodes,
        "current": requested_node,
        "position": (f"{sure_engine.REASONING_NODES.index(requested_node) + 1}/"
                     f"{len(sure_engine.REASONING_NODES)}") if node_valid else "",
    }

    gaps = {
        "chain": _as_list(chain.get("gaps")) if chain else [],
        "judgment": _as_list(judgment.get("gaps")) if judgment else [],
        "assumptions": _as_list(node_raw.get("assumptions")),
        "missing_references": missing_refs,
        "stale": [{"detail_code": _text(item.get("detail_code")),
                   "detail": _text(item.get("detail"))} for item in stale],
    }

    falsification = {
        "chain_next_test": _text(chain.get("next_test")) if chain else "",
        "judgment_next_test": _text(judgment.get("next_test")) if judgment else "",
        "hypotheses": _pick_hypotheses(study, chain) if chain else [],
    }

    change_log = []
    for entry in (chain.get("change_log") or []) if chain else []:
        if not isinstance(entry, dict):
            continue
        change_log.append({
            "id": _text(entry.get("id")),
            "base_version": _text(entry.get("base_version")),
            "new_version": _text(entry.get("new_version")),
            "reason_evidence_ids": _as_list(entry.get("reason_evidence_ids")),
            "affected_refs": _as_list(entry.get("affected_refs")),
            "impact": _text(entry.get("impact")),
            "decision": _text(entry.get("decision")),
            "owner": _text(entry.get("owner")),
            "decided_at": _text(entry.get("decided_at")),
            "projection_sync": _text(entry.get("projection_sync")),
        })

    snapshots = _snapshots(study_dir, states, faults)
    decision_records = _decision_records(study_dir, chain_id_value, states) if chain else {
        "available": False, "count": None, "records": [],
        "detail": "没有可读主链，未读取决策记录"}

    sources = []
    for ref in (STUDY_REF, CANONICAL_REF, JUDGMENTS_REF, EVIDENCE_REF, REVIEW_REF):
        path = study_dir / ref
        if not path.exists():
            status = "未登记"
        elif not path.is_file():
            status = "不是文件"
        else:
            status = "已读取"
        sources.append({"ref": ref, "path": str(path), "status": status})
    sources.append({"ref": str(SNAPSHOT_REF), "path": str(study_dir / SNAPSHOT_REF),
                    "status": "已读取" if (study_dir / SNAPSHOT_REF).is_dir() else "未登记"})

    page: Dict[str, Any] = {
        "schema": SCHEMA,
        "generator": GENERATOR,
        "generator_version": GENERATOR_VERSION,
        "generated_at": _text(now) or _now(),
        "read_only": True,
        "boundary": BOUNDARY,
        "study": {
            "study_id": _text(study.get("study_id")),
            "title": _text(study.get("title")),
        },
        "chain": {
            "id": chain_id_value,
            "title": _text(chain.get("title")) if chain else "",
            "context_key": chain_context,
            "status": _text(chain.get("status")) if chain else "",
            "confidence": _text(chain.get("confidence")) if chain else "",
            "demand_judgment_id": _text(chain.get("demand_judgment_id")) if chain else "",
            "selection": chain_source,
        },
        "node": node,
        "navigation": navigation,
        "decision": decision,
        "supporting": supporting,
        "counter": counter,
        "reasoning": {
            "statement": _text(node_raw.get("statement")),
            "rationale": _text(node_raw.get("rationale")),
            "assumptions": _as_list(node_raw.get("assumptions")),
            "alternatives": _as_list(chain.get("alternative_explanations")) if chain else [],
            "upstream": None,
            "downstream": None,
        },
        "judgment": {
            "id": _text(judgment.get("id")) if judgment else "",
            "title": _text(judgment.get("title")) if judgment else "",
            "status": _text(judgment.get("status")) if judgment else "",
            "confidence": _text(judgment.get("confidence")) if judgment else "",
            "counter_evidence_ids": judgment_counter_ids,
            "problem_evidence_ids": _as_list(judgment.get("problem_evidence_ids")) if judgment else [],
            "solution_evidence_ids": _as_list(judgment.get("solution_evidence_ids")) if judgment else [],
            "commercial_evidence_ids": _as_list(judgment.get("commercial_evidence_ids")) if judgment else [],
        },
        "gaps": gaps,
        "falsification": falsification,
        "change_log": change_log,
        "snapshots": snapshots,
        "decision_records": decision_records,
        "review": {
            "registered": isinstance(review, dict),
            "path": REVIEW_REF,
            "reviewed_at": _text(review.get("reviewed_at")) if isinstance(review, dict) else "",
            "reviewer": _text(review.get("reviewer")) if isinstance(review, dict) else "",
        },
        "sources": sources,
        "warnings": warnings,
        "faults": faults,
        "missing": missing,
        "notes": notes,
        "commands": _commands(study_dir, chain_id_value, requested_node),
    }

    position = sure_engine.REASONING_NODES.index(requested_node) if node_valid else -1
    if 0 < position:
        previous_id = sure_engine.REASONING_NODES[position - 1]
        previous = (chain.get("nodes") or {}).get(previous_id) if chain else {}
        page["reasoning"]["upstream"] = {
            "id": previous_id, "label": _node_label(previous_id),
            "status": _text((previous or {}).get("status")),
            "statement": _text((previous or {}).get("statement")),
        }
    if 0 <= position < len(sure_engine.REASONING_NODES) - 1:
        next_id = sure_engine.REASONING_NODES[position + 1]
        following = (chain.get("nodes") or {}).get(next_id) if chain else {}
        page["reasoning"]["downstream"] = {
            "id": next_id, "label": _node_label(next_id),
            "status": _text((following or {}).get("status")),
            "statement": _text((following or {}).get("statement")),
        }

    page["state"] = _state(states)
    page["states"] = states or [{"code": "OK", "detail": ""}]
    return page


# --------------------------------------------------------------------------- #
# HTML
# --------------------------------------------------------------------------- #

def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _pill(text: str, tone: str = "") -> str:
    if not text:
        return ""
    css = f"pill {tone}".strip()
    return f'<span class="{css}">{_esc(text)}</span>'


def _list_html(items: List[str], *, empty: str, css: str = "", raw: bool = False) -> str:
    if not items:
        return f'<p class="empty">{_esc(empty)}</p>'
    body = "".join(f"<li>{item if raw else _esc(item)}</li>" for item in items)
    return f'<ul class="{css}">{body}</ul>' if css else f"<ul>{body}</ul>"


def _count_text(items: List[Any]) -> str:
    return f"{len(items)} 条" if items else "未登记"


def _evidence_card(entry: Dict[str, Any], *, counter: bool = False) -> str:
    record_id = _esc(entry.get("record_id"))
    if not entry.get("exists"):
        return (f'<article class="evidence missing"><header><span class="rid">{record_id}</span>'
                f'<span class="pill bad">引用缺失</span></header>'
                f'<p>主链引用了这条证据，但 {_esc(EVIDENCE_REF)} 中没有对应记录。'
                f'页面不补造证据，也不把它当作空白通过。</p></article>')
    tags = [_pill(_text(entry.get("evidence_level")), "level"),
            _pill(_text(entry.get("corpus_role")), "ghost")]
    if not entry.get("qualified"):
        tags.insert(0, _pill("未通过证据资格门", "bad"))
    if counter:
        if entry.get("registered_on_chain"):
            tags.append(_pill("主链反证", "bad"))
        if entry.get("registered_in_judgment"):
            tags.append(_pill("需求判断反证", "warn"))
        if entry.get("overlaps_with_supporting"):
            tags.append(_pill("同时被节点引用", "warn"))
    context_note = ""
    if entry.get("context_matches_chain") is False:
        context_note = (f'<p class="warn-text">context_key 与主链不一致：'
                        f'{_esc(entry.get("context_key"))} ≠ 主链上下文</p>')
    fields = [
        ("用户角色", entry.get("user_role")),
        ("场景触发", entry.get("scene_trigger")),
        ("任务结果", entry.get("task_outcome")),
        ("当前替代", entry.get("current_substitute")),
        ("摩擦成本", entry.get("friction_cost")),
        ("后果", entry.get("consequence")),
        ("证据依据", entry.get("evidence_basis")),
    ]
    rows = "".join(
        f"<dt>{_esc(label)}</dt><dd>{_esc(value) if value else '<span class=empty>未登记</span>'}</dd>"
        for label, value in fields)
    source = " · ".join(part for part in (
        _text(entry.get("source_family")), _text(entry.get("source_ref")),
        _text(entry.get("context_key"))) if part)
    return (
        f'<article class="evidence{" counter" if counter else ""}">'
        f'<header><span class="rid">{record_id}</span>{"".join(tags)}</header>'
        f'<dl>{rows}</dl>'
        f'{context_note}'
        f'<p class="src">来源：{_esc(source) if source else "未登记"}</p>'
        f'</article>'
    )


def _snapshot_table(snapshots: Dict[str, Any]) -> str:
    items = snapshots.get("items") or []
    if not items:
        return ('<p class="empty">没有已登记的决定快照：这不代表“未决策”，只表示 '
                f'{_esc(SNAPSHOT_REF)}/ 下没有可读快照。</p>')
    rows = []
    for item in items:
        rows.append(
            "<tr>"
            f"<td>{_esc(item.get('decision_id'))}</td>"
            f"<td>{_esc(item.get('version')) or '<span class=empty>未登记</span>'}</td>"
            f"<td>{_esc(item.get('approved_at')) or '<span class=empty>未登记</span>'}</td>"
            f"<td>{_esc(item.get('approved_by')) or '<span class=empty>未登记</span>'}</td>"
            f"<td>{_esc(item.get('chosen_option')) or '<span class=empty>未登记</span>'}</td>"
            f"<td>{_esc(item.get('current_review_status')) or '<span class=empty>未登记</span>'}</td>"
            "</tr>")
    return (
        '<div class="table-wrap"><table><thead><tr>'
        "<th>决定</th><th>版本</th><th>批准时间</th><th>批准人</th>"
        "<th>选择</th><th>复核状态</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
        '<p class="note">身份字段是声明式记录（identity_basis=declaration_only），'
        '页面不把它当作真实签名或业务批准证明。</p>')


def _record_table(payload: Dict[str, Any]) -> str:
    if not payload.get("available"):
        return f'<p class="empty">{_esc(payload.get("detail") or "决策记录不可读")}</p>'
    records = payload.get("records") or []
    if not records:
        return ('<p class="empty">没有已登记的 DecisionRecord：'
                '这不代表没有判断，只表示 canonical 中没有该主链的决策记录。</p>')
    rows = "".join(
        "<tr>"
        f"<td>{_esc(item.get('record_id'))}</td>"
        f"<td>{_esc(item.get('version'))}</td>"
        f"<td>{_esc(item.get('recorded_at'))}</td>"
        f"<td>{_esc(item.get('decision_maker'))}</td>"
        f"<td>{_esc(item.get('decision'))}</td>"
        f"<td>{_esc(item.get('next_action'))}</td>"
        "</tr>" for item in records)
    return ('<div class="table-wrap"><table><thead><tr>'
            "<th>记录</th><th>版本</th><th>记录时间</th><th>决策人</th>"
            "<th>决定</th><th>下一步</th>"
            "</tr></thead><tbody>" + rows + "</tbody></table></div>")


def _change_log_table(entries: List[Dict[str, Any]]) -> str:
    if not entries:
        return '<p class="empty">主链没有登记变更记录：不代表从未修改，只表示 change_log 为空。</p>'
    rows = "".join(
        "<tr>"
        f"<td>{_esc(item.get('id'))}</td>"
        f"<td>{_esc(item.get('base_version'))} → {_esc(item.get('new_version'))}</td>"
        f"<td>{_esc(', '.join(item.get('reason_evidence_ids') or []))}</td>"
        f"<td>{_esc(', '.join(item.get('affected_refs') or []))}</td>"
        f"<td>{_esc(item.get('impact'))}</td>"
        f"<td>{_esc(item.get('decision'))}</td>"
        f"<td>{_esc(item.get('decided_at'))}</td>"
        "</tr>" for item in entries)
    return ('<div class="table-wrap"><table><thead><tr>'
            "<th>变更</th><th>版本</th><th>原因证据</th><th>影响节点</th>"
            "<th>影响</th><th>决定</th><th>时间</th>"
            "</tr></thead><tbody>" + rows + "</tbody></table></div>")


def _state_banner(page: Dict[str, Any]) -> str:
    if page["state"] == "ready":
        return ""
    tone = _STATE_TONES.get(page["state"], "warn")
    badge = _pill(_STATE_LABELS.get(page["state"], page["state"]), tone)
    blocks = [f'<div class="state-line">{badge}<span>{_esc(page["state"])}</span></div>']
    for item in page.get("states") or []:
        if item.get("code") == "OK":
            continue
        detail = item.get("detail") or ""
        code = item.get("detail_code") or item.get("code") or ""
        blocks.append(f'<p><strong>{_esc(code)}</strong> {_esc(detail)}</p>')
    return f'<section class="banner {_STATE_TONES.get(page["state"], "warn")}">' + "".join(blocks) + "</section>"


def _nav_html(page: Dict[str, Any]) -> str:
    items = []
    for entry in page["navigation"]["nodes"]:
        count = entry.get("evidence_count")
        count_text = "未登记" if count is None or count == 0 else f"{count} 条证据"
        status = entry.get("status") or "未登记"
        items.append(
            f'<li class="{"current" if entry.get("current") else ""}">'
            f'<span class="idx">{sure_engine.REASONING_NODES.index(entry["id"]) + 1}</span>'
            f'<span class="name">{_esc(entry.get("label"))}</span>'
            f'<span class="meta">{_esc(status)} · {_esc(count_text)}</span>'
            "</li>")
    return '<ol class="node-nav">' + "".join(items) + "</ol>"


def _section(title: str, body: str, *, css: str = "") -> str:
    return f'<section class="{css}"><h2>{_esc(title)}</h2>{body}</section>'


def render_html(page: Dict[str, Any]) -> str:
    """Render a self-contained HTML page with no scripts, links or images."""
    title = "Askovo 单判断证据页"
    study_id = _text((page.get("study") or {}).get("study_id")) or "未登记研究"
    chain = page.get("chain") or {}
    node = page.get("node") or {}
    decision = page.get("decision") or {}
    reasoning = page.get("reasoning") or {}
    gaps = page.get("gaps") or {}
    falsification = page.get("falsification") or {}

    subtitle_bits = [study_id, _text(chain.get("id")) or "主链未登记"]
    if node:
        subtitle_bits.append(f"{node.get('label')}（{page['navigation'].get('position')}）")

    review_banner = ""
    if decision.get("needs_re_review"):
        reasons = "；".join(decision.get("review_reasons") or [])
        review_banner = (
            '<section class="banner warn"><div class="state-line">'
            f'{_pill("需要重审", "warn")}'
            f'<span>主链已登记反证：{_esc(", ".join(decision.get("counter_evidence_ids") or []))}</span>'
            "</div>"
            f"<p>{_esc(reasons)}</p>"
            '<p class="note">这是复核信号，不是页面自动推翻决定；人工复核与后续动作由主链和决策记录承担。</p>'
            "</section>")

    decision_html = ""
    if decision:
        options = _list_html(decision.get("options") or [], empty="未登记决策选项")
        minimum = _list_html(decision.get("minimum_evidence") or [], empty="未登记最低证据要求")
        states = decision.get("supporting_states") or {}
        state_bits = []
        for key, label in (("delivery", "交付"), ("outcome", "结果"), ("causal", "因果")):
            value = states.get(key) or {}
            state_bits.append(
                f"<li><strong>{label}</strong>：{_esc(value.get('status') or '未登记')}</li>")
        human = decision.get("human_review") or {}
        decision_html = (
            '<div class="grid two">'
            f'<div class="card"><h3>决策问题</h3><p class="lead">{_esc(decision.get("question")) or "未登记"}</p>'
            f'<p class="meta">主链状态 {_esc(decision.get("chain_status")) or "未登记"} · '
            f'置信度 {_esc(decision.get("confidence")) or "未登记"} · '
            f'负责人 {_esc(decision.get("owner")) or "未登记"}</p>'
            f"<h3>选项</h3>{options}</div>"
            '<div class="card"><h3>最低证据要求</h3>' + minimum +
            '<h3>交付 / 结果 / 因果</h3><ul>' + "".join(state_bits) + "</ul>"
            f'<p class="meta">人工复核：{_esc(human.get("status")) or "未登记"} · '
            f'{_esc(human.get("reviewer")) or "未登记"}</p></div>'
            "</div>")

    node_body = ""
    if node:
        upstream = reasoning.get("upstream") or {}
        downstream = reasoning.get("downstream") or {}
        edge = []
        if upstream:
            edge.append(f'<li><strong>上游 · {_esc(upstream.get("label"))}</strong>：'
                        f'{_esc(upstream.get("statement")) or "未登记"}'
                        f'<span class="meta">（{_esc(upstream.get("status")) or "未登记"}）</span></li>')
        if downstream:
            edge.append(f'<li><strong>下游 · {_esc(downstream.get("label"))}</strong>：'
                        f'{_esc(downstream.get("statement")) or "未登记"}'
                        f'<span class="meta">（{_esc(downstream.get("status")) or "未登记"}）</span></li>')
        node_body = (
            f'<div class="card"><p class="eyebrow">{_esc(node.get("label"))} · '
            f'{_esc(node.get("id"))} · 状态 {_esc(node.get("status")) or "未登记"}</p>'
            f'<p class="lead">{_esc(node.get("statement")) or "未登记判断陈述"}</p>'
            f'<h3>推理边</h3><p>{_esc(node.get("rationale")) or "未登记推理理由"}</p>'
            '<h3>上下游</h3>' +
            _list_html(edge, empty="没有可读的上下游节点", raw=True) +
            '<h3>隐含假设</h3>' +
            _list_html(node.get("assumptions") or [], empty="未登记假设：不代表没有假设") +
            '<h3>备择解释</h3>' +
            _list_html(reasoning.get("alternatives") or [], empty="未登记备择解释") +
            "</div>")

    supporting_cards = "".join(_evidence_card(entry) for entry in page.get("supporting") or [])
    supporting_html = supporting_cards or (
        '<p class="empty">当前节点没有登记支撑证据：这不等于“无证据”，'
        '只表示 node.evidence_ids 未登记。</p>')
    counter_cards = "".join(_evidence_card(entry, counter=True)
                            for entry in page.get("counter") or [])
    counter_html = counter_cards or (
        '<p class="empty">主链与关联需求判断都没有登记反证：这不等于“无风险”，'
        '只表示 counter_evidence_ids 为空。页面不据此下通过结论。</p>')
    if counter_cards:
        counter_html += ('<p class="note">反证不等于否定；页面只呈现记录与登记位置，'
                         '不自动裁决、不自动降级或撤回决定。</p>')

    gap_rows = []
    for source, label in (("chain", "主链缺口"), ("judgment", "需求判断缺口"),
                          ("assumptions", "节点假设（尚未验证）")):
        for item in gaps.get(source) or []:
            gap_rows.append(f"<li><span class=tag>{_esc(label)}</span>{_esc(item)}</li>")
    for item in gaps.get("missing_references") or []:
        gap_rows.append(f"<li><span class='tag bad'>引用缺失</span>{_esc(item)}</li>")
    for item in gaps.get("stale") or []:
        gap_rows.append(f"<li><span class='tag bad'>{_esc(item.get('detail_code'))}</span>"
                        f"{_esc(item.get('detail'))}</li>")
    gap_html = (f'<ul class="gaps">{"".join(gap_rows)}</ul>' if gap_rows
                else '<p class="empty">没有登记缺口：这不代表证据充分，只表示 gaps/assumptions 为空。</p>')

    falsification_rows = []
    if falsification.get("chain_next_test"):
        falsification_rows.append(
            f"<li><span class=tag>主链</span>{_esc(falsification.get('chain_next_test'))}</li>")
    if falsification.get("judgment_next_test"):
        falsification_rows.append(
            f"<li><span class=tag>需求判断</span>{_esc(falsification.get('judgment_next_test'))}</li>")
    for hypothesis in falsification.get("hypotheses") or []:
        falsification_rows.append(
            f"<li><span class=tag>假设 {_esc(hypothesis.get('id'))}</span>"
            f"{_esc(hypothesis.get('falsified_if')) or '未登记证伪条件'}"
            f'<span class="meta">（{_esc(hypothesis.get("link_basis"))}）</span></li>')
    falsification_html = (f'<ul class="falsify">{"".join(falsification_rows)}</ul>'
                          if falsification_rows else
                          '<p class="empty">没有登记下一证伪动作：这不代表判断已证实。</p>')

    history_html = (
        "<h3>变更记录</h3>" + _change_log_table(page.get("change_log") or []) +
        "<h3>决定快照</h3>" + _snapshot_table(page.get("snapshots") or {}) +
        "<h3>决策记录</h3>" + _record_table(page.get("decision_records") or {})
    )

    source_rows = "".join(
        f"<tr><td>{_esc(item.get('ref'))}</td><td class=path>{_esc(item.get('path'))}</td>"
        f"<td>{_esc(item.get('status'))}</td></tr>" for item in page.get("sources") or [])
    warnings_html = _list_html(page.get("warnings") or [], empty="", css="warn-list") \
        if page.get("warnings") else ""
    faults_html = ""
    if page.get("faults"):
        fault_rows = "".join(f"<li><span class='tag bad'>{_esc(item.get('code'))}</span>"
                             f"{_esc(item.get('detail'))}</li>" for item in page["faults"])
        faults_html = f'<h3>读取故障</h3><ul class="gaps">{fault_rows}</ul>'
    notes_html = _list_html(page.get("notes") or [], empty="") if page.get("notes") else ""

    commands_html = "".join(f"<li><code>{_esc(command)}</code></li>"
                            for command in page.get("commands") or [])
    commands_html = (f'<ul class="commands">{commands_html}</ul>'
                     '<p class="note">仅供人工复制，本页不执行这些命令；'
                     '页面本身不触发同步、审批、复核或发送。</p>')

    body = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)} · {_esc(study_id)}</title>
<style>
:root {{ color-scheme: light; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif; background: #f4f2ec; color: #20201d; line-height: 1.62; }}
main {{ max-width: 1120px; margin: 0 auto; padding: 36px 22px 72px; }}
header.page {{ border-bottom: 2px solid #20201d; padding-bottom: 18px; margin-bottom: 24px; }}
.eyebrow {{ margin: 0 0 6px; font-size: 12px; letter-spacing: .14em; text-transform: uppercase; color: #6b6558; }}
h1 {{ margin: 0 0 8px; font-size: 30px; letter-spacing: -.02em; }}
.sub {{ margin: 0; color: #4c483f; }}
.badges {{ margin-top: 12px; display: flex; gap: 8px; flex-wrap: wrap; }}
.pill {{ display: inline-block; padding: 2px 9px; border-radius: 999px; border: 1px solid #c9c3b4; font-size: 12px; background: #fbfaf6; color: #4c483f; white-space: nowrap; }}
.pill.level {{ border-color: #20201d; color: #20201d; font-weight: 600; }}
.pill.bad {{ border-color: #9c2d20; color: #9c2d20; background: #fbeeea; }}
.pill.warn {{ border-color: #8a5a12; color: #7a4c06; background: #fdf3df; }}
.pill.ghost {{ border-style: dashed; }}
.pill.ok {{ border-color: #2f6b3a; color: #2f6b3a; background: #edf6ee; }}
section {{ margin: 26px 0; }}
h2 {{ font-size: 19px; margin: 0 0 12px; padding-bottom: 6px; border-bottom: 1px solid #d8d2c4; }}
h3 {{ font-size: 14px; margin: 18px 0 8px; color: #4c483f; letter-spacing: .02em; }}
.card {{ background: #fbfaf6; border: 1px solid #ddd7c9; border-radius: 10px; padding: 16px 18px; }}
.grid.two {{ display: grid; grid-template-columns: 1.15fr .85fr; gap: 16px; }}
@media (max-width: 780px) {{ .grid.two {{ grid-template-columns: 1fr; }} h1 {{ font-size: 24px; }} }}
.lead {{ font-size: 18px; font-weight: 600; margin: 6px 0 10px; }}
.meta {{ color: #6b6558; font-size: 13px; }}
.note {{ color: #6b6558; font-size: 13px; margin-top: 10px; }}
.banner {{ border-radius: 10px; padding: 14px 16px; border: 1px solid; }}
.banner.bad {{ background: #fbeeea; border-color: #c98a7f; }}
.banner.warn {{ background: #fdf3df; border-color: #d6b477; }}
.banner.muted {{ background: #f0eee7; border-color: #cfc9ba; }}
.state-line {{ display: flex; gap: 10px; align-items: center; font-weight: 600; margin-bottom: 4px; flex-wrap: wrap; }}
.banner p {{ margin: 5px 0; }}
.node-nav {{ list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(7, 1fr); gap: 8px; }}
.node-nav li {{ background: #fbfaf6; border: 1px solid #ddd7c9; border-radius: 9px; padding: 10px; min-height: 84px; display: flex; flex-direction: column; gap: 4px; }}
.node-nav li.current {{ border-color: #20201d; box-shadow: inset 0 0 0 1px #20201d; background: #fffdf7; }}
.node-nav .idx {{ font-size: 11px; color: #8b8475; }}
.node-nav .name {{ font-weight: 600; }}
.node-nav .meta {{ font-size: 11px; color: #6b6558; line-height: 1.35; }}
@media (max-width: 900px) {{ .node-nav {{ grid-template-columns: repeat(2, 1fr); }} }}
.evidence {{ background: #fbfaf6; border: 1px solid #ddd7c9; border-left: 4px solid #5a6b4f; border-radius: 8px; padding: 14px 16px; margin-bottom: 12px; }}
.evidence.counter {{ border-left-color: #9c2d20; }}
.evidence.missing {{ border-left-color: #9c2d20; background: #fff7f5; }}
.evidence header {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }}
.rid {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-weight: 700; }}
dl {{ display: grid; grid-template-columns: 96px 1fr; gap: 4px 12px; margin: 8px 0; }}
dt {{ color: #6b6558; font-size: 12px; padding-top: 2px; }}
dd {{ margin: 0; }}
.src {{ margin: 8px 0 0; font-size: 12px; color: #6b6558; border-top: 1px dashed #ddd7c9; padding-top: 8px; }}
.empty {{ color: #8b8475; font-style: italic; }}
.warn-text {{ color: #7a4c06; background: #fdf3df; padding: 4px 8px; border-radius: 6px; font-size: 13px; }}
ul {{ margin: 6px 0; padding-left: 20px; }}
.gaps li, .falsify li {{ margin: 6px 0; }}
.tag {{ display: inline-block; font-size: 11px; color: #6b6558; border: 1px solid #d8d2c4; border-radius: 4px; padding: 0 6px; margin-right: 7px; white-space: nowrap; }}
.tag.bad {{ color: #9c2d20; border-color: #c98a7f; }}
.table-wrap {{ overflow-x: auto; border: 1px solid #ddd7c9; border-radius: 8px; background: #fbfaf6; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid #e6e1d5; vertical-align: top; }}
th {{ background: #f0ede3; font-weight: 600; white-space: nowrap; }}
tr:last-child td {{ border-bottom: 0; }}
td.path {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; overflow-wrap: anywhere; }}
.commands {{ list-style: none; padding: 0; }}
.commands li {{ margin: 6px 0; }}
code {{ display: block; background: #20201d; color: #f4f2ec; padding: 8px 10px; border-radius: 6px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; overflow-wrap: anywhere; }}
.commands code::after {{ content: "  （仅供人工复制，本页不执行）"; color: #b9b2a2; }}
footer {{ margin-top: 34px; border-top: 1px solid #d8d2c4; padding-top: 14px; font-size: 12px; color: #6b6558; }}
</style>
</head>
<body>
<main>
<header class="page">
<p class="eyebrow">Askovo · 单判断证据页 · L0 只读投影</p>
<h1>{_esc(title)}</h1>
<p class="sub">{_esc(" · ".join(subtitle_bits))}</p>
<div class="badges">
{_pill("只读", "ok")}
{_pill("schema " + _text(page.get("schema")), "ghost")}
{_pill("生成 " + _text(page.get("generated_at")), "ghost")}
{_pill(_STATE_LABELS.get(page.get("state"), page.get("state")), _STATE_TONES.get(page.get("state"), "warn"))}
</div>
</header>

{_state_banner(page)}
{review_banner}
{_section("决策语境", decision_html)}
{_section("七节点导航", _nav_html(page))}
{_section("当前节点与推理边", node_body)}
{_section("支撑证据", supporting_html)}
{_section("反证", counter_html)}
{_section("证据缺口", gap_html)}
{_section("下一证伪动作", falsification_html)}
{_section("历史重审", history_html)}
{_section("来源与读取状态", '<div class="table-wrap"><table><thead><tr><th>引用</th><th>路径</th><th>状态</th></tr></thead><tbody>' + source_rows + '</tbody></table></div>' + warnings_html + faults_html + notes_html)}
{_section("人工操作（仅供复制）", commands_html)}
<footer>{_esc(page.get("boundary") or BOUNDARY)}<br>生成器 {_esc(page.get("generator"))} v{_esc(page.get("generator_version"))} · 生成时间 {_esc(page.get("generated_at"))}</footer>
</main>
</body>
</html>
"""
    return body


# --------------------------------------------------------------------------- #
# plain-text summary
# --------------------------------------------------------------------------- #

def render_summary(page: Dict[str, Any]) -> str:
    study = page.get("study") or {}
    chain = page.get("chain") or {}
    node = page.get("node") or {}
    decision = page.get("decision") or {}
    navigation = page.get("navigation") or {}
    supporting = page.get("supporting") or []
    counter = page.get("counter") or []
    gaps = page.get("gaps") or {}
    falsification = page.get("falsification") or {}
    snapshots = (page.get("snapshots") or {}).get("items") or []
    records = (page.get("decision_records") or {}).get("records") or []
    states = [item.get("code") for item in page.get("states") or [] if item.get("code") != "OK"]

    def ids(entries: List[Dict[str, Any]]) -> str:
        return ", ".join(_text(entry.get("record_id")) for entry in entries) or "未登记"

    lines = [
        "Askovo 单判断证据页（L0 只读）",
        f"研究：{_text(study.get('study_id')) or '未登记'} · 主链：{_text(chain.get('id')) or '未登记'}"
        f" · 节点：{_text(node.get('label')) or _text(navigation.get('current')) or '未登记'}"
        f"（{_text(navigation.get('position')) or '未登记'}）",
        f"状态：{page.get('state')}" + (f"（{', '.join(states)}）" if states else ""),
        f"判断：{_text(decision.get('chain_status')) or '未登记'} · "
        f"置信度 {_text(decision.get('confidence')) or '未登记'}",
        "重审：" + ("需要，已登记反证 " + ", ".join(decision.get("counter_evidence_ids") or [])
                   if decision.get("needs_re_review") else "未触发（不代表已被人工复核）"),
        f"支撑证据：{_count_text(supporting)}" + (f"（{ids(supporting)}）" if supporting else ""),
        f"反证：{_count_text(counter)}" + (f"（{ids(counter)}）" if counter else ""),
        f"缺口：{_count_text((gaps.get('chain') or []) + (gaps.get('judgment') or []))}"
        f" · 下一证伪动作："
        f"{_count_text([item for item in (falsification.get('chain_next_test'), falsification.get('judgment_next_test')) if item])}",
        f"决定快照：{_count_text(snapshots)} · 决策记录：{_count_text(records)}",
        f"生成：{_text(page.get('generated_at'))} · 生成器 {_text(page.get('generator'))}"
        f" v{_text(page.get('generator_version'))}",
        f"边界：{_text(page.get('boundary'))}",
    ]
    return "\n".join(lines)
