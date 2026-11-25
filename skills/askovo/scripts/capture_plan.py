"""A bounded capture plan turns one chain's ``next_test`` into an authorized brief.

``askovo capture plan`` is the planning layer above ``askovo capture page``. It
copies a chain's source snapshot (``next_test``, ``gaps``, node states,
counter-evidence ids, chain hash) into an immutable record, requires explicit
consent boundaries, stop conditions and a named review before authorization,
and accepts imported notes only as **candidates**.

Unreviewed candidates never carry an evidence level (``evidence_level=None``), never move
a verdict (``verdict_effect="none"``), and are never registered into
``02-data/evidence.jsonl``. The named-human ``review-candidate`` transaction is
the only route from a candidate to a separate canonical evidence record.

Every rendered document treats external text as data: ``<``/``>``/``&`` are
escaped, so a note that looks like an instruction stays a string.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import sure_engine

SCHEMA = "askovo.evidence-capture-plan/1"
CANDIDATE_SCHEMA = "askovo.evidence-capture-candidates/1"
GENERATOR = "skills.askovo.scripts.capture_plan"
GENERATOR_VERSION = "1"

CANONICAL_REF = "04-findings/product-reasoning.json"
PLANS_SUBDIR = Path("04-findings/capture-plans")
STUDY_REF = "study.json"

STATES = ("draft", "needs_review", "authorized", "collecting",
          "candidates_ready", "closed", "cancelled", "stale")
OPEN_STATES = ("draft", "needs_review", "authorized", "collecting", "candidates_ready")
IMPORT_STATES = ("authorized", "collecting", "candidates_ready")
METHODS = ("interview", "survey", "diary", "task_observation")
REVIEW_DECISIONS = ("approve", "reject")

# A change to any of these invalidates the recorded authorization.
SCOPE_FIELDS = ("study_ref", "chain_id", "context_key", "objective",
                "research_question", "methods", "target_participants", "consent",
                "stop_conditions", "triggers", "window")
EDITABLE_FIELDS = ("objective", "research_question", "methods",
                   "target_participants", "consent", "stop_conditions",
                   "triggers", "window")

CANDIDATE_COLUMNS = (
    "candidate_id", "context_key", "behavior_ref", "alternative_behavior",
    "consequence", "counter_evidence", "user_voice", "note", "source_ref",
    "collected_at", "consent_ref", "participant_ref",
)

BOUNDARY = (
    "这是一份采集计划，不是证据，也不是判断。候选条目 evidence_level 恒为 null；"
    "采集数量不改变判断等级；只有既有命名人工 capture review 通道可以把候选登记为证据。"
    "计划不发送消息、不预约、不对外采集；导入只写本地文件。"
)

EFFECTS = {
    "evidence": "none",
    "verdict": "none",
    "delivery": "none",
    "canonical": "none",
    "outbound": "none",
}


class CapturePlanError(ValueError):
    """A capture-plan rule was violated; carries a stable reason code."""

    def __init__(self, message: str, reason_code: str = "INTERNAL_ERROR",
                 suggestion: str = "") -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.suggestion = suggestion
        self.missing: List[str] = []


def _now() -> str:
    return sure_engine.now()


def _sha_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _esc(value: Any) -> str:
    text = "" if value is None else str(value)
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _cell(value: Any) -> str:
    return _esc(value).replace("|", "\\|").replace("\n", " ").strip()


def _as_str(value: Any) -> str:
    return "" if value is None else str(value)


def _csv_cell(value: Any) -> str:
    """Guard a CSV cell against spreadsheet formula injection."""
    text = _as_str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def _clean_list(value: Any) -> List[str]:
    return [item.strip() for item in _as_list(value) if item.strip()]


def _deepcopy(plan: Dict[str, Any]) -> Dict[str, Any]:
    return copy.deepcopy(plan)


def load_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_plan(path: Path) -> Dict[str, Any]:
    payload = load_json(Path(path))
    if not isinstance(payload, dict):
        raise CapturePlanError(
            f"capture plan must be a JSON object: {path}", "PLAN_INVALID",
            "重建计划：askovo capture plan build")
    problems = validate_plan(payload)
    if problems:
        raise CapturePlanError(
            "capture plan failed validation: " + "; ".join(problems),
            "PLAN_INVALID")
    return payload


def validate_plan(plan: Dict[str, Any]) -> List[str]:
    problems: List[str] = []
    if not isinstance(plan, dict):
        return ["plan is not a JSON object"]
    if plan.get("schema") != SCHEMA:
        problems.append(f"schema must be {SCHEMA}")
    if not _as_str(plan.get("plan_id")).strip():
        problems.append("plan_id is missing")
    if plan.get("state") not in STATES:
        problems.append(f"state {plan.get('state')!r} is not one of {STATES}")
    for field in ("study_ref", "chain_id", "context_key", "objective"):
        if not _as_str(plan.get(field)).strip():
            problems.append(f"{field} is missing")
    source = plan.get("source")
    if not isinstance(source, dict) or not _as_str(source.get("chain_hash")).strip():
        problems.append("source.chain_hash is missing")
    methods = plan.get("methods")
    if not isinstance(methods, list) or any(m not in METHODS for m in methods):
        problems.append(f"methods must be a list drawn from {METHODS}")
    participants = plan.get("target_participants")
    if not isinstance(participants, dict) or set(
            ("segment", "criteria", "count")) - set(participants):
        problems.append("target_participants must carry segment/criteria/count")
    consent = plan.get("consent")
    if not isinstance(consent, dict) or set(
            ("boundary", "recording", "withdrawal", "data_handling")) - set(consent):
        problems.append("consent must carry boundary/recording/withdrawal/data_handling")
    for field in ("stop_conditions", "triggers"):
        if not isinstance(plan.get(field), list):
            problems.append(f"{field} must be a list")
    window = plan.get("window")
    if not isinstance(window, dict) or set(("start", "end")) - set(window):
        problems.append("window must carry start/end")
    if plan.get("verdict_effect") != "none":
        problems.append("verdict_effect must stay 'none'")
    for index, candidate in enumerate(plan.get("candidates") or []):
        if not isinstance(candidate, dict):
            problems.append(f"candidate {index} is not an object")
            continue
        if candidate.get("evidence_level") is not None:
            problems.append(f"candidate {index} carries an evidence level")
        if candidate.get("state") not in ("candidate", "accepted", "rejected"):
            problems.append(f"candidate {index} has unknown review state")
    if not isinstance(plan.get("review", []), list):
        problems.append("review must be a list")
    if not isinstance(plan.get("change_log", []), list):
        problems.append("change_log must be a list")
    return problems


def _hashable(plan: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in plan.items()
            if key not in ("created_at", "updated_at", "change_log")}


def plan_hash(plan: Dict[str, Any]) -> str:
    """Content hash used for build idempotency and version conflicts."""
    return _sha_text(_canonical(_hashable(plan)))


def _scope_projection(plan: Dict[str, Any]) -> Dict[str, Any]:
    return {field: plan.get(field) for field in SCOPE_FIELDS}


def scope_hash(plan: Dict[str, Any]) -> str:
    """Authorization scope hash; candidates and timestamps are excluded."""
    return _sha_text(_canonical(_scope_projection(plan)))


def _read_reasoning(study_dir: Path) -> Dict[str, Any]:
    path = Path(study_dir) / CANONICAL_REF
    if not path.exists():
        raise CapturePlanError(
            f"missing {CANONICAL_REF}; run `askovo chain` first",
            "CANONICAL_MISSING")
    try:
        payload = load_json(path)
    except (OSError, ValueError) as exc:
        raise CapturePlanError(
            f"cannot read {CANONICAL_REF}: {type(exc).__name__}: {exc}",
            "CANONICAL_INVALID")
    if not isinstance(payload, dict):
        raise CapturePlanError(
            f"{CANONICAL_REF} must be a JSON object", "CANONICAL_INVALID")
    return payload


def _study_identity(study_dir: Path) -> Dict[str, str]:
    root = Path(study_dir)
    identity = {"study_id": root.name, "study_title": ""}
    path = root / STUDY_REF
    if path.exists():
        try:
            document = load_json(path)
        except (OSError, ValueError):
            document = {}
        if isinstance(document, dict):
            identity["study_id"] = (
                _as_str(document.get("study_id")) or root.name)
            identity["study_title"] = _as_str(document.get("title"))
    return identity


def _pick_chain(reasoning: Dict[str, Any], chain_id: str) -> Dict[str, Any]:
    wanted = _as_str(chain_id).strip()
    if not wanted:
        raise CapturePlanError("--chain is required", "CHAIN_REQUIRED")
    chains = reasoning.get("chains")
    if not isinstance(chains, list):
        raise CapturePlanError(
            f"{CANONICAL_REF} chains must be an array", "CANONICAL_INVALID")
    for chain in chains:
        if isinstance(chain, dict) and _as_str(chain.get("id")) == wanted:
            return chain
    raise CapturePlanError(
        f"chain {wanted!r} not found in {CANONICAL_REF}", "CHAIN_NOT_FOUND",
        "先运行 askovo chain，或选择已存在的 chain id")


def _chain_snapshot(chain: Dict[str, Any], chain_id: str) -> Dict[str, Any]:
    nodes = chain.get("nodes") if isinstance(chain.get("nodes"), dict) else {}
    node_states: Dict[str, Dict[str, Any]] = {}
    for name, node in nodes.items():
        if not isinstance(node, dict):
            continue
        node_states[str(name)] = {
            "status": _as_str(node.get("status")),
            "evidence_ids": _as_list(node.get("evidence_ids")),
        }
    return {
        "chain_ref": f"{CANONICAL_REF}#chains/{chain_id}",
        "next_test": _as_str(chain.get("next_test")),
        "gaps": _as_list(chain.get("gaps")),
        "status": _as_str(chain.get("status")),
        "confidence": _as_str(chain.get("confidence")),
        "supporting_states": copy.deepcopy(
            chain.get("supporting_states") or {}),
        "alternative_explanations": _as_list(
            chain.get("alternative_explanations")),
        "counter_evidence_ids": _as_list(chain.get("counter_evidence_ids")),
        "node_states": node_states,
        "chain_hash": _sha_text(_canonical(chain)),
    }


def _normalize_participants(value: Any) -> Dict[str, Any]:
    payload = value if isinstance(value, dict) else {}
    count = payload.get("count")
    if count in ("", None):
        count = None
    elif isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        raise CapturePlanError(
            "target_participants.count must be a positive integer or null",
            "PARTICIPANT_COUNT_INVALID")
    return {
        "segment": _as_str(payload.get("segment")).strip(),
        "criteria": _as_str(payload.get("criteria")).strip(),
        "count": count,
    }


def _normalize_consent(value: Any) -> Dict[str, str]:
    payload = value if isinstance(value, dict) else {}
    return {field: _as_str(payload.get(field)).strip()
            for field in ("boundary", "recording", "withdrawal", "data_handling")}


def _normalize_window(value: Any) -> Dict[str, str]:
    payload = value if isinstance(value, dict) else {}
    window = {"start": _as_str(payload.get("start")).strip(),
              "end": _as_str(payload.get("end")).strip()}
    if window["start"] and window["end"] and window["start"] > window["end"]:
        raise CapturePlanError(
            f"window.start {window['start']!r} is after window.end "
            f"{window['end']!r}", "WINDOW_INVALID")
    return window


def _normalize_methods(value: Any) -> List[str]:
    methods = _clean_list(value) or list(METHODS[:2])
    unknown = [method for method in methods if method not in METHODS]
    if unknown:
        raise CapturePlanError(
            f"unknown method(s) {unknown!r}; choose from {METHODS}",
            "METHOD_UNKNOWN")
    return methods


def _plan_id(study_id: str, chain_id: str) -> str:
    digest = hashlib.sha256(f"{study_id}:{chain_id}".encode("utf-8")).hexdigest()
    return "cp-" + digest[:12]


def build_plan(study_dir: Path, chain_id: str, *, plan_version: Any = "1",
               objective: str = "", research_question: str = "",
               methods: Any = None, target_participants: Any = None,
               consent: Any = None, stop_conditions: Any = None,
               triggers: Any = None, window: Any = None,
               at: Optional[str] = None) -> Dict[str, Any]:
    """Read one chain and freeze a draft plan; nothing is written to the study."""
    root = Path(study_dir)
    if not root.exists():
        raise CapturePlanError(f"study directory not found: {root}",
                               "STUDY_NOT_FOUND")
    reasoning = _read_reasoning(root)
    chain = _pick_chain(reasoning, chain_id)
    identity = _study_identity(root)
    snapshot = _chain_snapshot(chain, _as_str(chain.get("id")))
    stamp = _as_str(at).strip() or _now()
    objective_text = _as_str(objective).strip() or snapshot["next_test"].strip()
    if not research_question:
        research_question = (
            "哪种可观察行为会支持或推翻：" + (objective_text or "（未设定）"))
    plan = {
        "schema": SCHEMA,
        "generator": GENERATOR,
        "generator_version": GENERATOR_VERSION,
        "plan_id": _plan_id(identity["study_id"], _as_str(chain.get("id"))),
        "plan_version": _as_str(plan_version).strip() or "1",
        "state": "draft",
        "created_at": stamp,
        "updated_at": stamp,
        "study_ref": STUDY_REF,
        "study_id": identity["study_id"],
        "study_title": identity["study_title"],
        "chain_id": _as_str(chain.get("id")),
        "demand_judgment_id": _as_str(chain.get("demand_judgment_id")),
        "context_key": _as_str(chain.get("context_key")),
        "source": snapshot,
        "objective": objective_text,
        "research_question": _as_str(research_question).strip(),
        "methods": _normalize_methods(methods),
        "target_participants": _normalize_participants(target_participants),
        "consent": _normalize_consent(consent),
        "stop_conditions": _clean_list(stop_conditions),
        "triggers": _clean_list(triggers),
        "window": _normalize_window(window),
        "review": [],
        "authorization": {
            "status": "none",
            "authorized_by": "",
            "authorized_at": "",
            "authorization_ref": "",
            "scope_hash": "",
        },
        "requires_reauthorization": False,
        "candidates": [],
        "counter_evidence": [],
        "last_import": None,
        "change_log": [{
            "seq": 1,
            "at": stamp,
            "actor": "capture_plan.build",
            "action": "build",
            "fields": [],
            "note": f"frozen source snapshot {snapshot['chain_hash']}",
        }],
        "verdict_effect": "none",
        "effects": dict(EFFECTS),
        "boundary": BOUNDARY,
    }
    problems = validate_plan(plan)
    if problems:
        raise CapturePlanError(
            "built plan failed validation: " + "; ".join(problems),
            "PLAN_INVALID")
    return plan


def _append_log(plan: Dict[str, Any], *, at: str, actor: str,
                action: str, fields: Iterable[str] = (),
                note: str = "") -> None:
    log = plan.setdefault("change_log", [])
    log.append({
        "seq": len(log) + 1,
        "at": at,
        "actor": _as_str(actor) or "unknown",
        "action": action,
        "fields": list(fields),
        "note": _as_str(note),
    })


def _require_state(plan: Dict[str, Any], allowed: Iterable[str],
                   action: str) -> None:
    if plan.get("state") in allowed:
        return
    raise CapturePlanError(
        f"{action} is not allowed in state {plan.get('state')!r}; "
        f"allowed: {tuple(allowed)}", "INVALID_STATE")


def _bump_version(version: Any) -> str:
    text = _as_str(version).strip() or "1"
    if text.isdigit():
        return str(int(text) + 1)
    return text + ".1"


def submit_for_review(plan: Dict[str, Any], *, actor: str,
                      at: Optional[str] = None, note: str = "") -> Dict[str, Any]:
    _require_state(plan, ("draft", "needs_review"), "submit_for_review")
    if plan.get("state") == "needs_review":
        return plan
    if not _as_str(actor).strip():
        raise CapturePlanError("submit_for_review needs --actor NAME",
                               "ACTOR_REQUIRED")
    updated = _deepcopy(plan)
    updated["state"] = "needs_review"
    updated["updated_at"] = _as_str(at).strip() or _now()
    _append_log(updated, at=updated["updated_at"], actor=actor,
                action="submit_for_review", note=note)
    return updated


def record_review(plan: Dict[str, Any], *, reviewer: str, decision: str,
                  at: Optional[str] = None, note: str = "",
                  ref: str = "") -> Dict[str, Any]:
    _require_state(plan, ("needs_review",), "record_review")
    reviewer_name = _as_str(reviewer).strip()
    if not reviewer_name:
        raise CapturePlanError(
            "a named human reviewer is required (--reviewer NAME)",
            "NAMED_REVIEW_REQUIRED")
    if decision not in REVIEW_DECISIONS:
        raise CapturePlanError(
            f"review decision must be one of {REVIEW_DECISIONS}",
            "REVIEW_DECISION_INVALID")
    updated = _deepcopy(plan)
    stamp = _as_str(at).strip() or _now()
    review = updated.setdefault("review", [])
    review.append({
        "seq": len(review) + 1,
        "reviewer": reviewer_name,
        "decision": decision,
        "at": stamp,
        "note": _as_str(note),
        "ref": _as_str(ref),
    })
    if decision == "reject":
        updated["state"] = "draft"
    updated["updated_at"] = stamp
    _append_log(updated, at=stamp, actor=reviewer_name,
                action=f"review_{decision}", note=note)
    return updated


def authorize(plan: Dict[str, Any], *, authorized_by: str,
              authorized_at: Optional[str] = None,
              authorization_ref: str = "") -> Dict[str, Any]:
    _require_state(plan, ("needs_review",), "authorize")
    missing: List[str] = []
    if not _as_str(plan.get("objective")).strip():
        missing.append("objective")
    if not _clean_list(plan.get("stop_conditions")):
        missing.append("stop_conditions")
    consent = plan.get("consent") if isinstance(plan.get("consent"), dict) else {}
    if not _as_str(consent.get("boundary")).strip():
        missing.append("consent.boundary")
    approvals = [review for review in plan.get("review") or []
                 if isinstance(review, dict)
                 and review.get("decision") == "approve"
                 and _as_str(review.get("reviewer")).strip()]
    if not approvals:
        missing.append("named_review_approval")
    if not _as_str(authorized_by).strip():
        missing.append("authorized_by")
    if missing:
        error = CapturePlanError(
            "authorization blocked; missing: " + ", ".join(missing),
            "AUTHORIZATION_BLOCKED",
            "补齐停止条件、同意边界并完成具名审核后再授权")
        error.missing = missing
        raise error
    updated = _deepcopy(plan)
    stamp = _as_str(authorized_at).strip() or _now()
    updated["authorization"] = {
        "status": "authorized",
        "authorized_by": _as_str(authorized_by).strip(),
        "authorized_at": stamp,
        "authorization_ref": _as_str(authorization_ref),
        "scope_hash": scope_hash(updated),
    }
    updated["requires_reauthorization"] = False
    updated["state"] = "authorized"
    updated["updated_at"] = stamp
    _append_log(updated, at=stamp, actor=updated["authorization"]["authorized_by"],
                action="authorize", note=_as_str(authorization_ref))
    return updated


def start_collection(plan: Dict[str, Any], *, actor: str,
                     at: Optional[str] = None) -> Dict[str, Any]:
    _require_state(plan, ("authorized", "collecting"), "start_collection")
    if plan.get("state") == "collecting":
        return plan
    if not _as_str(actor).strip():
        raise CapturePlanError("start_collection needs --actor NAME",
                               "ACTOR_REQUIRED")
    updated = _deepcopy(plan)
    stamp = _as_str(at).strip() or _now()
    updated["state"] = "collecting"
    updated["collection_started_at"] = stamp
    updated["updated_at"] = stamp
    _append_log(updated, at=stamp, actor=actor, action="start_collection")
    return updated


def candidate_hash(record: Dict[str, Any]) -> str:
    return _sha_text(_canonical({
        key: record[key] for key in CANDIDATE_COLUMNS if key != "candidate_id"
    }))


def _candidate_record(candidate: Dict[str, Any], *, plan: Dict[str, Any],
                      stamp: str) -> Dict[str, Any]:
    if _as_str(candidate.get("evidence_level")).strip():
        raise CapturePlanError(
            "candidates cannot carry an evidence level; only named review "
            "assigns E0-E2", "EVIDENCE_LEVEL_FORBIDDEN")
    context = _as_str(candidate.get("context_key")).strip()
    if not context:
        raise CapturePlanError(
            f"candidate {candidate.get('candidate_id') or '?'} has no context_key",
            "CONTEXT_MISSING")
    if context != _as_str(plan.get("context_key")).strip():
        raise CapturePlanError(
            f"candidate context {context!r} does not match plan context "
            f"{plan.get('context_key')!r}", "CONTEXT_MISMATCH")
    record = {
        "candidate_id": _as_str(candidate.get("candidate_id")).strip(),
        "context_key": context,
        "behavior_ref": _as_str(candidate.get("behavior_ref")).strip(),
        "behavior_unknown": not _as_str(candidate.get("behavior_ref")).strip(),
        "alternative_behavior": _as_str(
            candidate.get("alternative_behavior")).strip(),
        "consequence": _as_str(candidate.get("consequence")).strip(),
        "counter_evidence": _clean_list(candidate.get("counter_evidence")),
        "user_voice": _as_str(candidate.get("user_voice")),
        "note": _as_str(candidate.get("note")),
        "source_ref": _as_str(candidate.get("source_ref")).strip(),
        "collected_at": _as_str(candidate.get("collected_at")).strip(),
        "consent_ref": _as_str(candidate.get("consent_ref")).strip(),
        "participant_ref": _as_str(candidate.get("participant_ref")).strip(),
        "imported_at": stamp,
        "evidence_level": None,
        "state": "candidate",
        "usable": True,
    }
    record["candidate_hash"] = candidate_hash(record)
    if not record["candidate_id"]:
        record["candidate_id"] = "cand-" + record["candidate_hash"].split(":", 1)[1][:12]
    return record


def import_candidates(plan: Dict[str, Any], candidates: List[Dict[str, Any]],
                      *, at: Optional[str] = None) -> Dict[str, Any]:
    authorization = plan.get("authorization") if isinstance(
        plan.get("authorization"), dict) else {}
    if authorization.get("status") == "withdrawn":
        raise CapturePlanError(
            "authorization was withdrawn; imported candidates are unusable",
            "AUTHORIZATION_WITHDRAWN")
    if plan.get("state") in ("draft", "needs_review"):
        raise CapturePlanError(
            "import requires an authorized plan; submit, review and authorize first",
            "AUTHORIZATION_REQUIRED")
    _require_state(plan, IMPORT_STATES, "import_candidates")
    if not isinstance(candidates, list):
        raise CapturePlanError("candidates must be a JSON array",
                               "CANDIDATES_INVALID")
    stamp = _as_str(at).strip() or _now()
    updated = _deepcopy(plan)
    existing = list(updated.get("candidates") or [])
    ids = {str(item.get("candidate_id")) for item in existing
           if isinstance(item, dict)}
    hashes = {str(item.get("candidate_hash")) for item in existing
              if isinstance(item, dict)}
    added = 0
    duplicates = 0
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            raise CapturePlanError(f"candidate {index} is not an object",
                                   "CANDIDATES_INVALID")
        record = _candidate_record(candidate, plan=updated, stamp=stamp)
        if (record["candidate_id"] in ids
                or record["candidate_hash"] in hashes):
            duplicates += 1
            continue
        existing.append(record)
        ids.add(record["candidate_id"])
        hashes.add(record["candidate_hash"])
        added += 1
    updated["candidates"] = existing
    updated["last_import"] = {
        "at": stamp, "submitted": len(candidates),
        "added": added, "duplicates": duplicates,
    }
    updated["state"] = "candidates_ready"
    updated["updated_at"] = stamp
    _append_log(updated, at=stamp, actor="capture_plan.import",
                action="import_candidates",
                fields=["candidates"],
                note=f"added={added} duplicates={duplicates}")
    return updated


def withdraw_authorization(plan: Dict[str, Any], *, actor: str, reason: str,
                           at: Optional[str] = None) -> Dict[str, Any]:
    authorization = plan.get("authorization") if isinstance(
        plan.get("authorization"), dict) else {}
    if authorization.get("status") != "authorized":
        raise CapturePlanError(
            "only an authorized plan can be withdrawn",
            "AUTHORIZATION_REQUIRED")
    if not _as_str(actor).strip():
        raise CapturePlanError("withdraw needs --actor NAME", "ACTOR_REQUIRED")
    if not _as_str(reason).strip():
        raise CapturePlanError("withdraw needs --reason TEXT", "REASON_REQUIRED")
    updated = _deepcopy(plan)
    stamp = _as_str(at).strip() or _now()
    updated["authorization"]["status"] = "withdrawn"
    updated["authorization"]["withdrawn_by"] = _as_str(actor)
    updated["authorization"]["withdrawn_at"] = stamp
    updated["authorization"]["withdraw_reason"] = _as_str(reason)
    for candidate in updated.get("candidates") or []:
        if isinstance(candidate, dict):
            candidate["usable"] = False
    updated["state"] = "cancelled"
    updated["collection_stopped_at"] = stamp
    updated["updated_at"] = stamp
    _append_log(updated, at=stamp, actor=actor, action="withdraw_authorization",
                note=reason)
    return updated


def close_plan(plan: Dict[str, Any], *, actor: str, at: Optional[str] = None,
               note: str = "") -> Dict[str, Any]:
    if plan.get("state") == "closed":
        return plan
    if not _as_str(actor).strip():
        raise CapturePlanError("close needs --actor NAME", "ACTOR_REQUIRED")
    updated = _deepcopy(plan)
    stamp = _as_str(at).strip() or _now()
    updated["state"] = "closed"
    updated["closed_at"] = stamp
    updated["updated_at"] = stamp
    _append_log(updated, at=stamp, actor=actor, action="close", note=note)
    return updated


def revise_plan(plan: Dict[str, Any], changes: Dict[str, Any], *, actor: str,
                at: Optional[str] = None, note: str = "") -> Dict[str, Any]:
    if plan.get("state") in ("closed", "cancelled"):
        raise CapturePlanError(
            f"cannot revise a plan in state {plan.get('state')!r}",
            "PLAN_CLOSED")
    if not isinstance(changes, dict) or not changes:
        raise CapturePlanError("revise needs a non-empty changes object",
                               "CHANGES_INVALID")
    unknown = sorted(set(changes) - set(EDITABLE_FIELDS))
    if unknown:
        raise CapturePlanError(
            f"fields not editable: {unknown}; editable: {EDITABLE_FIELDS}",
            "FIELD_NOT_EDITABLE")
    if not _as_str(actor).strip():
        raise CapturePlanError("revise needs --actor NAME", "ACTOR_REQUIRED")
    updated = _deepcopy(plan)
    changed: List[str] = []
    for field, value in changes.items():
        if field in ("target_participants", "consent", "window"):
            current = updated.get(field) if isinstance(
                updated.get(field), dict) else {}
            merged = dict(current)
            merged.update(value if isinstance(value, dict) else {})
            if field == "target_participants":
                normalized = _normalize_participants(merged)
            elif field == "consent":
                normalized = _normalize_consent(merged)
            else:
                normalized = _normalize_window(merged)
        elif field == "methods":
            normalized = _normalize_methods(value)
        elif field in ("stop_conditions", "triggers"):
            normalized = _clean_list(value)
        else:
            normalized = _as_str(value).strip()
        if updated.get(field) != normalized:
            updated[field] = normalized
            changed.append(field)
    if not changed:
        return plan
    stamp = _as_str(at).strip() or _now()
    updated["plan_version"] = _bump_version(updated.get("plan_version"))
    authorization = updated.get("authorization") if isinstance(
        updated.get("authorization"), dict) else {}
    if authorization.get("status") == "authorized" and (
            scope_hash(updated) != authorization.get("scope_hash")):
        updated["authorization"] = dict(authorization)
        updated["authorization"]["status"] = "superseded"
        updated["authorization"]["superseded_at"] = stamp
        updated["state"] = "needs_review"
        updated["requires_reauthorization"] = True
    updated["updated_at"] = stamp
    _append_log(updated, at=stamp, actor=actor, action="revise",
                fields=changed, note=note)
    return updated


def record_counter_evidence(plan: Dict[str, Any], evidence: Any, *,
                            at: Optional[str] = None,
                            note: str = "") -> Dict[str, Any]:
    stamp = _as_str(at).strip() or _now()
    if isinstance(evidence, dict):
        record = {
            "ref": _as_str(evidence.get("ref")).strip(),
            "summary": _as_str(evidence.get("summary")),
            "source_ref": _as_str(evidence.get("source_ref")).strip(),
            "observed_at": _as_str(evidence.get("observed_at")).strip(),
        }
    else:
        record = {"ref": "", "summary": _as_str(evidence),
                  "source_ref": "", "observed_at": ""}
    if not (record["summary"].strip() or record["ref"]):
        raise CapturePlanError("counter evidence needs a ref or summary",
                               "COUNTER_EVIDENCE_INVALID")
    updated = _deepcopy(plan)
    record["recorded_at"] = stamp
    record["note"] = _as_str(note)
    record["source_chain_hash"] = (updated.get("source") or {}).get("chain_hash", "")
    updated.setdefault("counter_evidence", []).append(record)
    updated["updated_at"] = stamp
    _append_log(updated, at=stamp, actor="capture_plan.counter_evidence",
                action="record_counter_evidence",
                fields=["counter_evidence"],
                note="snapshot unchanged; verdict_effect stays none")
    return updated


def save_plan(plan: Dict[str, Any], path: Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    return target


def store_plan(plan: Dict[str, Any], out_dir: Path) -> Dict[str, Any]:
    """Persist a freshly built plan with same-id/same-version hash discipline."""
    out = Path(out_dir)
    path = out / "capture-plan.json"
    digest = plan_hash(plan)
    if path.exists():
        existing = load_json(path)
        if isinstance(existing, dict) and existing.get("plan_id") == plan.get("plan_id"):
            if _as_str(existing.get("plan_version")) == _as_str(plan.get("plan_version")):
                if plan_hash(existing) == digest:
                    return {"status": "unchanged", "path": str(path),
                            "plan_hash": digest, "plan": existing}
                raise CapturePlanError(
                    f"plan {plan.get('plan_id')} version "
                    f"{plan.get('plan_version')} already exists with a "
                    "different content hash", "PLAN_VERSION_CONFLICT",
                    "提升 --version 后重新构建；不要覆盖已登记版本")
    save_plan(plan, path)
    return {"status": "created", "path": str(path),
            "plan_hash": digest, "plan": plan}


def candidate_template() -> Dict[str, Any]:
    example = {column: "" for column in CANDIDATE_COLUMNS}
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(CANDIDATE_COLUMNS),
                            lineterminator="\n")
    writer.writeheader()
    return {
        "schema": CANDIDATE_SCHEMA,
        "columns": list(CANDIDATE_COLUMNS),
        "csv": buffer.getvalue(),
        "json": {"schema": CANDIDATE_SCHEMA, "candidates": [example]},
    }


def _header(plan: Dict[str, Any]) -> List[str]:
    return [
        f"# 证据采集计划 {_esc(plan.get('plan_id'))} "
        f"v{_esc(plan.get('plan_version'))}",
        "",
        f"- 状态：{_esc(plan.get('state'))}",
        f"- 研究：{_esc(plan.get('study_id'))}（{_esc(plan.get('study_ref'))}）",
        f"- 链条：{_esc((plan.get('source') or {}).get('chain_ref'))}",
        f"- 链条哈希：{_esc((plan.get('source') or {}).get('chain_hash'))}",
        f"- 情境：{_esc(plan.get('context_key'))}",
        f"- 需求判断：{_esc(plan.get('demand_judgment_id'))}",
        "",
    ]


def _objective_block(plan: Dict[str, Any]) -> List[str]:
    return [
        "## 目标",
        "",
        _esc(plan.get("objective")) or "（未设定）",
        "",
        "## 研究问题",
        "",
        _esc(plan.get("research_question")) or "（未设定）",
        "",
    ]


def _source_block(plan: Dict[str, Any]) -> List[str]:
    source = plan.get("source") if isinstance(plan.get("source"), dict) else {}
    lines = [
        "## 来源快照（构建时冻结，之后永不改写）",
        "",
        f"- next_test：{_esc(source.get('next_test')) or '（缺失）'}",
        f"- 链条状态：{_esc(source.get('status')) or '（缺失）'}",
        f"- 置信度：{_esc(source.get('confidence')) or '（缺失）'}",
    ]
    gaps = source.get("gaps") or []
    lines.append("- 证据缺口：")
    if gaps:
        lines.extend(f"  - {_esc(gap)}" for gap in gaps)
    else:
        lines.append("  - （未登记）")
    node_states = source.get("node_states") or {}
    if node_states:
        lines.append("")
        lines.append("| 节点 | 状态 | 证据 |")
        lines.append("| --- | --- | --- |")
        for name, node in node_states.items():
            evidence = ", ".join(node.get("evidence_ids") or []) or "（无）"
            lines.append(f"| {_cell(name)} | {_cell(node.get('status'))} "
                         f"| {_cell(evidence)} |")
    lines.append("")
    return lines


def _design_block(plan: Dict[str, Any]) -> List[str]:
    participants = plan.get("target_participants") or {}
    count = participants.get("count")
    consent = plan.get("consent") or {}
    window = plan.get("window") or {}
    lines = [
        "## 方法与对象",
        "",
        "- 方法：" + (", ".join(plan.get("methods") or []) or "（未设定）"),
        f"- 对象：{_esc(participants.get('segment')) or '（未设定）'}",
        f"- 纳入标准：{_esc(participants.get('criteria')) or '（未设定）'}",
        f"- 目标数量：{_esc(count) if count is not None else '（未设定）'}",
        f"- 时间窗：{_esc(window.get('start')) or '（未设定）'} → "
        f"{_esc(window.get('end')) or '（未设定）'}",
        "",
        "## 知情同意与边界",
        "",
        f"- 范围边界：{_esc(consent.get('boundary')) or '（缺失，禁止授权）'}",
        f"- 录音：{_esc(consent.get('recording')) or '（缺失）'}",
        f"- 退出方式：{_esc(consent.get('withdrawal')) or '（缺失）'}",
        f"- 数据处理：{_esc(consent.get('data_handling')) or '（缺失）'}",
        "",
        "## 停止条件",
        "",
    ]
    stops = plan.get("stop_conditions") or []
    lines.extend(f"- {_esc(item)}" for item in stops) if stops else lines.append(
        "- （未设定，禁止授权）")
    lines.extend(["", "## 触发条件（改动这些条件需要重新授权）", ""])
    triggers = plan.get("triggers") or []
    lines.extend(f"- {_esc(item)}" for item in triggers) if triggers else lines.append(
        "- （未设定）")
    lines.append("")
    return lines


def _review_block(plan: Dict[str, Any]) -> List[str]:
    authorization = plan.get("authorization") or {}
    lines = ["## 审核与授权", ""]
    reviews = plan.get("review") or []
    if reviews:
        lines.extend(["| # | 审核人 | 决定 | 时间 | 备注 |",
                      "| --- | --- | --- | --- | --- |"])
        for review in reviews:
            lines.append(
                f"| {_cell(review.get('seq'))} | {_cell(review.get('reviewer'))} "
                f"| {_cell(review.get('decision'))} | {_cell(review.get('at'))} "
                f"| {_cell(review.get('note'))} |")
    else:
        lines.append("（暂无具名审核）")
    lines.extend([
        "",
        f"- 授权状态：{_esc(authorization.get('status')) or 'none'}",
        f"- 授权人：{_esc(authorization.get('authorized_by')) or '（无）'}",
        f"- 授权时间：{_esc(authorization.get('authorized_at')) or '（无）'}",
        f"- 授权引用：{_esc(authorization.get('authorization_ref')) or '（无）'}",
        f"- 授权范围哈希：{_esc(authorization.get('scope_hash')) or '（无）'}",
        f"- 是否需重新授权：{'是' if plan.get('requires_reauthorization') else '否'}",
        "",
    ])
    return lines


def render_plan_md(plan: Dict[str, Any]) -> str:
    lines = _header(plan)
    lines.extend(_source_block(plan))
    lines.extend(_objective_block(plan))
    lines.extend(_design_block(plan))
    lines.extend(_review_block(plan))
    lines.extend(["## 候选（不代表证据）", ""])
    candidates = plan.get("candidates") or []
    if candidates:
        lines.extend([
            "| 候选 | 行为锚点 | 替代行为 | 后果 | 反证 | 可用 |",
            "| --- | --- | --- | --- | --- | --- |",
        ])
        for candidate in candidates:
            behavior = (_esc(candidate.get("behavior_ref"))
                        if not candidate.get("behavior_unknown")
                        else "behavior_unknown")
            lines.append(
                f"| {_cell(candidate.get('candidate_id'))} | {_cell(behavior)} "
                f"| {_cell(candidate.get('alternative_behavior'))} "
                f"| {_cell(candidate.get('consequence'))} "
                f"| {_cell('; '.join(candidate.get('counter_evidence') or []))} "
                f"| {'是' if candidate.get('usable') else '否'} |")
    else:
        lines.append("（暂无候选）")
    lines.extend(["", "## 反证", ""])
    counter = plan.get("counter_evidence") or []
    if counter:
        for item in counter:
            lines.append(
                f"- [{_esc(item.get('ref')) or 'ref?'}] "
                f"{_esc(item.get('summary'))} "
                f"（来源：{_esc(item.get('source_ref')) or '未登记'}；"
                f"记录于 {_esc(item.get('recorded_at'))}）")
    else:
        lines.append("（暂无反证）")
    lines.extend(["", "## 变更记录", ""])
    for entry in plan.get("change_log") or []:
        fields = ", ".join(entry.get("fields") or []) or "-"
        lines.append(
            f"- #{_esc(entry.get('seq'))} {_esc(entry.get('at'))} "
            f"{_esc(entry.get('actor'))}：{_esc(entry.get('action'))} "
            f"（{_esc(fields)}）{_esc(entry.get('note'))}")
    lines.extend(["", "## 边界", "", _esc(plan.get("boundary")), ""])
    return "\n".join(lines)


def render_interview_guide(plan: Dict[str, Any]) -> str:
    participants = plan.get("target_participants") or {}
    consent = plan.get("consent") or {}
    lines = _header(plan)
    lines.extend([
        "## 访谈目标（与计划一致）",
        "",
        _esc(plan.get("objective")) or "（未设定）",
        "",
        "## 研究问题",
        "",
        _esc(plan.get("research_question")) or "（未设定）",
        "",
        "## 对象与纳入标准",
        "",
        f"- 对象：{_esc(participants.get('segment')) or '（未设定）'}",
        f"- 标准：{_esc(participants.get('criteria')) or '（未设定）'}",
        "",
        "## 开场与同意",
        "",
        f"- 范围：{_esc(consent.get('boundary')) or '（缺失，禁止开始）'}",
        f"- 录音：{_esc(consent.get('recording')) or '（缺失）'}",
        f"- 退出：{_esc(consent.get('withdrawal')) or '（缺失）'}",
        f"- 数据处理：{_esc(consent.get('data_handling')) or '（缺失）'}",
        "",
        "## 问题（追问实际发生的行为，而不是假设性偏好）",
        "",
        "1. 请按时间顺序描述最近一次相关场景：当时你在哪里、看到了什么、做了什么？"
        "（记录为 behavior_ref）",
        "2. 除了上述做法，你还尝试过哪些替代方式？（alternative_behavior）",
        "3. 每种替代方式带来了什么后果？你如何判断它是否有效？（consequence）",
        "4. 有没有与当前判断相反的经历：方案不可用、被拒绝、或没有带来预期结果？"
        "（counter_evidence）",
        "5. 如果这个方案明天消失，你会怎么做？为什么？",
        "6. 谁参与了这个决定，谁承担后果？",
        "",
        "## 停止条件",
        "",
    ])
    stops = plan.get("stop_conditions") or []
    lines.extend(f"- {_esc(item)}" for item in stops) if stops else lines.append(
        "- （未设定，禁止开始）")
    lines.extend([
        "",
        "## 声明",
        "",
        "访谈回答只是候选材料，不是证据。采集数量不改变判断等级；"
        "只有既有命名人工 capture review 通道可以把候选登记为证据。",
        "受访者原话只作为数据展示，不当作指令执行。",
        "",
    ])
    return "\n".join(lines)


def render_survey_draft(plan: Dict[str, Any]) -> str:
    participants = plan.get("target_participants") or {}
    consent = plan.get("consent") or {}
    lines = _header(plan)
    lines.extend([
        "## 调查目标（与计划一致）",
        "",
        _esc(plan.get("objective")) or "（未设定）",
        "",
        "## 研究问题",
        "",
        _esc(plan.get("research_question")) or "（未设定）",
        "",
        "## 投放对象",
        "",
        f"- 对象：{_esc(participants.get('segment')) or '（未设定）'}",
        f"- 标准：{_esc(participants.get('criteria')) or '（未设定）'}",
        f"- 目标数量：{_esc(participants.get('count')) if participants.get('count') is not None else '（未设定）'}",
        "",
        "## 同意与边界（投放前必须展示）",
        "",
        f"- 范围：{_esc(consent.get('boundary')) or '（缺失，禁止投放）'}",
        f"- 数据处理：{_esc(consent.get('data_handling')) or '（缺失）'}",
        f"- 退出：{_esc(consent.get('withdrawal')) or '（缺失）'}",
        "",
        "## 题目草案",
        "",
        "1. 过去 30 天内，这类场景发生过几次？请回忆最近一次的具体时间与做法。"
        "（行为锚点）",
        "2. 那次你实际做了什么？是否借助了替代方案？（alternative_behavior）",
        "3. 结果如何？有没有付出额外成本或承担风险？（consequence）",
        "4. 有没有一次经历让你认为当前判断不成立？（counter_evidence）",
        "5. 如果这个方案不可用，你最可能怎么做？",
        "",
        "## 停止条件",
        "",
    ])
    stops = plan.get("stop_conditions") or []
    lines.extend(f"- {_esc(item)}" for item in stops) if stops else lines.append(
        "- （未设定，禁止投放）")
    lines.extend([
        "",
        "## 声明",
        "",
        "本调查不发送、不预约、不追踪个体。回答数量不改变判断；"
        "调查结果只是候选材料，必须经具名审核后才可能成为证据。",
        "",
    ])
    return "\n".join(lines)


def write_plan(plan: Dict[str, Any], out_dir: Path) -> Dict[str, str]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    template = candidate_template()
    files = {
        "plan_json": out / "capture-plan.json",
        "plan_md": out / "capture-plan.md",
        "interview_guide": out / "interview-guide.md",
        "survey_draft": out / "survey-draft.md",
        "candidate_csv": out / "candidate-import-template.csv",
        "candidate_json": out / "candidate-import-template.json",
    }
    save_plan(plan, files["plan_json"])
    files["plan_md"].write_text(render_plan_md(plan), encoding="utf-8")
    files["interview_guide"].write_text(render_interview_guide(plan),
                                        encoding="utf-8")
    files["survey_draft"].write_text(render_survey_draft(plan), encoding="utf-8")
    files["candidate_csv"].write_text(template["csv"], encoding="utf-8")
    files["candidate_json"].write_text(
        json.dumps(template["json"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    return {name: str(path) for name, path in files.items()}
