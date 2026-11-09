"""Readable delivery projections from the canonical seven-node research artifact.

The report file and this summary are two views of the same inputs. This module
never creates or upgrades research claims; missing, stale and audit-failed states
remain explicit in both structured fields and human-readable text.
"""
from __future__ import annotations

import hashlib
import json
import shlex
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CANONICAL_ARTIFACT = "04-findings/product-reasoning.json"
INPUT_FILES = (
    "study.json",
    CANONICAL_ARTIFACT,
    "04-findings/demand-judgments.json",
    "02-data/evidence.jsonl",
    "02-data/normalized.jsonl",
    "01-sources/source-plan.csv",
    "01-sources/collection-summary.json",
    "03-codebook/codebook.csv",
    "method-choice.json",
    "01-sources/role-workbench/workplan.json",
)
FLOW = ("scene", "user", "pain", "need", "feature", "product", "business")
GLOBAL_BOUNDARY = (
    "本摘要与交付物不证明总体发生率、市场规模、真实付费、因果、发布就绪或商业成功；"
    "decided 只记录选择，文本生成不会自动升级为 validated。"
)


def _iso(timestamp: float | None) -> str | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def _input_files(study_dir: Path) -> list[str]:
    """All deterministic report inputs, including analysis funnel projections."""
    relatives = list(INPUT_FILES)
    for pattern in ("02-data/raw/**/*.jsonl", "02-data/screened-*.jsonl"):
        for path in sorted(study_dir.glob(pattern)):
            if path.is_file():
                relatives.append(path.relative_to(study_dir).as_posix())
    return list(dict.fromkeys(relatives))


def _update_file_digest(digest: Any, path: Path) -> None:
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)


def _role_asset_inputs(kind: str) -> list[tuple[str, Path]]:
    if kind not in {"role", "lifecycle"}:
        return []
    assets = Path(__file__).resolve().parents[1] / "assets"
    return [
        ("role-catalog.json", assets / "role-catalog.json"),
        ("industry-contexts.json", assets / "industry-contexts.json"),
    ]


def _fingerprint(study_dir: Path, kind: str = "") -> str:
    digest = hashlib.sha256()
    for relative in _input_files(study_dir):
        path = study_dir / relative
        digest.update(relative.encode("utf-8") + b"\0")
        if path.is_file():
            try:
                _update_file_digest(digest, path)
            except OSError as exc:
                digest.update(("unreadable:" + str(exc)).encode("utf-8"))
        else:
            digest.update(b"<missing>")
        digest.update(b"\0")
    for label, path in _role_asset_inputs(kind):
        digest.update(("asset:" + label).encode("utf-8") + b"\0")
        if path.is_file():
            _update_file_digest(digest, path)
        else:
            digest.update(b"<missing>")
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def _artifact_digest(path: Path) -> str | None:
    digest = hashlib.sha256()
    try:
        _update_file_digest(digest, path)
    except OSError:
        return None
    return "sha256:" + digest.hexdigest()


def _chains(reasoning: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(reasoning, dict):
        return []
    return [item for item in reasoning.get("chains") or [] if isinstance(item, dict)]


def _business(chain: dict[str, Any]) -> dict[str, Any]:
    nodes = chain.get("nodes") if isinstance(chain.get("nodes"), dict) else {}
    value = nodes.get("business") if isinstance(nodes.get("business"), dict) else {}
    return value


def _decision_projection(
    study: dict[str, Any],
    reasoning: dict[str, Any] | None,
    audit_status: str,
) -> list[dict[str, Any]]:
    owner = str((study.get("decision") or {}).get("owner") or "") if isinstance(study.get("decision"), dict) else ""
    result: list[dict[str, Any]] = []
    for chain in _chains(reasoning):
        business = _business(chain)
        gate = business.get("gate") if isinstance(business.get("gate"), dict) else {}
        prioritization = chain.get("prioritization") if isinstance(chain.get("prioritization"), dict) else {}
        statement = business.get("statement")
        if not statement:
            nodes = chain.get("nodes") if isinstance(chain.get("nodes"), dict) else {}
            product = nodes.get("product") if isinstance(nodes.get("product"), dict) else {}
            statement = product.get("statement") or chain.get("title")
        result.append({
            "chain_id": chain.get("id"),
            "status": chain.get("status"),
            "decision": gate.get("decision") or statement,
            "statement": statement,
            "decision_maker": prioritization.get("owner") or gate.get("owner") or owner or None,
            "audit_status": audit_status,
            "audited_recommendation": bool(audit_status == "pass" and chain.get("status") == "decided"),
            "meaning": "产品/商业选择记录，不是发布、因果、付费或商业成功证明",
        })
    return result


def _basis_projection(reasoning: dict[str, Any] | None, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    families = sorted({str(item.get("source_family")) for item in records if item.get("source_family")})
    qualified_ids = {str(item.get("record_id")) for item in records}
    result: list[dict[str, Any]] = []
    for chain in _chains(reasoning):
        nodes = chain.get("nodes") if isinstance(chain.get("nodes"), dict) else {}
        node_basis: list[dict[str, Any]] = []
        cited: list[str] = []
        for name in FLOW:
            node = nodes.get(name) if isinstance(nodes.get(name), dict) else {}
            if not node:
                continue
            ids = [str(value) for value in node.get("evidence_ids") or [] if str(value)]
            cited.extend(ids)
            node_basis.append({
                "node": name,
                "status": node.get("status"),
                "rationale": node.get("rationale"),
                "evidence_ids": ids,
            })
        counter_ids = [str(value) for value in chain.get("counter_evidence_ids") or [] if str(value)]
        cited.extend(counter_ids)
        unresolved = [value for value in dict.fromkeys(cited) if value not in qualified_ids]
        prioritization = chain.get("prioritization") if isinstance(chain.get("prioritization"), dict) else {}
        result.append({
            "chain_id": chain.get("id"),
            "demand_judgment_id": chain.get("demand_judgment_id"),
            "context_key": chain.get("context_key"),
            "counter_evidence_ids": counter_ids,
            "unresolved_evidence_ids": unresolved,
            "unresolved_meaning": "引用未登记为合格证据（采集库或不存在），不得计入依据；审计同样判 unknown evidence",
            "prioritization_rationale": prioritization.get("rationale"),
            "nodes": node_basis,
            "evidence_records": len(records),
            "source_families": families,
            "source_independence": "多个来源族不代表独立观察；来源间相关性未被字符串去重或族名自动排除",
        })
    return result


def _action_projection(
    reasoning: dict[str, Any] | None,
    audit_info: dict[str, Any],
    artifact_exists: bool,
    stale: bool,
    reproduce_command: str,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for check in audit_info.get("checks") or []:
        if isinstance(check, dict) and check.get("status") == "fail":
            actions.append({
                "type": "repair_audit",
                "chain_id": None,
                "action": f"修复 {check.get('id')}：{check.get('detail')}",
            })
    for chain in _chains(reasoning):
        actions.append({
            "type": "next_test",
            "chain_id": chain.get("id"),
            "action": chain.get("next_test") or "未登记下一验证；先记录可证伪的最小研究动作",
        })
    if not artifact_exists or stale:
        actions.insert(0, {"type": "regenerate", "chain_id": None, "action": reproduce_command})
    if not actions:
        actions.append({"type": "record", "chain_id": None, "action": "登记决定、依据、未知与下一动作；不要自动升级为 validated"})
    return actions


def _costs_and_boundaries(
    study: dict[str, Any],
    reasoning: dict[str, Any] | None,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    costs: list[dict[str, Any]] = []
    unknowns: list[str] = []
    for chain in _chains(reasoning):
        chain_id = str(chain.get("id") or "chain")
        business = _business(chain)
        gate = business.get("gate") if isinstance(business.get("gate"), dict) else {}
        costs.append({
            "chain_id": chain_id,
            "cost_drivers": list(business.get("cost_drivers") or []),
            "resource_commitment": gate.get("resource_commitment"),
            "revisit_trigger": gate.get("revisit_trigger"),
        })
        for gap in chain.get("gaps") or []:
            unknowns.append(f"{chain_id}：{gap}")
        for item in business.get("unit_economics_inputs") or []:
            if isinstance(item, dict) and item.get("value") is None:
                unknowns.append(f"{chain_id} 成本/单位经济未知：{item.get('metric') or '未命名输入'}（null 不是 0）")
        for node_name in FLOW:
            nodes = chain.get("nodes") if isinstance(chain.get("nodes"), dict) else {}
            node = nodes.get(node_name) if isinstance(nodes.get(node_name), dict) else {}
            if node and node.get("status") not in {"validated", "rejected", "deprioritized"}:
                unknowns.append(f"{chain_id}.{node_name} 仍为 {node.get('status') or 'unknown'}，不能当作已验证")
    scope = study.get("scope") if isinstance(study.get("scope"), dict) else {}
    boundaries = [GLOBAL_BOUNDARY]
    boundaries.extend(str(item) for item in scope.get("prohibited_inferences") or [])
    if records:
        boundaries.append("公开社区/便利样本只能描述本语料，不能推总体发生率；公开评论不能证明真实付费。")
        boundaries.append("多个来源族/相关性未证明独立；访谈不能推市场规模，报价实验必须记录选择偏差。")
    return {
        "costs": costs,
        "boundaries": list(dict.fromkeys(boundaries)),
        "cost_unknowns": unknowns,
    }


def _text_summary(payload: dict[str, Any]) -> str:
    lines = [
        "# Askovo 交付摘要",
        "",
        f"- 状态：{payload['status']}",
        f"- 产物：{payload['artifact'].get('path') or '无产物'}",
        f"- 审计：{payload['audit_status']}；数据新鲜度：{payload['freshness']['status']}",
        f"- Canonical artifact：{payload['canonical_artifact']}",
        "",
        "## 决定",
        "",
    ]
    if payload["status"] == "no_artifact":
        lines.append("- 无可用产物；不能声称已交付或已审核。")
    if payload["status"] == "stale":
        lines.append("- 产物早于最新 canonical 输入，以下内容不能当作当前结论；先按复现命令重建。")
    if payload["audit_status"] != "pass":
        lines.append(f"- 审计为 {payload['audit_status']}；即使存在 decided 记录，也不是已审核推荐或签收依据。")
    decisions = payload.get("decision") or []
    if decisions:
        for item in decisions:
            lines.append(
                f"- {item.get('chain_id')}：`{item.get('status')}`；{item.get('decision') or '未登记决定'}"
                f"；决策人：{item.get('decision_maker') or '未记录'}"
            )
    else:
        lines.append("- 尚无七节点链上的产品/商业决定；保持假设与 unknowns，不自动文本生成 validated。")
    lines.extend(["", "## 依据", ""])
    basis = payload.get("basis") or []
    if basis:
        for item in basis:
            evidence_ids: list[str] = []
            for node in item.get("nodes") or []:
                evidence_ids.extend(str(value) for value in node.get("evidence_ids") or [])
            unresolved = [str(value) for value in item.get("unresolved_evidence_ids") or []]
            basis_ids = [value for value in dict.fromkeys(evidence_ids) if value not in unresolved]
            counter_ids = [str(value) for value in item.get("counter_evidence_ids") or []]
            counter_basis = [value for value in counter_ids if value not in unresolved]
            unresolved_line = (
                f"；未评级引用 {', '.join(unresolved)}（不计入依据，审计判 unknown evidence）"
                if unresolved
                else ""
            )
            lines.append(
                f"- {item.get('chain_id')}：需求判断 `{item.get('demand_judgment_id') or '未关联'}`；"
                f"证据 {', '.join(basis_ids) or '无'}；反证 {', '.join(counter_basis) or '未记录'}"
                f"{unresolved_line}"
            )
            lines.append(f"  - 优先级依据：{item.get('prioritization_rationale') or '未记录'}；{item.get('source_independence')}")
    else:
        lines.append("- 无可用七节点依据。")
    lines.extend(["", "## 行动", ""])
    lines.extend(f"- [{item.get('type')}] {item.get('chain_id') or '研究层面'}：{item.get('action')}" for item in payload.get("actions") or [])
    lines.extend(["", "## 成本与边界", ""])
    costs = payload.get("costs_and_boundaries", {}).get("costs") or []
    if costs:
        for item in costs:
            lines.append(
                f"- {item.get('chain_id')}：成本驱动 {json.dumps(item.get('cost_drivers') or [], ensure_ascii=False)}；"
                f"资源承诺：{item.get('resource_commitment') or '未知'}；复审：{item.get('revisit_trigger') or '未知'}"
            )
    else:
        lines.append("- 成本与资源承诺未知；未知不按 0 处理。")
    lines.extend(f"- 边界：{item}" for item in payload.get("costs_and_boundaries", {}).get("boundaries") or [])
    lines.extend(["", "## Unknowns", ""])
    unknowns = payload.get("unknowns") or []
    lines.extend(f"- {item}" for item in unknowns) if unknowns else lines.append("- 未登记；这不等于没有未知。")
    lines.extend([
        "",
        "## 复现与新鲜度",
        "",
        f"- input_fingerprint：`{payload['input_fingerprint']}`",
        f"- freshness：`{json.dumps(payload['freshness'], ensure_ascii=False)}`",
        f"- reproduce_command：`{payload['reproduce_command']}`",
        "",
    ])
    return "\n".join(lines)


def build_chat_summary(
    study_dir: Path,
    kind: str,
    result: dict[str, Any],
    *,
    study: dict[str, Any] | None,
    reasoning: dict[str, Any] | None,
    evidence: dict[str, Any] | None,
    audit_info: dict[str, Any] | None,
) -> dict[str, Any]:
    """Project one result with explicit no-artifact/audit/stale behavior."""
    study_dir = Path(study_dir).resolve()
    study = study if isinstance(study, dict) else {}
    evidence = evidence if isinstance(evidence, dict) else {}
    records = [item for item in evidence.get("records") or [] if isinstance(item, dict)]
    audit_info = audit_info if isinstance(audit_info, dict) else {"status": "not_run", "checks": []}
    audit_status = str(audit_info.get("status") or "not_run")
    command_parts = ["askovo", "deliver", str(study_dir), "--kind", str(kind)]
    if kind == "role":
        for flag, key in (("--role", "role_id"), ("--deliverable", "deliverable_id"), ("--industry", "industry_id"), ("--chain", "chain_id")):
            value = result.get(key)
            if key == "chain_id" and not value:
                value = (result.get("projected_chain_ids") or [None])[0]
            if value:
                command_parts.extend([flag, str(value)])
    reproduce_command = shlex.join(command_parts)

    artifact_value = result.get("path")
    artifact_path = None
    if artifact_value:
        artifact_path = Path(str(artifact_value))
        if not artifact_path.is_absolute():
            artifact_path = study_dir / artifact_path
        artifact_path = artifact_path.resolve()
    artifact_exists = bool(artifact_path and artifact_path.is_file())
    input_mtimes: dict[str, float] = {}
    for relative in _input_files(study_dir):
        path = study_dir / relative
        if path.is_file():
            try:
                input_mtimes[relative] = path.stat().st_mtime
            except OSError:
                continue
    for label, path in _role_asset_inputs(kind):
        if path.is_file():
            try:
                input_mtimes["asset:" + label] = path.stat().st_mtime
            except OSError:
                continue
    latest_input = max(input_mtimes.values()) if input_mtimes else None
    artifact_mtime = artifact_path.stat().st_mtime if artifact_exists and artifact_path else None
    stale_inputs = sorted(
        relative for relative, timestamp in input_mtimes.items()
        if artifact_mtime is not None and timestamp > artifact_mtime + 0.000001
    )
    stale = bool(artifact_exists and stale_inputs)
    freshness_status = "no_artifact" if not artifact_exists else ("stale" if stale else "fresh")
    if not artifact_exists:
        status = "no_artifact"
    elif stale:
        status = "stale"
    elif result.get("status") == "error":
        status = "error"
    elif audit_status != "pass":
        status = "audit_failed"
    else:
        status = str(result.get("status") or "written")

    costs_and_boundaries = _costs_and_boundaries(study, reasoning, records)
    unknowns = list(costs_and_boundaries.pop("cost_unknowns"))
    if not (study_dir / "study.json").is_file():
        unknowns.insert(0, "study.json 缺失或不可读，决定与范围未知")
    if reasoning is None:
        unknowns.append("canonical product-reasoning.json 缺失或不可读，七节点判断未知")
    if not records:
        unknowns.append("没有可用证据记录；这不等于没有需求，也不能推出总体或付费结论")
    if audit_status == "not_run":
        unknowns.append("full audit 未运行，结构门槛状态未知")
    failed_checks = [item for item in audit_info.get("checks") or [] if isinstance(item, dict) and item.get("status") == "fail"]
    artifact_title = None
    if artifact_exists and artifact_path:
        try:
            artifact_title = next(
                (line.lstrip("# ").strip() for line in artifact_path.read_text(encoding="utf-8", errors="ignore").splitlines()
                 if line.startswith("#")),
                None,
            )
        except OSError:
            artifact_title = None
    payload: dict[str, Any] = {
        "kind": "askovo.delivery-chat-summary",
        "schema_version": "1.0",
        "status": status,
        "deliverable_kind": kind,
        "study_id": study.get("study_id"),
        "canonical_artifact": CANONICAL_ARTIFACT,
        "artifact": {
            "path": str(artifact_path) if artifact_path else None,
            "exists": artifact_exists,
            "title": artifact_title,
            "sha256": _artifact_digest(artifact_path) if artifact_path else None,
        },
        "audit_status": audit_status,
        "audit_failures": [
            {"id": item.get("id"), "detail": item.get("detail")} for item in failed_checks
        ],
        "decision": _decision_projection(study, reasoning, audit_status),
        "basis": _basis_projection(reasoning, records),
        "actions": _action_projection(reasoning, audit_info, artifact_exists, stale, reproduce_command),
        "costs_and_boundaries": costs_and_boundaries,
        "unknowns": list(dict.fromkeys(unknowns)),
        "input_fingerprint": _fingerprint(study_dir, kind),
        "freshness": {
            "status": freshness_status,
            "artifact_mtime": _iso(artifact_mtime),
            "latest_input_mtime": _iso(latest_input),
            "stale_inputs": stale_inputs,
        },
        "reproduce_command": reproduce_command,
        "boundary": GLOBAL_BOUNDARY,
    }
    payload["text"] = _text_summary(payload)
    return payload
