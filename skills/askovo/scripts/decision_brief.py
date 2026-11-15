"""A-04 Decision Brief: a read-only projection of the canonical chain.

The brief is the one-page decision artifact from PRD §2.3. It is **not** a
second editable truth: it reads ``04-findings/product-reasoning.json``,
``04-findings/demand-judgments.json``, ``02-data/evidence.jsonl`` and
``decision_review``, and writes only derived artifacts under ``06-report/``.
Every claim keeps its source reference, so a reviewer can walk from a sentence
back to a node and an evidence record.

Gates enforced here (AC A19-A23):

- **A19** no evidence still yields a ``hold`` action, never a validated decision
  and never an approval;
- **A20** the PRD acceptance checklist is the canonical
  ``feature.acceptance_conditions`` / ``product.acceptance_criteria`` projection
  with a stable ``product-reasoning.json#chains/<id>/nodes/<node>`` reference;
- **A21** counter-evidence marks the brief ``needs_review`` and shows what it
  challenges, keeping the previous recommendation instead of overwriting it;
- **A22** every emitted number keeps its unit, time window and source; a number
  missing any of them is withheld and listed as unprovenanced;
- **A23** no invented interviews or conversion rates; ``research_facts`` stays
  ``null`` unless the canonical artifacts contain the fact, and a heuristic rank
  is a ``heuristic_score`` with ``calibrated: false``, never a probability.

A broken reference or a drifted input marks the brief ``stale``: formal delivery
is blocked (``delivery_state: blocked``, ``reason_code: STALE_SOURCE``) and only
a diagnostic draft is written.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import decision_review
import research_loop
import sure_engine

SCHEMA = "askovo.decision-brief/1"
KIND = "askovo.decision-brief"
SCHEMA_VERSION = "1.0"
CANONICAL_REF = "04-findings/product-reasoning.json"
REVIEW_REF = "05-audit/decision-review.json"
REPORT_RELATIVE = Path("06-report")
JSON_NAME = "decision-brief.json"
MD_NAME = "decision-brief.md"

#: PRD §2.3's nine fixed sections, in order.
SECTIONS = (
    "question",
    "recommendation",
    "options",
    "evidence",
    "counter_evidence",
    "limitations",
    "rejected_options",
    "verification_actions",
    "prd_acceptance",
    "states",
)
SECTION_TITLES = {
    "question": "问题、边界、时间窗与决策负责人",
    "recommendation": "结论（recommendation，不是自动批准）",
    "options": "选项（同一组维度）",
    "evidence": "支撑证据",
    "counter_evidence": "反证",
    "limitations": "受限结论",
    "rejected_options": "不做的选择及原因",
    "verification_actions": "下一个最低成本验证动作",
    "prd_acceptance": "PRD 开发验收清单",
    "states": "四态独立显示",
}
FLOW = ("scene", "user", "pain", "need", "feature", "product", "business")
DIMENSIONS = ("user", "task", "opportunity", "cost", "risk")

BOUNDARY = (
    "Brief 是 canonical 七节点主链与 decision_review 的只读投影：它列出结论、选项、证据、"
    "反证、缺口与下一动作，但不改写主链、不分配证据等级、不替人批准。recommendation 不是"
    "自动批准；delivered 不等于 decision_approved；validated 只表示预先指定假设在证据范围内"
    "成立，不表示整个产品市场验证完成。"
)
LIMITATION_SAMPLES = (
    "样本为授权来源便利样本，不能代表总体；公开 issue 中的要求不等于已证实的实际使用行为",
    "无真实付费/留存/复购等商业行为证据时不得宣称商业验证或商业成立",
)
RESEARCH_FACT_KEYS = ("interviews_conducted", "conversion_rate", "market_size_estimate")

#: Money, percentages and thousands-separated quantities. Deliberately narrow so
#: identifiers like ``PR01``, ``G0`` or ``two-week`` are not treated as numbers.
_UNVERIFIED_NUMBER = re.compile(
    r"(?:[$€£¥]\s?\d[\d,]*(?:\.\d+)?"
    r"|\d[\d,]*(?:\.\d+)?\s?%"
    r"|\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b)")
REDACTION = "[未核验数字]"


class BriefError(ValueError):
    """A brief rule was violated; always carries a C-01 reason code."""

    def __init__(self, message: str, reason_code: str = "INPUT_REQUIRED",
                 suggestion: str = "") -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.suggestion = suggestion


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _records(study_dir: Path) -> List[Dict[str, Any]]:
    path = study_dir / "02-data" / "evidence.jsonl"
    if not path.is_file():
        return []
    records: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            records.append(item)
    return records


def _text(record: Dict[str, Any]) -> str:
    return str(record.get("text") or record.get("text_excerpt") or "").strip()


def _sha_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _fingerprint(study_dir: Path) -> str:
    """Deterministic digest of every canonical brief input."""
    digest = hashlib.sha256()
    for relative in ("study.json", CANONICAL_REF, "04-findings/demand-judgments.json",
                     "02-data/evidence.jsonl"):
        path = study_dir / relative
        digest.update(relative.encode("utf-8") + b"\0")
        if path.is_file():
            try:
                digest.update(path.read_bytes())
            except OSError as exc:
                digest.update(str(exc).encode("utf-8"))
        else:
            digest.update(b"<missing>")
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def _chains(reasoning: Any) -> List[Dict[str, Any]]:
    if not isinstance(reasoning, dict):
        return []
    return [item for item in reasoning.get("chains") or [] if isinstance(item, dict)]


def review_signal(chain: Dict[str, Any], *,
                  extra_counter_ids: Tuple[str, ...] = ()) -> Dict[str, Any]:
    """The single "does this decision need re-review?" predicate.

    ``decision_brief`` and ``research_delta`` both call this, so the brief and the
    delta can never disagree about whether new material challenges the decision.
    A counter record only counts once it is registered on the chain (or, for an
    incremental delta, once it is new and registered as contradicting).
    """
    registered = [str(value) for value in chain.get("counter_evidence_ids") or []]
    counter = list(dict.fromkeys(registered + [str(value) for value in extra_counter_ids]))
    extra = [value for value in counter if value not in registered]
    reasons: List[str] = []
    if registered:
        reasons.append(f"主链已登记 {len(registered)} 条反证：{', '.join(registered)}")
    if extra:
        reasons.append(f"增量同步带入新的反证记录：{', '.join(extra)}")
    return {
        "needs_re_review": bool(counter),
        "counter_evidence_ids": counter,
        "reasons": reasons,
    }


def _chain_evidence_ids(chain: Dict[str, Any]) -> List[str]:
    nodes = chain.get("nodes") if isinstance(chain.get("nodes"), dict) else {}
    ids: List[str] = []
    for name in FLOW:
        node = nodes.get(name) if isinstance(nodes.get(name), dict) else {}
        ids.extend(str(value) for value in node.get("evidence_ids") or [])
    ids.extend(str(value) for value in chain.get("counter_evidence_ids") or [])
    return list(dict.fromkeys(ids))


# --------------------------------------------------------------------------- #
# stale gate
# --------------------------------------------------------------------------- #

def stale_reasons(
    study_dir: Path,
    chains: List[Dict[str, Any]],
    judgments: List[Dict[str, Any]],
    record_ids: set,
    *,
    previous_fingerprints: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Broken references or drifted inputs block formal delivery.

    Shared by the brief and the delta: a broken reference must not be "stale" in
    one projection and "fresh" in the other.
    """
    reasons: List[Dict[str, Any]] = []
    judgment_ids = {str(item.get("id")) for item in judgments if isinstance(item, dict)}

    for chain in chains:
        chain_id = str(chain.get("id") or "chain")
        nodes = chain.get("nodes") if isinstance(chain.get("nodes"), dict) else {}
        for name in FLOW:
            node = nodes.get(name) if isinstance(nodes.get(name), dict) else {}
            unknown = sorted(str(value) for value in node.get("evidence_ids") or []
                             if str(value) not in record_ids)
            if unknown:
                reasons.append({
                    "detail_code": "BROKEN_REFERENCE",
                    "detail": f"{chain_id}.{name} 引用了不存在的证据：" + ", ".join(unknown),
                    "refs": [f"{chain_id}.{name}"] + unknown,
                })
        unknown_counter = sorted(str(value) for value in chain.get("counter_evidence_ids") or []
                                 if str(value) not in record_ids)
        if unknown_counter:
            reasons.append({
                "detail_code": "BROKEN_REFERENCE",
                "detail": f"{chain_id}.counter_evidence_ids 引用了不存在的证据："
                          + ", ".join(unknown_counter),
                "refs": [f"{chain_id}.counter_evidence_ids"] + unknown_counter,
            })
        linked = str(chain.get("demand_judgment_id") or "").strip()
        if linked and linked not in judgment_ids:
            reasons.append({
                "detail_code": "BROKEN_REFERENCE",
                "detail": f"{chain_id} 关联的需求判断 {linked} 不存在",
                "refs": [f"{chain_id}.demand_judgment_id", linked],
            })

    for judgment in judgments:
        if not isinstance(judgment, dict):
            continue
        judgment_id = str(judgment.get("id") or "judgment")
        cited: List[str] = []
        for key in ("problem_evidence_ids", "solution_evidence_ids",
                    "commercial_evidence_ids", "counter_evidence_ids"):
            cited.extend(str(value) for value in judgment.get(key) or [])
        unknown = sorted({value for value in cited if value not in record_ids})
        if unknown:
            reasons.append({
                "detail_code": "BROKEN_REFERENCE",
                "detail": f"demand-judgments[{judgment_id}] 引用了不存在的证据："
                          + ", ".join(unknown),
                "refs": [judgment_id] + unknown,
            })

    # D4: the review pins each cited record's content. A same-id edit keeps the
    # reference intact but changes what the decision was made on, so it is drift.
    records_by_id: Dict[str, Dict[str, Any]] = {}
    for relative in ("02-data/evidence.jsonl",):
        path = study_dir / relative
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict) and item.get("record_id"):
                records_by_id[str(item["record_id"])] = item
    for record_id, recorded in sorted((previous_fingerprints or {}).items()):
        current = records_by_id.get(str(record_id))
        if current is None:
            continue  # a missing record is already a BROKEN_REFERENCE
        if decision_review.evidence_fingerprint(current) != str(recorded):
            reasons.append({
                "detail_code": "INPUT_DRIFT",
                "detail": (f"{record_id} 的内容在决策复盘之后被修改（同一 record_id 不同内容）；"
                           f"当前 Brief 不能当作已复核结论"),
                "refs": [record_id],
            })

    review_path = study_dir / REVIEW_REF
    canonical = study_dir / CANONICAL_REF
    if review_path.is_file() and canonical.is_file():
        try:
            if canonical.stat().st_mtime > review_path.stat().st_mtime + 0.000001:
                reasons.append({
                    "detail_code": "INPUT_DRIFT",
                    "detail": "canonical 主链在决策复盘之后被修改，Brief 不能当作当前结论",
                    "refs": [CANONICAL_REF, REVIEW_REF],
                })
        except OSError:
            pass
    return reasons


# --------------------------------------------------------------------------- #
# section builders
# --------------------------------------------------------------------------- #

def stale_inputs(study_dir: Path) -> List[Dict[str, Any]]:
    """Read the canonical inputs and return every staleness reason.

    The single reader both ``decision_brief`` and ``research_delta`` call, so the
    two projections cannot disagree about whether the decision is still current.
    """
    study_dir = Path(study_dir).resolve()
    chains = _chains(_load(study_dir / CANONICAL_REF))
    judgments = _load(study_dir / "04-findings" / "demand-judgments.json")
    judgments = [item for item in judgments if isinstance(item, dict)] \
        if isinstance(judgments, list) else []
    record_ids = {str(item.get("record_id")) for item in _records(study_dir)
                  if item.get("record_id")}
    recorded_review = _load(study_dir / REVIEW_REF)
    fingerprints = ((recorded_review or {}).get("input_fingerprints") or {}).get("evidence") \
        if isinstance(recorded_review, dict) else None
    return stale_reasons(study_dir, chains, judgments, record_ids,
                         previous_fingerprints=fingerprints)


def _question_section(study: Dict[str, Any], chain: Dict[str, Any],
                      question: str) -> Dict[str, Any]:
    decision = study.get("decision") if isinstance(study.get("decision"), dict) else {}
    scope = study.get("scope") if isinstance(study.get("scope"), dict) else {}
    window = scope.get("source_time_window") if isinstance(scope.get("source_time_window"), dict) else {}
    return {
        "text": question or str(decision.get("question") or chain.get("title") or ""),
        "scope": {
            "target_users": list(scope.get("target_users") or []),
            "markets": list(scope.get("markets") or []),
            "languages": list(scope.get("languages") or []),
            "allowed_sources": list(scope.get("allowed_sources") or []),
            "prohibited_inferences": list(scope.get("prohibited_inferences") or []),
            "unit_of_observation": scope.get("unit_of_observation"),
        },
        "time_window": {
            "start": window.get("start"),
            "end": window.get("end"),
            "label": (f"{window.get('start')}..{window.get('end')}"
                      if window.get("start") or window.get("end") else "未登记"),
        },
        "decision_owner": decision.get("owner"),
        "deadline": decision.get("deadline"),
        "decision_type": decision.get("decision_type"),
        "minimum_evidence": list(decision.get("minimum_evidence") or []),
    }


def _recommendation(chain: Dict[str, Any], *, supported: int,
                    recommended_option_id: Optional[str]) -> Dict[str, Any]:
    nodes = chain.get("nodes") if isinstance(chain.get("nodes"), dict) else {}
    business = nodes.get("business") if isinstance(nodes.get("business"), dict) else {}
    gate = business.get("gate") if isinstance(business.get("gate"), dict) else {}
    statement = gate.get("decision") or business.get("statement") or chain.get("title")
    decided = str(chain.get("status") or "") == "decided"
    if not supported:
        kind = "hold"
    elif not decided:
        kind = "needs_validation"
    else:
        kind = "recommend"
    return {
        "kind": kind,
        "statement": statement,
        "option_id": recommended_option_id if kind == "recommend" else None,
        "not_approved": True,
        "heuristic_score": None,
        "calibrated": False,
        "ranking_basis": (
            "规则排序：仅当存在通过审计的支持判断且主链为 decided 时才给出 recommendation；"
            "未使用校准概率，heuristic_score 保持 null"
        ),
        "confidence": chain.get("confidence"),
        "meaning": (
            "recommendation 是建议，不是自动批准；hold 表示证据不足，不能推出 validated"
        ),
    }


def _dimensions(chain: Dict[str, Any], business: Dict[str, Any],
                findings: List[Dict[str, Any]]) -> Dict[str, str]:
    nodes = chain.get("nodes") if isinstance(chain.get("nodes"), dict) else {}
    user = nodes.get("user") if isinstance(nodes.get("user"), dict) else {}
    need = nodes.get("need") if isinstance(nodes.get("need"), dict) else {}
    pain = nodes.get("pain") if isinstance(nodes.get("pain"), dict) else {}
    return {
        "user": _guard_text(str(user.get("statement") or "unknown"),
                            "node.user.statement", findings),
        "task": _guard_text(str(need.get("statement") or "unknown"),
                            "node.need.statement", findings),
        "opportunity": _guard_text(str(pain.get("statement") or "unknown"),
                                   "node.pain.statement", findings),
        "cost": _guard_text(
            "; ".join(str(item) for item in business.get("cost_drivers") or []) or "unknown",
            "business.cost_drivers", findings),
        "risk": _guard_text(
            "; ".join(str(item) for item in business.get("non_goals") or []) or "unknown",
            "business.non_goals", findings),
    }


def _options(study: Dict[str, Any], chain: Dict[str, Any],
             recommended_option_id: Optional[str],
             findings: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    decision = study.get("decision") if isinstance(study.get("decision"), dict) else {}
    statements = [str(item) for item in decision.get("options") or [] if str(item).strip()]
    nodes = chain.get("nodes") if isinstance(chain.get("nodes"), dict) else {}
    business = nodes.get("business") if isinstance(nodes.get("business"), dict) else {}
    dimensions = _dimensions(chain, business, findings)
    evidence_ids = _chain_evidence_ids(chain)
    options: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for index, statement in enumerate(statements[:5]):
        option_id = f"option-{chr(ord('A') + index)}"
        status = "recommended" if option_id == recommended_option_id else "candidate"
        options.append({
            "id": option_id,
            "statement": statement,
            "status": status,
            "dimensions": dict(dimensions),
            "dimensions_basis": "chain_level",
            "evidence_ids": list(evidence_ids) if status == "recommended" else [],
            "counter_evidence_ids": [],
        })
        if status != "recommended":
            rejected.append({
                "id": option_id,
                "statement": statement,
                "reason": ("主链未给出该选项的取舍理由；未选择不等于已被证伪，"
                           "需要人工补一条明确的反证或成本理由"),
            })
    return options, rejected


def _recommended_option_id(study: Dict[str, Any], chain: Dict[str, Any],
                           kind: str) -> Optional[str]:
    if kind != "recommend":
        return None
    decision = study.get("decision") if isinstance(study.get("decision"), dict) else {}
    statements = [str(item).strip() for item in decision.get("options") or []]
    nodes = chain.get("nodes") if isinstance(chain.get("nodes"), dict) else {}
    business = nodes.get("business") if isinstance(nodes.get("business"), dict) else {}
    gate = business.get("gate") if isinstance(business.get("gate"), dict) else {}
    candidates = [str(gate.get("decision") or "").strip(),
                  str(business.get("statement") or "").strip(),
                  str(chain.get("title") or "").strip()]
    for candidate in candidates:
        if candidate and candidate in statements:
            return f"option-{chr(ord('A') + statements.index(candidate))}"
    return None


def _evidence_entry(record: Dict[str, Any], qualification: Dict[str, Any],
                    *, challenge: str = "") -> Dict[str, Any]:
    return {
        "record_id": record.get("record_id"),
        "source_url": record.get("source_url") or record.get("source_ref") or "",
        "collected_at": record.get("collected_at") or record.get("created_at") or "",
        "context_key": record.get("context_key") or "",
        "evidence_level": record.get("evidence_level"),
        "qualification": {
            "measurement_integrity": qualification.get("measurement_integrity"),
            "behavior_kind": qualification.get("behavior_kind"),
            "claim_eligibility": qualification.get("claim_eligibility"),
            "needs_requalification": qualification.get("needs_requalification"),
        },
        "excerpt": _text(record)[:400],
        "challenge": challenge,
    }


def _verification_actions(chain: Dict[str, Any], review_payload: Dict[str, Any],
                          owner: Optional[str],
                          findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    actions: List[Dict[str, Any]] = []
    next_test = str(chain.get("next_test") or "").strip()
    tasks = chain.get("external_validation_tasks") if isinstance(chain, dict) else None
    if next_test:
        actions.append({
            "action": _guard_text(next_test, "chain.next_test", findings),
            "owner": owner or "product_owner",
            "falsified_if": "该动作无法复现问题，或反证条件被满足",
            "stop_condition": "预算/时间窗用尽，或反证条件成立时停止并重审",
            "cost": "low",
            "requires": "无（离线）",
            "status": "proposed",
        })
    for item in (review_payload.get("items") or [])[:10]:
        if not isinstance(item, dict) or item.get("status") != "fail":
            continue
        if not item.get("next_action"):
            continue
        actions.append({
            "action": _guard_text(str(item["next_action"]), "review.next_action", findings),
            "owner": owner or "product_owner",
            "falsified_if": "修复后审计仍失败",
            "stop_condition": "审计通过即停止",
            "cost": "low",
            "requires": "无（离线）",
            "status": "proposed",
        })
    for gap in chain.get("gaps") or []:
        actions.append({
            "action": _guard_text(f"补证：{gap}", "chain.gaps", findings),
            "owner": owner or "product_owner",
            "falsified_if": "补证材料与该判断矛盾",
            "stop_condition": "该缺口被 assess 关闭",
            "cost": "medium",
            "requires": "需要新的授权来源或被试",
            "status": "proposed",
        })
    if not actions:
        actions.append({
            "action": "登记决定、依据、未知与下一动作；不要自动升级为 validated",
            "owner": owner or "product_owner",
            "falsified_if": "无",
            "stop_condition": "决定被记录即停止",
            "cost": "low",
            "requires": "无（离线）",
            "status": "proposed",
        })
    return actions[:10]


def _prd_acceptance(chain: Dict[str, Any],
                    findings: List[Dict[str, Any]]) -> Dict[str, Any]:
    chain_id = str(chain.get("id") or "chain")
    nodes = chain.get("nodes") if isinstance(chain.get("nodes"), dict) else {}
    feature = nodes.get("feature") if isinstance(nodes.get("feature"), dict) else {}
    product = nodes.get("product") if isinstance(nodes.get("product"), dict) else {}
    checklist: List[Dict[str, Any]] = []
    for node_name, field_name in (("feature", "acceptance_conditions"),
                                  ("product", "acceptance_criteria")):
        node = feature if node_name == "feature" else product
        for index, statement in enumerate(node.get(field_name) or []):
            checklist.append({
                "id": f"{chain_id}.{node_name}.{field_name}[{index}]",
                "statement": _guard_text(
                    str(statement), f"{node_name}.{field_name}", findings),
                "source_field": field_name,
                "source_node": node_name,
                "source_ref": f"{CANONICAL_REF}#chains/{chain_id}/nodes/{node_name}",
                "evidence_ids": list(node.get("evidence_ids") or []),
                "implementation_status": "unknown",
                "note": "研究侧验收参数；勾选完成不等于需求已验证、工程放行或发布就绪",
            })
    return {
        "checklist": checklist,
        "undefined": not checklist,
        "non_goals": [_guard_text(str(item), "business.non_goals", findings)
                      for item in product.get("non_goals") or []],
        "linked_issues": [],
        "note": (
            "验收清单为空：主链尚未写 acceptance_conditions / acceptance_criteria；"
            "这是尚未定义，不是没有验收。" if not checklist else
            "验收清单与 PRD 原字段一致（acceptance_conditions / acceptance_criteria），"
            "每条可追溯到 product-reasoning.json#chains/<id>/nodes/<node>；"
            "工程实现标准与放行决定由研发另行制定。"
        ),
    }


# --------------------------------------------------------------------------- #
# A22 / A23: numbers and fabrication guard
# --------------------------------------------------------------------------- #

def _guard_text(text: str, field: str, findings: List[Dict[str, Any]],
                *, redact: bool = True) -> str:
    """A22 second pass: free text copied into the brief is scanned for numbers.

    ``numbers[]`` only covers structured business fields. Free text (cost drivers,
    non-goals, statements, rationales) is also copied, so a number there is either
    withheld with a redaction marker or it silently bypasses the A22 guard (D5).
    """
    value = str(text or "")
    hits = _UNVERIFIED_NUMBER.findall(value)
    if not hits:
        return value
    findings.append({
        "field": field,
        "numbers": sorted(set(hits)),
        "excerpt": value[:200],
        "reason": "自由文本中的数字没有单位/窗口/来源，不进入 numbers[]；已标注未核验",
    })
    return _UNVERIFIED_NUMBER.sub(REDACTION, value) if redact else value


def _number_entry(kind: str, item: Dict[str, Any],
                  problems: List[str]) -> Dict[str, Any]:
    value = item.get("value")
    unit = str(item.get("unit") or "").strip()
    window = str(item.get("time_window") or item.get("window") or "").strip()
    source = str(item.get("source_ref") or "").strip()
    metric = str(item.get("metric") or item.get("metric_id") or "").strip() or "未命名指标"
    entry = {
        "kind": kind,
        "metric": metric,
        "value": value,
        "unit": unit,
        "time_window": window,
        "source_ref": source,
        "formula": str(item.get("formula") or ""),
        "population_definition": str(item.get("population_definition") or ""),
        "status": str(item.get("status") or ""),
        "unavailable_reason": "",
    }
    if value is None:
        entry["unavailable_reason"] = "未测量；null 不是 0"
        return entry
    if isinstance(value, str) or isinstance(value, bool):
        # Prose is not a number: keep it out of the numeric projection and out of
        # the unprovenanced list, but say why no number was emitted.
        entry["value"] = None
        entry["unavailable_reason"] = "value 不是数值（原文为说明性文本）"
        return entry
    missing = [name for name, raw in (("unit", unit), ("time_window", window),
                                      ("source_ref", source)) if not raw]
    if missing:
        entry["value"] = None
        entry["unavailable_reason"] = "缺少 " + ", ".join(missing) + "；数字不予输出"
        problems.append(metric)
    return entry


def _numbers(business: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    problems: List[str] = []
    entries: List[Dict[str, Any]] = []
    for estimate in business.get("market_estimates") or []:
        if isinstance(estimate, dict):
            entries.append(_number_entry("market_estimate", estimate, problems))
    for item in business.get("unit_economics_inputs") or []:
        if isinstance(item, dict):
            entries.append(_number_entry("unit_economics_input", item, problems))
    for metric in business.get("success_metrics") or []:
        if not isinstance(metric, dict):
            continue
        entries.append({
            "kind": "success_metric",
            "metric": str(metric.get("metric_id") or "未命名指标"),
            "value": None,
            "unit": str(metric.get("unit") or ""),
            "time_window": str(metric.get("window") or ""),
            "source_ref": str(metric.get("source_ref") or ""),
            "formula": str(metric.get("definition") or ""),
            "population_definition": str(metric.get("denominator") or ""),
            "status": "predeclared",
            "unavailable_reason": "目标值是预先声明的门槛，不是已测量结果；null 不是 0",
        })
    return entries, problems


def _research_facts(study: Dict[str, Any], records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Canonical facts only. Unknown stays null, never 0 and never invented."""
    facts: Dict[str, Any] = {key: None for key in RESEARCH_FACT_KEYS}
    facts["basis"] = "canonical_artifacts_only"
    facts["note"] = (
        "研究事实只从 study.json / evidence 记录读取；没有就是 null（未知），"
        "不生成访谈人数、转化率或市场规模"
    )
    return facts


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #

def build(study_dir: Path, *, task_id: str = "", question: str = "",
          review_payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Project the canonical chain into one ``askovo.decision-brief/1`` document."""
    study_dir = Path(study_dir).resolve()
    study = _load(study_dir / "study.json")
    if not isinstance(study, dict):
        raise BriefError(f"study.json not found or unreadable under {study_dir}",
                         "INPUT_REQUIRED", "run `askovo do` first")
    reasoning = _load(study_dir / CANONICAL_REF)
    judgments = _load(study_dir / "04-findings" / "demand-judgments.json")
    judgments = [item for item in judgments if isinstance(item, dict)] \
        if isinstance(judgments, list) else []
    chains = _chains(reasoning)
    if not chains:
        raise BriefError(
            "canonical product-reasoning.json has no chain; a brief would have nothing to project",
            "INPUT_REQUIRED", "run `askovo chain STUDY` and write the seven-node chain first")
    chain = chains[0]
    records = _records(study_dir)
    record_by_id = {str(item.get("record_id")): item for item in records if item.get("record_id")}
    findings: List[Dict[str, Any]] = []
    recorded_review = _load(study_dir / REVIEW_REF)
    # The brief projects the **recorded** review; it only generates one when none
    # exists. Regenerating it would refresh the fingerprints and erase the very
    # drift it is supposed to detect (D4).
    review_payload = review_payload if isinstance(review_payload, dict) else (
        recorded_review if isinstance(recorded_review, dict)
        else decision_review.review(study_dir))
    audit = research_loop.cli_module().audit_payload(study_dir)
    claims = [item for item in audit.get("claims") or [] if isinstance(item, dict)]
    supported = sum(1 for claim in claims if claim.get("verdict") == "supported")

    reasons = stale_reasons(
        study_dir, chains, judgments, set(record_by_id),
        previous_fingerprints=((recorded_review or {}).get("input_fingerprints") or {}).get(
            "evidence") if isinstance(recorded_review, dict) else None)
    # A study may carry several chains (one per candidate); a counter-evidence on
    # any of them challenges the decision, so the signal unions them all instead
    # of only looking at the first chain.
    all_counter_ids: List[str] = []
    for item in chains:
        all_counter_ids.extend(str(value) for value in item.get("counter_evidence_ids") or [])
    signal = review_signal(chain, extra_counter_ids=all_counter_ids)
    counter_ids = signal["counter_evidence_ids"]
    needs_re_review = signal["needs_re_review"]

    # A19: a decision with no evidence behind it (nothing cited, or no audited
    # support) can only hold. It must never be rendered as a validated recommendation.
    cited = [value for value in _chain_evidence_ids(chain) if value in record_by_id]
    grounded = bool(cited) and supported > 0
    nodes = chain.get("nodes") if isinstance(chain.get("nodes"), dict) else {}
    business = nodes.get("business") if isinstance(nodes.get("business"), dict) else {}
    recommendation_kind = _recommendation(chain, supported=supported if grounded else 0,
                                          recommended_option_id=None)["kind"]
    recommended_option_id = _recommended_option_id(study, chain, recommendation_kind)
    recommendation = _recommendation(chain, supported=supported if grounded else 0,
                                     recommended_option_id=recommended_option_id)
    recommendation["statement"] = _guard_text(
        recommendation["statement"], "business.statement", findings)
    # The business statement is the canonical claim behind the recommendation; the
    # gate decision may shadow it in the brief, so scan it too rather than letting a
    # number hide behind the shadowed field.
    _guard_text(str(business.get("statement") or ""), "business.statement", findings,
                redact=False)
    # Rationales are not copied into the brief, but a number there is still an
    # unprovenanced claim: record it so the boundary is visible.
    for node_name, node in (chain.get("nodes") or {}).items():
        if isinstance(node, dict):
            _guard_text(str(node.get("rationale") or ""), f"node.{node_name}.rationale",
                        findings, redact=False)

    options, rejected_options = _options(study, chain, recommended_option_id, findings)
    numbers, number_problems = _numbers(business)
    prd_acceptance = _prd_acceptance(chain, findings)
    prd_acceptance["linked_issues"] = [
        str(item) for item in (study.get("decision") or {}).get("linked_issues") or []
        if str(item).strip()
    ]
    decision = study.get("decision") if isinstance(study.get("decision"), dict) else {}
    owner = decision.get("owner")

    if needs_re_review:
        decision_status = "needs_review"
    elif recommendation_kind == "hold":
        decision_status = "hold"
    elif recommendation_kind == "needs_validation":
        decision_status = "needs_validation"
    else:
        decision_status = "ready"

    stale = bool(reasons)
    artifact_status = "stale" if stale else "partial"
    reason_code = "STALE_SOURCE" if stale else "ARTIFACT_PARTIAL"
    supporting_states = chain.get("supporting_states") if isinstance(
        chain.get("supporting_states"), dict) else {}
    outcome = supporting_states.get("outcome") if isinstance(
        supporting_states.get("outcome"), dict) else {}
    causal = supporting_states.get("causal") if isinstance(
        supporting_states.get("causal"), dict) else {}
    delivery_state = "blocked" if stale else "partial"
    states = {
        "decision_state": "not_approved",
        "delivery_state": delivery_state,
        "outcome_state": str(outcome.get("status") or "not_measured").replace("-", "_"),
        "causality_state": str(causal.get("status") or "not_claimed").replace("-", "_"),
        "independent": True,
        "note": (
            "四态彼此独立：decision_state 只表示是否有人批准；delivery_state 只表示交付物是否"
            "可交付；outcome_state 只表示观察到的结果；causality_state 只表示因果是否被声明"
        ),
    }

    limitations = list(LIMITATION_SAMPLES)
    for scope_item in (study.get("scope") or {}).get("prohibited_inferences") or []:
        limitations.append(f"禁止推断：{scope_item}")
    if not records:
        limitations.append("没有任何证据记录；不能推出总体、付费或因果结论")
    if not supported:
        limitations.append("没有通过审计的支持判断；结论只能是 hold，不能是 validated")
    if recommendation_kind == "needs_validation":
        limitations.append("主链尚未 decided；当前只能等待验证，不能当作已批准")
    if number_problems:
        limitations.append("存在缺少单位/窗口/来源的数字：" + ", ".join(number_problems))
    if findings:
        limitations.append(
            "自由文本中的数字未核验（已在正文标注 " + REDACTION + "）："
            + ", ".join(sorted({str(item["field"]) for item in findings})))
    limitations = list(dict.fromkeys(limitations))

    challenge = None
    if needs_re_review:
        challenge = {
            "counter_evidence_ids": counter_ids,
            "why": ("新的反证材料挑战了当前建议；Brief 标为需重审，不自动覆盖上一次决定，"
                    "也不把支持数当作胜负"),
            "previous_recommendation": recommendation["statement"],
            "previous_decision_state": "not_approved",
            "previous_approved_at": None,
            "next": "人工重审该决定；记录差异、为何需要复审与下一实验",
        }

    document: Dict[str, Any] = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "task_id": task_id or None,
        "study_id": str(study.get("study_id") or ""),
        "generated_at": _now(),
        "canonical_ref": CANONICAL_REF,
        "canonical_refs": [
            str(study_dir / relative) for relative in
            ("study.json", CANONICAL_REF, "04-findings/demand-judgments.json",
             "02-data/evidence.jsonl", "04-findings/loop-candidates.json")
            if (study_dir / relative).is_file()
        ],
        "source_fingerprint": _fingerprint(study_dir),
        "artifact_status": artifact_status,
        "reason_code": reason_code,
        "diagnostic_only": stale,
        # C-01 §3: the contract vocabulary lives on `reason_code` only. The
        # challenged/expired distinction is a **detail** code, so the brief can
        # still say "the content changed under the same id" without inventing an
        # eleventh registry entry.
        "stale_reasons": reasons,
        "input_drift": any(item.get("detail_code") == "INPUT_DRIFT" for item in reasons),
        "decision_status": decision_status,
        "recommended_option_id": recommended_option_id,
        "needs_re_review": needs_re_review,
        "challenge": challenge,
        "question": _question_section(study, chain, question),
        "recommendation": recommendation,
        "options": options,
        "evidence": [
            _evidence_entry(record_by_id[record_id],
                            _qualification(record_by_id[record_id]))
            for record_id in _chain_evidence_ids(chain)
            if record_id in record_by_id and record_id not in counter_ids
        ],
        "counter_evidence": [
            _evidence_entry(record_by_id[record_id],
                            _qualification(record_by_id[record_id]),
                            challenge="反证：与当前建议冲突，需人工裁决")
            for record_id in counter_ids if record_id in record_by_id
        ],
        "limitations": limitations,
        "rejected_options": rejected_options,
        "verification_actions": _verification_actions(chain, review_payload, owner, findings),
        "prd_acceptance": prd_acceptance,
        "states": states,
        "decision_state": states["decision_state"],
        "delivery_state": states["delivery_state"],
        "outcome_state": states["outcome_state"],
        "causality_state": states["causality_state"],
        "numbers": numbers,
        "research_facts": _research_facts(study, records),
        "fabrication": {
            "invented_facts": [],
            "numbers_without_provenance": number_problems,
            "unverified_numbers": findings,
            "checked_numbers": len(numbers),
            "checked_fields": [key for key in RESEARCH_FACT_KEYS],
            "boundary": "只从 canonical 摘录；未出现的访谈人数、转化率、市场规模保持 null",
        },
        "approval": {
            "approved": False,
            "approved_by": None,
            "approval_ref": None,
            "identity_basis": "declaration_only",
            "note": "approval_ref 的身份真实性依赖实际签核机制；CLI 自填人名只算声明",
        },
        "gaps": list(chain.get("gaps") or []) + [
            str(item.get("detail")) for item in (review_payload.get("items") or [])
            if isinstance(item, dict) and item.get("status") == "fail"
        ],
        "next_validation": [],
        "restricted": limitations,
        "review_status": str(review_payload.get("status") or "not_run"),
        "evidence_index": {
            "records": len(records),
            "cited_records": len([value for value in _chain_evidence_ids(chain)
                                  if value in record_by_id]),
            "counter_records": len([value for value in counter_ids if value in record_by_id]),
            "source_families": sorted({
                str(item.get("source_family")) for item in records if item.get("source_family")}),
        },
        "next_required_action": _next_required_action(stale, decision_status),
        "boundary": BOUNDARY,
    }
    document["next_validation"] = document["verification_actions"]
    return document


def _qualification(record: Dict[str, Any]) -> Dict[str, Any]:
    """A-01 orthogonal qualification for one evidence record (read-only)."""
    return sure_engine.qualify_evidence(record)


def _next_required_action(stale: bool, decision_status: str) -> str:
    if stale:
        return ("引用断裂或输入过期：先运行 `askovo review STUDY` 重新生成决策复盘，"
                "修复断链后再交付；当前只有诊断草稿")
    if decision_status == "needs_review":
        return ("决策被反证挑战：人工重审并记录差异、为何需要复审与下一实验；"
                "不要自动覆盖上一次决定")
    if decision_status == "hold":
        return "证据不足：补一条可讨论的行为证据或开展访谈，再重跑 `askovo brief`"
    if decision_status == "needs_validation":
        return "主链尚未 decided：先完成验证动作，再重跑 `askovo brief`"
    return "登记决定、批准记录与下一验证动作；recommendation 不是自动批准"


# --------------------------------------------------------------------------- #
# markdown + write
# --------------------------------------------------------------------------- #

def render_markdown(document: Dict[str, Any]) -> str:
    question = document.get("question") or {}
    recommendation = document.get("recommendation") or {}
    states = document.get("states") or {}
    lines = [
        f"# Decision Brief：{question.get('text') or document.get('study_id')}",
        "",
        f"- 状态：`{document.get('artifact_status')}`"
        f"（reason_code：`{document.get('reason_code') or '-'}`）"
        f"{'；**诊断草稿**，不可正式交付' if document.get('diagnostic_only') else ''}",
        f"- decision_status：`{document.get('decision_status')}`；"
        f"source_fingerprint：`{document.get('source_fingerprint')}`",
        "",
    ]
    if document.get("stale_reasons"):
        lines.extend(["## 为什么是 stale", ""])
        for reason in document["stale_reasons"]:
            lines.append(f"- [{reason.get('detail_code')}] {reason.get('detail')}")
        lines.append("")

    lines.extend([
        f"## 1. {SECTION_TITLES['question']}",
        "",
        f"- 问题：{question.get('text')}",
        f"- 决策负责人：{question.get('decision_owner') or '未登记'}；"
        f"截止：{question.get('deadline') or '未登记'}",
        f"- 时间窗：{question.get('time_window', {}).get('label')}",
        f"- 目标用户：{'；'.join(question.get('scope', {}).get('target_users') or []) or '未登记'}",
        f"- 边界：{'；'.join(question.get('scope', {}).get('prohibited_inferences') or []) or '未登记'}",
        "",
        f"## 2. {SECTION_TITLES['recommendation']}",
        "",
        f"- **{recommendation.get('kind')}**：{recommendation.get('statement')}",
        f"- 这是 recommendation，不是自动批准（not_approved："
        f"{recommendation.get('not_approved')}）；heuristic_score："
        f"{recommendation.get('heuristic_score')}；calibrated：{recommendation.get('calibrated')}",
        "",
        f"## 3. {SECTION_TITLES['options']}",
        "",
    ])
    for option in document.get("options") or []:
        dimensions = option.get("dimensions") or {}
        lines.append(f"### {option.get('id')} · {option.get('statement')}"
                     f"（`{option.get('status')}`）")
        for name in DIMENSIONS:
            lines.append(f"- {name}：{dimensions.get(name)}")
        lines.append(f"- 依据：{option.get('dimensions_basis')}；"
                     f"证据：{', '.join(option.get('evidence_ids') or []) or '无'}")
        lines.append("")
    lines.extend([f"## 4. {SECTION_TITLES['evidence']}", ""])
    for entry in document.get("evidence") or []:
        qualification = entry.get("qualification") or {}
        lines.append(f"- `{entry.get('record_id')}`（{entry.get('source_url') or '无链接'}；"
                     f"采集：{entry.get('collected_at') or '未知'}；"
                     f"语境：{entry.get('context_key') or '未登记'}；"
                     f"资格：{qualification.get('claim_eligibility')} / "
                     f"{qualification.get('behavior_kind')}）")
    if not document.get("evidence"):
        lines.append("- 无支撑证据记录。")
    lines.extend(["", f"### {SECTION_TITLES['counter_evidence']}", ""])
    for entry in document.get("counter_evidence") or []:
        excerpt = entry.get("excerpt") or "（无原文摘录：该记录只有元数据，不补写引文）"
        lines.append(f"- `{entry.get('record_id')}`：{excerpt}")
    if not document.get("counter_evidence"):
        lines.append("- 未记录反证；这不等于没有反证。")
    lines.extend(["", f"## 5. {SECTION_TITLES['limitations']}", ""])
    lines.extend(f"- {item}" for item in document.get("limitations") or [])
    lines.extend(["", f"## 6. {SECTION_TITLES['rejected_options']}", ""])
    for item in document.get("rejected_options") or []:
        lines.append(f"- {item.get('statement')}：{item.get('reason')}")
    if not document.get("rejected_options"):
        lines.append("- 无未选项。")
    lines.extend(["", f"## 7. {SECTION_TITLES['verification_actions']}", ""])
    for item in document.get("verification_actions") or []:
        lines.append(f"- {item.get('action')}（责任人：{item.get('owner')}；"
                     f"证伪条件：{item.get('falsified_if')}；停止条件：{item.get('stop_condition')}）")
    acceptance = document.get("prd_acceptance") or {}
    lines.extend(["", f"## 8. {SECTION_TITLES['prd_acceptance']}", ""])
    if acceptance.get("checklist"):
        for item in acceptance["checklist"]:
            lines.append(f"- [ ] {item.get('statement')}（{item.get('source_field')}；"
                         f"来源：{item.get('source_ref')}）")
    else:
        lines.append("- 验收清单为空：主链尚未定义，不是没有验收。")
    lines.append(f"- 非目标：{'；'.join(acceptance.get('non_goals') or []) or '未登记'}")
    lines.append(f"- 关联 Issue：{'；'.join(acceptance.get('linked_issues') or []) or '未登记'}")
    lines.extend(["", f"## 9. {SECTION_TITLES['states']}", ""])
    for key in ("decision_state", "delivery_state", "outcome_state", "causality_state"):
        lines.append(f"- {key}：`{states.get(key)}`")
    lines.extend([
        "",
        "## 数字与来源",
        "",
    ])
    for entry in document.get("numbers") or []:
        if entry.get("value") is None:
            lines.append(f"- {entry.get('metric')}：未知（{entry.get('unavailable_reason')}）")
        else:
            lines.append(f"- {entry.get('metric')}：{entry.get('value')} {entry.get('unit')}"
                         f"（窗口：{entry.get('time_window')}；来源：{entry.get('source_ref')}）")
    lines.extend([
        "",
        "## 批准",
        "",
        f"- approved：{document.get('approval', {}).get('approved')}；"
        f"approval_ref：{document.get('approval', {}).get('approval_ref') or '无'}",
        f"- {document.get('approval', {}).get('note')}",
        "",
        "## 下一步",
        "",
        f"- {document.get('next_required_action')}",
        "",
        "## 边界",
        "",
        str(document.get("boundary") or ""),
        "",
    ])
    return "\n".join(lines)


def write(study_dir: Path, document: Dict[str, Any],
          output_dir: Optional[Path] = None, *,
          json_name: str = JSON_NAME, md_name: str = MD_NAME) -> Dict[str, Any]:
    """Write the derived JSON + Markdown pair; canonical artifacts stay untouched."""
    study_dir = Path(study_dir).resolve()
    target = Path(output_dir).resolve() if output_dir else study_dir / REPORT_RELATIVE
    target.mkdir(parents=True, exist_ok=True)
    json_path = target / json_name
    md_path = target / md_name
    markdown = render_markdown(document)
    document = dict(document)
    document["markdown"] = markdown
    document["json_path"] = str(json_path)
    document["markdown_path"] = str(md_path)
    json_path.write_text(json.dumps(
        {key: value for key, value in document.items() if key != "markdown"},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")
    return document


def build_and_write(study_dir: Path, *, task_id: str = "", question: str = "",
                    output_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Project and persist in one call."""
    document = build(study_dir, task_id=task_id, question=question)
    return write(study_dir, document, output_dir)
