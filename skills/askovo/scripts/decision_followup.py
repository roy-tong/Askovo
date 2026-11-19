"""Decision follow-up: append-only choice, delivery, outcome and causality receipts.

This module records what happened *after* a DecisionRecord was written. It never
edits `04-findings/product-reasoning.json`, never changes an evidence grade,
never promotes a claim because a delivery shipped, and never infers causality
from temporal order. Every follow-up is one appended JSON line; receipts are
read-only projections over those lines plus the original DecisionRecord.
"""
from __future__ import annotations

import hashlib
import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

SCHEMA = "askovo.decision-followup/1"
SCHEMA_VERSION = "1.0"
RECEIPT_KIND = "askovo.decision-followup-receipt"
RECEIPT_SCHEMA_VERSION = "1.0"
FOLLOWUPS_REL = Path("04-findings/decision-followups.jsonl")
REPORT_SUBDIR = Path("06-report/decision-followups")
CHOICE_STATES = ("accepted", "rejected", "deferred")
DELIVERY_STATES = ("unknown", "not_started", "in_progress", "shipped", "blocked")
OUTCOME_STATES = ("unknown", "observed", "not_observed")
CAUSALITY_STATES = ("not_claimed", "designed", "observed_only")
GENERATOR = "askovo.decision_followup"
GENERATOR_VERSION = "1"
EFFECTS = {
    "evidence": "none",
    "verdict": "none",
    "delivery": "none",
    "canonical": "none",
    "outbound": "none",
}
BOUNDARY = (
    "Append-only follow-up projection over one historical DecisionRecord. It records "
    "what an owner reported; it does not verify identity, change the canonical chain or "
    "evidence grades, prove delivery quality, establish causality, or imply commercial "
    "success. Choice, delivery, outcome and causality are separate states."
)


# ---------------------------------------------------------------------------
# Small deterministic helpers
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fingerprint(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def followups_path(study_dir: Path) -> Path:
    return Path(study_dir).resolve() / FOLLOWUPS_REL


def _canonical(study_dir: Path) -> Tuple[Dict[str, Any], Dict[str, Any], Path]:
    study_dir = Path(study_dir).resolve()
    study_path = study_dir / "study.json"
    reasoning_path = study_dir / "04-findings" / "product-reasoning.json"
    if not study_path.is_file():
        raise ValueError("missing study.json under %s" % study_dir)
    if not reasoning_path.is_file():
        raise ValueError("missing 04-findings/product-reasoning.json; run `askovo chain` first")
    study = json.loads(study_path.read_text(encoding="utf-8"))
    reasoning = json.loads(reasoning_path.read_text(encoding="utf-8"))
    if not isinstance(study, dict) or not isinstance(reasoning, dict):
        raise ValueError("study.json and product-reasoning.json must be objects")
    return study, reasoning, reasoning_path


def _records(reasoning: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [item for item in reasoning.get("decision_records") or [] if isinstance(item, dict)]


def _find_record(reasoning: Dict[str, Any], decision_id: str) -> Dict[str, Any]:
    wanted = _text(decision_id)
    if not wanted:
        raise ValueError("follow-up requires --decision with an existing DecisionRecord id")
    for item in _records(reasoning):
        if _text(item.get("record_id")) == wanted:
            return item
    raise ValueError(
        "%s is not a recorded DecisionRecord; record the decision before appending a follow-up" % wanted
    )


def _find_chain(reasoning: Dict[str, Any], chain_id: str) -> Optional[Dict[str, Any]]:
    chains = reasoning.get("chains") if isinstance(reasoning.get("chains"), list) else []
    for chain in chains:
        if isinstance(chain, dict) and _text(chain.get("id")) == _text(chain_id):
            return chain
    return None


def _current_fingerprint(chain: Optional[Dict[str, Any]]) -> str:
    return _fingerprint(chain) if isinstance(chain, dict) else ""


def _normalize_choice(value: Any) -> str:
    state = _text(value).lower()
    if state not in CHOICE_STATES:
        raise ValueError("choice_state must be one of %s" % ", ".join(CHOICE_STATES))
    return state


def _normalize_delivery(value: Any) -> Tuple[str, List[Dict[str, str]]]:
    state = _text(value).lower() or "unknown"
    if state in DELIVERY_STATES:
        return state, []
    return "unknown", [{
        "code": "DELIVERY_STATE_INVALID",
        "axis": "delivery",
        "detail": "delivery_state %r is not one of %s; recorded as unknown" % (state, ", ".join(DELIVERY_STATES)),
    }]


def _normalize_outcome_state(value: Any) -> Tuple[str, List[Dict[str, str]]]:
    state = _text(value).lower() or "unknown"
    if state in OUTCOME_STATES:
        return state, []
    return "unknown", [{
        "code": "OUTCOME_STATE_INVALID",
        "axis": "outcome",
        "detail": "outcome_state %r is not one of %s; recorded as unknown" % (state, ", ".join(OUTCOME_STATES)),
    }]


def _normalize_causality(value: Any) -> Tuple[str, List[Dict[str, str]]]:
    state = _text(value).lower() or "not_claimed"
    if state in CAUSALITY_STATES:
        return state, []
    return "not_claimed", [{
        "code": "CAUSALITY_STATE_INVALID",
        "axis": "causality",
        "detail": "causality_state %r is not one of %s; recorded as not_claimed" % (state, ", ".join(CAUSALITY_STATES)),
    }]


def _check_ref(study_dir: Path, ref: Any, kind: str = "") -> Dict[str, Any]:
    text = _text(ref)
    if not text:
        return {"ref": "", "kind": _text(kind) or "unspecified", "exists": False, "state": "EMPTY_REFERENCE"}
    lowered = text.lower()
    if lowered.startswith(("http://", "https://")):
        return {"ref": text, "kind": _text(kind) or "url", "exists": None, "state": "EXTERNAL_UNVERIFIED"}
    if ":" in text and not text.startswith(("/", "./", "../")):
        return {"ref": text, "kind": _text(kind) or "external", "exists": None, "state": "EXTERNAL_UNVERIFIED"}
    path = Path(text)
    if not path.is_absolute():
        path = Path(study_dir).resolve() / text
    exists = path.exists()
    return {
        "ref": text,
        "kind": _text(kind) or ("file" if path.suffix else "path"),
        "exists": exists,
        "state": "OK" if exists else "BROKEN_REFERENCE",
    }


def _normalize_delivery_refs(
    study_dir: Path, raw_refs: Any, at: str
) -> Tuple[List[Dict[str, Any]], str, List[Dict[str, str]]]:
    refs: List[Dict[str, Any]] = []
    diagnostics: List[Dict[str, str]] = []
    for raw in raw_refs or []:
        if isinstance(raw, dict):
            ref_value = raw.get("ref") or raw.get("path") or raw.get("id") or ""
            kind = _text(raw.get("kind"))
            explicit_exists = raw.get("exists")
        else:
            ref_value = raw
            kind = ""
            explicit_exists = None
        checked = _check_ref(study_dir, ref_value, kind)
        if explicit_exists is False:
            checked["exists"] = False
            checked["state"] = "BROKEN_REFERENCE"
        checked["checked_at"] = at
        refs.append(checked)
        if checked["state"] == "BROKEN_REFERENCE":
            diagnostics.append({
                "code": "BROKEN_REFERENCE",
                "axis": "delivery",
                "detail": "delivery reference %r does not exist; delivery evidence is not sufficient" % checked["ref"],
            })
        elif checked["state"] == "EMPTY_REFERENCE":
            diagnostics.append({
                "code": "DELIVERY_REFERENCE_EMPTY",
                "axis": "delivery",
                "detail": "an empty delivery reference was ignored",
            })
        elif checked["state"] == "EXTERNAL_UNVERIFIED":
            diagnostics.append({
                "code": "DELIVERY_REFERENCE_UNVERIFIED",
                "axis": "delivery",
                "detail": "delivery reference %r cannot be verified locally" % checked["ref"],
            })
    refs = [item for item in refs if item["ref"]]
    if any(item["state"] == "BROKEN_REFERENCE" for item in refs):
        evidence_state = "BROKEN_REFERENCE"
    elif any(item["state"] == "EXTERNAL_UNVERIFIED" for item in refs):
        evidence_state = "UNVERIFIED"
    elif refs:
        evidence_state = "OK"
    else:
        evidence_state = "NO_REFERENCE"
    return refs, evidence_state, diagnostics


def _window_from(value: Any) -> Tuple[Optional[Dict[str, str]], bool]:
    if isinstance(value, dict):
        start = _text(value.get("start") or value.get("window_start"))
        end = _text(value.get("end") or value.get("window_end"))
    elif isinstance(value, (list, tuple)) and len(value) == 2:
        start, end = _text(value[0]), _text(value[1])
    else:
        start = end = ""
    if not start and not end:
        return None, False
    return {"start": start, "end": end}, bool(start and end)


def _normalize_event(
    raw: Any,
    *,
    index: int,
    decision_id: str,
    window_default: Optional[Dict[str, str]],
) -> Tuple[Optional[Dict[str, Any]], List[str], bool]:
    if not isinstance(raw, dict):
        return None, ["OUTCOME_EVENT_INVALID"], False
    subject = _text(raw.get("subject_ref") or raw.get("subject"))
    event = _text(raw.get("event") or raw.get("event_type"))
    occurred_at = _text(raw.get("occurred_at") or raw.get("occurred"))
    source_ref = _text(raw.get("source_ref") or raw.get("source"))
    window, complete_window = _window_from(raw.get("observation_window"))
    if window is None and (raw.get("window_start") or raw.get("window_end")):
        window, complete_window = _window_from({
            "start": raw.get("window_start"),
            "end": raw.get("window_end"),
        })
    if window is None and window_default:
        window = dict(window_default)
        complete_window = bool(window.get("start") and window.get("end"))
    computed_hash = _fingerprint(raw)
    provided_hash = _text(raw.get("event_hash"))
    source_family = _text(raw.get("source_family") or raw.get("source_product")).lower()
    run_id = _text(raw.get("run_id"))
    binding_ref = _text(raw.get("binding_ref") or raw.get("result_receipt_id"))
    binding_decision = _text(raw.get("binding_decision_id"))
    cross_product = source_family in {"growovo", "verovo"} or bool(run_id)
    if not binding_ref and not cross_product:
        binding_state = "not_cross_product"
    elif not binding_ref:
        binding_state = "unbound"
    elif binding_decision and binding_decision != decision_id:
        binding_state = "binding_mismatch"
    else:
        binding_state = "bound"

    problems: List[str] = []
    if not subject:
        problems.append("OUTCOME_SUBJECT_REQUIRED")
    if not event:
        problems.append("OUTCOME_EVENT_REQUIRED")
    if not occurred_at:
        problems.append("OUTCOME_TIME_REQUIRED")
    if not complete_window:
        problems.append("OUTCOME_WINDOW_REQUIRED")
    if not source_ref:
        problems.append("OUTCOME_SOURCE_REQUIRED")
    if provided_hash and provided_hash != computed_hash:
        problems.append("EVENT_HASH_MISMATCH")
    if binding_state == "unbound":
        problems.append("CROSS_PRODUCT_UNBOUND")
    if binding_state == "binding_mismatch":
        problems.append("BINDING_MISMATCH")

    normalized = {
        "event_index": index,
        "event_id": "EV-%s" % computed_hash.split(":", 1)[-1][:12],
        "subject_ref": subject,
        "event": event,
        "occurred_at": occurred_at,
        "observation_window": window,
        "source_ref": source_ref,
        "source_family": source_family,
        "run_id": run_id,
        "binding_ref": binding_ref,
        "binding_decision_id": binding_decision,
        "binding_state": binding_state,
        "event_hash": computed_hash,
        "attribution": _text(raw.get("attribution")),
        "note": _text(raw.get("note")),
    }
    return normalized, problems, not problems


def _normalize_events(
    raw_events: Any,
    *,
    decision_id: str,
    window_default: Optional[Dict[str, str]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    formal: List[Dict[str, Any]] = []
    gaps: List[Dict[str, Any]] = []
    unbound: List[Dict[str, Any]] = []
    for index, raw in enumerate(raw_events or []):
        normalized, problems, complete = _normalize_event(
            raw, index=index, decision_id=decision_id, window_default=window_default
        )
        if complete and normalized is not None:
            formal.append(normalized)
        else:
            gap = {
                "event_index": index,
                "event_id": (normalized or {}).get("event_id", ""),
                "event_hash": (normalized or {}).get("event_hash", ""),
                "problems": problems,
                "binding_state": (normalized or {}).get("binding_state", ""),
            }
            gaps.append(gap)
            if normalized is not None and normalized.get("binding_state") in {"unbound", "binding_mismatch"}:
                unbound.append(dict(normalized, problems=problems))
    return formal, gaps, unbound


def _dedupe_events(events: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set = set()
    result: List[Dict[str, Any]] = []
    for event in events:
        key = _text(event.get("event_hash"))
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(event)
    return result


def _dedupe_gaps(gaps: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set = set()
    result: List[Dict[str, Any]] = []
    for gap in gaps:
        key = (
            _text(gap.get("event_hash")),
            tuple(gap.get("problems") or []),
            _text(gap.get("binding_state")),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(gap)
    return result


# ---------------------------------------------------------------------------
# Append-only storage
# ---------------------------------------------------------------------------


def load_followups(study_dir: Path, *, decision_id: str = "") -> List[Dict[str, Any]]:
    path = followups_path(study_dir)
    records: List[Dict[str, Any]] = []
    if not path.is_file():
        return records
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue
        if _text(item.get("kind")) != SCHEMA and _text(item.get("schema")) != SCHEMA:
            continue
        if decision_id and _text(item.get("decision_id")) != _text(decision_id):
            continue
        records.append(item)
    return records


def latest_followup(records: Iterable[Dict[str, Any]], decision_id: str = "") -> Optional[Dict[str, Any]]:
    selected = [item for item in records if isinstance(item, dict)
                and (not decision_id or _text(item.get("decision_id")) == _text(decision_id))]
    return selected[-1] if selected else None


def _content_payload(
    *,
    decision_id: str,
    decision_snapshot_hash: str,
    choice_state: str,
    owner_ref: str,
    source_ref: str,
    note: str,
    delivery_state: str,
    delivery_refs: List[Dict[str, Any]],
    outcome_state: str,
    outcome_events: List[Dict[str, Any]],
    outcome_gaps: List[Dict[str, Any]],
    observation_window: Optional[Dict[str, str]],
    attribution: str,
    causality_state: str,
    reviewer: str,
    reviewed_at: str,
    notification_authorized: bool,
    notification_ref: str,
) -> Dict[str, Any]:
    return {
        "decision_id": decision_id,
        "decision_snapshot_hash": decision_snapshot_hash,
        "choice_state": choice_state,
        "owner_ref": owner_ref,
        "source_ref": source_ref,
        "note": note,
        "delivery_state": delivery_state,
        "delivery_refs": [{"ref": item.get("ref"), "kind": item.get("kind")} for item in delivery_refs],
        "outcome_state": outcome_state,
        "outcome_events": outcome_events,
        "outcome_gaps": outcome_gaps,
        "observation_window": observation_window,
        "attribution": attribution,
        "causality_state": causality_state,
        "reviewer": reviewer,
        "reviewed_at": reviewed_at,
        "notification": {"authorized": notification_authorized, "ref": notification_ref},
    }


def _notification(study_dir: Path, authorized: bool, ref: str, diagnostics: List[Dict[str, str]]) -> Dict[str, Any]:
    ref_text = _text(ref)
    if authorized and not ref_text:
        authorized = False
        diagnostics.append({
            "code": "NOTIFICATION_REF_REQUIRED",
            "axis": "notification",
            "detail": "notification authorization requires an explicit authorization reference; kept local",
        })
    return {
        "state": "authorized_local_only" if authorized else "local_todo_only",
        "authorized": bool(authorized),
        "authorization_ref": ref_text,
        "outbound": "none",
        "note": (
            "Authorization is recorded only. This module has no outbound channel; "
            "an authorized follow-up remains a local todo for a human operator."
        ),
    }


def _store(
    study_dir: Path,
    *,
    record: Dict[str, Any],
    choice_state: str,
    owner_ref: str,
    source_ref: str,
    note: str,
    delivery_state: str,
    delivery_refs: List[Dict[str, Any]],
    delivery_evidence_state: str,
    outcome_state: str,
    outcome_events: List[Dict[str, Any]],
    outcome_gaps: List[Dict[str, Any]],
    observation_window: Optional[Dict[str, str]],
    attribution: str,
    causality_state: str,
    reviewer: str,
    reviewed_at: str,
    notification: Dict[str, Any],
    diagnostics: List[Dict[str, str]],
    at: str,
) -> Dict[str, Any]:
    study_dir = Path(study_dir).resolve()
    decision_id = _text(record.get("record_id"))
    snapshot_hash = _text(record.get("chain_fingerprint"))
    _, reasoning, reasoning_path = _canonical(study_dir)
    chain = _find_chain(reasoning, _text(record.get("chain_id")))
    current_fp = _current_fingerprint(chain)
    snapshot_state = "matches" if chain is not None and current_fp == snapshot_hash else "stale"
    if snapshot_state == "stale":
        diagnostics.append({
            "code": "SNAPSHOT_HASH_MISMATCH",
            "axis": "snapshot",
            "detail": (
                "DecisionSnapshot %s recorded %s but the current chain fingerprint is %s; "
                "the follow-up is kept for review and must not be read as a clean match"
                % (decision_id, snapshot_hash or "(missing)", current_fp or "(chain missing)")
            ),
        })

    if _text(delivery_state) not in {"unknown"} and not delivery_refs:
        diagnostics.append({
            "code": "DELIVERY_REFERENCE_REQUIRED",
            "axis": "delivery",
            "detail": "delivery_state %r has no delivery reference; evidence stays insufficient" % delivery_state,
        })

    content = _content_payload(
        decision_id=decision_id,
        decision_snapshot_hash=snapshot_hash,
        choice_state=choice_state,
        owner_ref=owner_ref,
        source_ref=source_ref,
        note=note,
        delivery_state=delivery_state,
        delivery_refs=delivery_refs,
        outcome_state=outcome_state,
        outcome_events=outcome_events,
        outcome_gaps=outcome_gaps,
        observation_window=observation_window,
        attribution=attribution,
        causality_state=causality_state,
        reviewer=reviewer,
        reviewed_at=reviewed_at,
        notification_authorized=bool(notification.get("authorized")),
        notification_ref=_text(notification.get("authorization_ref")),
    )
    content_hash = _fingerprint(content)

    existing = load_followups(study_dir, decision_id=decision_id)
    for item in existing:
        if _text(item.get("content_hash")) == content_hash:
            return {
                "status": "unchanged",
                "followup_id": item.get("followup_id"),
                "record": item,
                "path": str(followups_path(study_dir)),
                "diagnostics": diagnostics,
                "canonical_write": False,
                "effects": EFFECTS,
                "reason": "an identical follow-up already exists; no line was appended",
            }

    sequence = len(existing) + 1
    followup_id = "FU-%s-%03d" % (decision_id, sequence)
    stored_at = at or _now()
    stored = {
        "kind": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "followup_id": followup_id,
        "content_hash": content_hash,
        "appended_at": stored_at,
        "decision_id": decision_id,
        "decision_snapshot_hash": snapshot_hash,
        "snapshot_state": snapshot_state,
        "chain_id": _text(record.get("chain_id")),
        "current_chain_fingerprint": current_fp,
        "choice_state": choice_state,
        "owner_ref": owner_ref,
        "source_ref": source_ref,
        "note": note,
        "delivery_state": delivery_state,
        "delivery_refs": delivery_refs,
        "delivery_evidence_state": delivery_evidence_state,
        "outcome_state": outcome_state,
        "outcome_events": outcome_events,
        "outcome_gaps": outcome_gaps,
        "observation_window": observation_window,
        "attribution": attribution,
        "causality_state": causality_state,
        "reviewer": reviewer,
        "reviewed_at": reviewed_at,
        "verification_effect": "none",
        "notification": notification,
        "diagnostics": diagnostics,
        "input_refs": {
            "study_dir": str(study_dir),
            "reasoning": str(reasoning_path),
            "followups": str(followups_path(study_dir)),
        },
        "generator": GENERATOR,
        "generator_version": GENERATOR_VERSION,
        "effects": EFFECTS,
        "boundary": BOUNDARY,
    }
    path = followups_path(study_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(stored, ensure_ascii=False, sort_keys=True) + "\n")
    return {
        "status": "recorded",
        "followup_id": followup_id,
        "record": stored,
        "path": str(path),
        "diagnostics": diagnostics,
        "canonical_write": False,
        "effects": EFFECTS,
    }


def append_followup(
    study_dir: Path,
    *,
    decision_id: str,
    choice_state: str,
    owner_ref: str,
    source_ref: str,
    delivery_state: str = "unknown",
    delivery_refs: Any = (),
    outcome_state: str = "unknown",
    outcome_events: Any = (),
    observation_window: Any = None,
    attribution: str = "",
    causality_state: str = "not_claimed",
    reviewer: str = "",
    reviewed_at: str = "",
    note: str = "",
    notification_authorized: bool = False,
    notification_ref: str = "",
    at: str = "",
) -> Dict[str, Any]:
    """Append one follow-up. Identical content is a no-op; old lines never change."""
    study_dir = Path(study_dir).resolve()
    _, reasoning, _ = _canonical(study_dir)
    record = _find_record(reasoning, decision_id)
    owner = _text(owner_ref)
    source = _text(source_ref)
    if not owner:
        raise ValueError("follow-up requires --owner naming the person accountable for the follow-up")
    if not source:
        raise ValueError("follow-up requires --source pointing at the receipt/source of the follow-up")
    choice = _normalize_choice(choice_state)
    reason = _text(note)
    if choice in {"rejected", "deferred"} and not reason:
        raise ValueError("rejected/deferred follow-ups require --note recording the reason")

    diagnostics: List[Dict[str, str]] = []
    delivery, delivery_diags = _normalize_delivery(delivery_state)
    diagnostics.extend(delivery_diags)
    stored_at = at or _now()
    refs, evidence_state, ref_diags = _normalize_delivery_refs(study_dir, delivery_refs, stored_at)
    diagnostics.extend(ref_diags)

    outcome, outcome_diags = _normalize_outcome_state(outcome_state)
    diagnostics.extend(outcome_diags)
    window, window_complete = _window_from(observation_window)
    if observation_window and not window_complete:
        diagnostics.append({
            "code": "OBSERVATION_WINDOW_INCOMPLETE",
            "axis": "outcome",
            "detail": "observation_window needs both start and end; kept as given but not treated as complete",
        })
    formal_events, gaps, unbound = _normalize_events(
        outcome_events, decision_id=_text(record.get("record_id")), window_default=window
    )
    if outcome == "observed" and not formal_events:
        outcome = "unknown"
        diagnostics.append({
            "code": "OUTCOME_WITHOUT_EVENTS",
            "axis": "outcome",
            "detail": "outcome_state=observed requires at least one complete event; recorded as unknown",
        })
    for gap in gaps:
        for problem in gap.get("problems") or []:
            diagnostics.append({
                "code": problem,
                "axis": "outcome",
                "detail": "outcome event #%d was not admitted: %s" % (gap.get("event_index", 0), problem),
            })

    causality, causality_diags = _normalize_causality(causality_state)
    diagnostics.extend(causality_diags)
    reviewer_text = _text(reviewer)
    reviewed_text = _text(reviewed_at)
    if bool(reviewer_text) != bool(reviewed_text):
        diagnostics.append({
            "code": "REVIEW_INCOMPLETE",
            "axis": "review",
            "detail": "reviewer and reviewed_at must be supplied together; the review is not treated as complete",
        })

    notification = _notification(study_dir, bool(notification_authorized), notification_ref, diagnostics)

    return _store(
        study_dir,
        record=record,
        choice_state=choice,
        owner_ref=owner,
        source_ref=source,
        note=reason,
        delivery_state=delivery,
        delivery_refs=refs,
        delivery_evidence_state=evidence_state,
        outcome_state=outcome,
        outcome_events=formal_events,
        outcome_gaps=gaps,
        observation_window=window,
        attribution=_text(attribution),
        causality_state=causality,
        reviewer=reviewer_text,
        reviewed_at=reviewed_text,
        notification=notification,
        diagnostics=diagnostics,
        at=stored_at,
    )


def import_outcome_events(
    study_dir: Path,
    *,
    decision_id: str,
    events: Any,
    at: str = "",
) -> Dict[str, Any]:
    """Import outcome events as a new follow-up line without touching prior lines."""
    study_dir = Path(study_dir).resolve()
    _, reasoning, _ = _canonical(study_dir)
    record = _find_record(reasoning, decision_id)
    existing = load_followups(study_dir, decision_id=_text(record.get("record_id")))
    latest = latest_followup(existing)
    if latest is None:
        raise ValueError(
            "no follow-up exists for %s; append the accepted/rejected/deferred follow-up first"
            % _text(record.get("record_id"))
        )
    stored_at = at or _now()
    previous_events = [item for item in latest.get("outcome_events") or [] if isinstance(item, dict)]
    previous_gaps = [item for item in latest.get("outcome_gaps") or [] if isinstance(item, dict)]
    window = latest.get("observation_window") if isinstance(latest.get("observation_window"), dict) else None
    formal_events, gaps, unbound = _normalize_events(
        events, decision_id=_text(record.get("record_id")), window_default=window
    )
    known_hashes = {_text(item.get("event_hash")) for item in previous_events}
    duplicates = len([item for item in formal_events if _text(item.get("event_hash")) in known_hashes])
    merged_events = _dedupe_events(previous_events + formal_events)
    merged_gaps = _dedupe_gaps(previous_gaps + gaps)
    outcome_state = "observed" if merged_events else _text(latest.get("outcome_state")) or "unknown"

    diagnostics: List[Dict[str, str]] = []
    for gap in gaps:
        for problem in gap.get("problems") or []:
            diagnostics.append({
                "code": problem,
                "axis": "outcome",
                "detail": "imported outcome event #%d was not admitted: %s" % (gap.get("event_index", 0), problem),
            })
    if duplicates:
        diagnostics.append({
            "code": "OUTCOME_EVENT_DUPLICATE",
            "axis": "outcome",
            "detail": "%d imported event(s) already existed and were not counted twice" % duplicates,
        })

    result = _store(
        study_dir,
        record=record,
        choice_state=_text(latest.get("choice_state")),
        owner_ref=_text(latest.get("owner_ref")),
        source_ref=_text(latest.get("source_ref")),
        note=_text(latest.get("note")),
        delivery_state=_text(latest.get("delivery_state")) or "unknown",
        delivery_refs=[item for item in latest.get("delivery_refs") or [] if isinstance(item, dict)],
        delivery_evidence_state=_text(latest.get("delivery_evidence_state")) or "NO_REFERENCE",
        outcome_state=outcome_state,
        outcome_events=merged_events,
        outcome_gaps=merged_gaps,
        observation_window=window,
        attribution=_text(latest.get("attribution")),
        causality_state=_text(latest.get("causality_state")) or "not_claimed",
        reviewer=_text(latest.get("reviewer")),
        reviewed_at=_text(latest.get("reviewed_at")),
        notification=latest.get("notification") if isinstance(latest.get("notification"), dict) else {
            "state": "local_todo_only", "authorized": False, "authorization_ref": "", "outbound": "none",
        },
        diagnostics=diagnostics,
        at=stored_at,
    )
    result["added_events"] = len([item for item in formal_events if _text(item.get("event_hash")) not in known_hashes])
    result["duplicate_events"] = duplicates
    result["unbound_events"] = unbound
    return result


# ---------------------------------------------------------------------------
# Read-only receipt projection
# ---------------------------------------------------------------------------


def _snapshot_projection(record: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "record_id": record.get("record_id"),
        "chain_id": record.get("chain_id"),
        "version": record.get("version"),
        "recorded_at": record.get("recorded_at"),
        "decision_maker": record.get("decision_maker"),
        "accountable_owner": record.get("accountable_owner"),
        "decision": record.get("decision"),
        "decision_state": record.get("decision_state"),
        "chain_fingerprint": record.get("chain_fingerprint"),
        "next_action": record.get("next_action"),
        "original_hypothesis": record.get("original_hypothesis") or [],
        "basis": record.get("basis") or {},
        "chain_snapshot": record.get("chain_snapshot") or {},
    }


def _receipt_fingerprint(study_dir: Path, reasoning_path: Path, records: List[Dict[str, Any]]) -> str:
    path = followups_path(study_dir)
    parts: List[str] = []
    try:
        parts.append(Path(reasoning_path).read_text(encoding="utf-8"))
    except OSError:
        parts.append("")
    try:
        parts.append(path.read_text(encoding="utf-8") if path.is_file() else "")
    except OSError:
        parts.append("")
    return _fingerprint({"reasoning": parts[0], "followups": parts[1], "count": len(records)})


def build_receipt(study_dir: Path, decision_id: str, *, at: str = "") -> Dict[str, Any]:
    """Build a deterministic read-only receipt; nothing is written."""
    study_dir = Path(study_dir).resolve()
    study, reasoning, reasoning_path = _canonical(study_dir)
    record = _find_record(reasoning, decision_id)
    chain = _find_chain(reasoning, _text(record.get("chain_id")))
    current_fp = _current_fingerprint(chain)
    snapshot_hash = _text(record.get("chain_fingerprint"))
    snapshot_state = "matches" if chain is not None and current_fp == snapshot_hash else "stale"
    records = load_followups(study_dir, decision_id=_text(record.get("record_id")))
    latest = latest_followup(records)

    diagnostics: List[Dict[str, str]] = []
    if snapshot_state == "stale":
        diagnostics.append({
            "code": "SNAPSHOT_HASH_MISMATCH",
            "axis": "snapshot",
            "detail": "recorded snapshot %s differs from current chain fingerprint %s"
                      % (snapshot_hash or "(missing)", current_fp or "(chain missing)"),
        })
    if latest is None:
        diagnostics.append({
            "code": "FOLLOWUP_NOT_RECORDED",
            "axis": "choice",
            "detail": "no follow-up has been appended for this DecisionRecord",
        })

    refs: List[Dict[str, Any]] = []
    for item in (latest or {}).get("delivery_refs") or []:
        if not isinstance(item, dict):
            continue
        checked = _check_ref(study_dir, item.get("ref"), _text(item.get("kind")))
        checked["checked_at"] = item.get("checked_at")
        refs.append(checked)
        if checked["state"] == "BROKEN_REFERENCE":
            diagnostics.append({
                "code": "BROKEN_REFERENCE",
                "axis": "delivery",
                "detail": "delivery reference %r is missing; delivery evidence is insufficient" % checked["ref"],
            })

    delivery_state = _text((latest or {}).get("delivery_state")) or "unknown"
    if refs and any(item["state"] == "BROKEN_REFERENCE" for item in refs):
        delivery_evidence_state = "BROKEN_REFERENCE"
    elif refs and any(item["state"] == "EXTERNAL_UNVERIFIED" for item in refs):
        delivery_evidence_state = "UNVERIFIED"
    elif refs:
        delivery_evidence_state = "OK"
    else:
        delivery_evidence_state = "NO_REFERENCE"

    outcome_events = list((latest or {}).get("outcome_events") or [])
    outcome_gaps = list((latest or {}).get("outcome_gaps") or [])
    unbound = [item for item in outcome_events if _text(item.get("binding_state")) in {"unbound", "binding_mismatch"}]
    unbound.extend([
        gap for gap in outcome_gaps
        if _text(gap.get("binding_state")) in {"unbound", "binding_mismatch"}
    ])

    timeline = [{
        "followup_id": item.get("followup_id"),
        "appended_at": item.get("appended_at"),
        "choice_state": item.get("choice_state"),
        "owner_ref": item.get("owner_ref"),
        "source_ref": item.get("source_ref"),
        "note": item.get("note"),
        "delivery_state": item.get("delivery_state"),
        "outcome_state": item.get("outcome_state"),
        "causality_state": item.get("causality_state"),
        "reviewer": item.get("reviewer"),
        "reviewed_at": item.get("reviewed_at"),
        "snapshot_state": item.get("snapshot_state"),
    } for item in records]

    receipt = {
        "kind": RECEIPT_KIND,
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "study_id": study.get("study_id"),
        "decision_id": _text(record.get("record_id")),
        "chain_id": _text(record.get("chain_id")),
        "decision_snapshot": _snapshot_projection(record),
        "decision_snapshot_hash": snapshot_hash,
        "snapshot_state": snapshot_state,
        "current_chain_fingerprint": current_fp,
        "generated_at": at or _now(),
        "generator": GENERATOR,
        "generator_version": GENERATOR_VERSION,
        "input_refs": {
            "study_dir": str(study_dir),
            "reasoning": str(reasoning_path),
            "followups": str(followups_path(study_dir)),
        },
        "input_fingerprint": _receipt_fingerprint(study_dir, reasoning_path, records),
        "followup_count": len(records),
        "latest_followup_id": (latest or {}).get("followup_id"),
        "states": {
            "choice": _text((latest or {}).get("choice_state")) or "not_recorded",
            "delivery": delivery_state,
            "outcome": _text((latest or {}).get("outcome_state")) or "unknown",
            "causality": _text((latest or {}).get("causality_state")) or "not_claimed",
        },
        "choice": {
            "state": _text((latest or {}).get("choice_state")) or "not_recorded",
            "owner_ref": (latest or {}).get("owner_ref"),
            "source_ref": (latest or {}).get("source_ref"),
            "reason": (latest or {}).get("note"),
            "appended_at": (latest or {}).get("appended_at"),
            "followup_id": (latest or {}).get("followup_id"),
        },
        "delivery": {
            "state": delivery_state,
            "refs": refs,
            "evidence_state": delivery_evidence_state,
            "appended_at": (latest or {}).get("appended_at"),
            "followup_id": (latest or {}).get("followup_id"),
        },
        "outcome": {
            "state": _text((latest or {}).get("outcome_state")) or "unknown",
            "events": outcome_events,
            "gaps": outcome_gaps,
            "unbound": unbound,
            "observation_window": (latest or {}).get("observation_window"),
            "attribution": (latest or {}).get("attribution"),
            "appended_at": (latest or {}).get("appended_at"),
            "followup_id": (latest or {}).get("followup_id"),
        },
        "causality": {
            "state": _text((latest or {}).get("causality_state")) or "not_claimed",
            "note": "Causality is a separate claim; temporal order and delivered artifacts never establish it.",
        },
        "reviewer": (latest or {}).get("reviewer"),
        "reviewed_at": (latest or {}).get("reviewed_at"),
        "notification": (latest or {}).get("notification") or {
            "state": "local_todo_only",
            "authorized": False,
            "authorization_ref": "",
            "outbound": "none",
        },
        "verification_effect": "none",
        "canonical_write": False,
        "effects": EFFECTS,
        "timeline": timeline,
        "diagnostics": diagnostics,
        "boundary": BOUNDARY,
    }
    return receipt


def render_receipt_md(receipt: Dict[str, Any]) -> str:
    snapshot = receipt.get("decision_snapshot") or {}
    states = receipt.get("states") or {}
    lines: List[str] = []
    lines.append("# 决策回执：%s" % receipt.get("decision_id"))
    lines.append("")
    lines.append("- 研究：`%s`" % (receipt.get("study_id") or ""))
    lines.append("- 链条：`%s`" % (receipt.get("chain_id") or ""))
    lines.append("- 快照状态：`%s`" % receipt.get("snapshot_state"))
    lines.append("- 输入指纹：`%s`" % receipt.get("input_fingerprint"))
    lines.append("- 生成器：`%s@%s`" % (receipt.get("generator"), receipt.get("generator_version")))
    lines.append("")
    lines.append("## 原决定快照")
    lines.append("")
    lines.append("| 字段 | 值 |")
    lines.append("| --- | --- |")
    for label, key in (
        ("决定人", "decision_maker"),
        ("责任 owner", "accountable_owner"),
        ("决定", "decision"),
        ("记录时间", "recorded_at"),
        ("快照指纹", "chain_fingerprint"),
        ("下一步", "next_action"),
    ):
        value = snapshot.get(key)
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        lines.append("| %s | %s |" % (label, _md_cell(value)))
    lines.append("")
    lines.append("## 四轴当前状态")
    lines.append("")
    lines.append("| 轴 | 状态 |")
    lines.append("| --- | --- |")
    lines.append("| 选择 | `%s` |" % states.get("choice"))
    lines.append("| 交付 | `%s` |" % states.get("delivery"))
    lines.append("| 结果 | `%s` |" % states.get("outcome"))
    lines.append("| 因果 | `%s` |" % states.get("causality"))
    lines.append("")

    choice = receipt.get("choice") or {}
    lines.append("## 选择")
    lines.append("")
    lines.append("- 状态：`%s`" % choice.get("state"))
    lines.append("- 责任人：`%s`" % (choice.get("owner_ref") or ""))
    lines.append("- 来源：`%s`" % (choice.get("source_ref") or ""))
    lines.append("- 理由：%s" % (choice.get("reason") or "（未填写）"))
    lines.append("")

    delivery = receipt.get("delivery") or {}
    lines.append("## 交付")
    lines.append("")
    lines.append("- 状态：`%s`" % delivery.get("state"))
    lines.append("- 证据状态：`%s`" % delivery.get("evidence_state"))
    if delivery.get("refs"):
        for item in delivery.get("refs") or []:
            lines.append("- `%s`（%s，exists=%s）" % (item.get("ref"), item.get("kind"), item.get("exists")))
    else:
        lines.append("- 未登记交付物引用")
    lines.append("")

    outcome = receipt.get("outcome") or {}
    lines.append("## 结果事件")
    lines.append("")
    lines.append("- 状态：`%s`" % outcome.get("state"))
    lines.append("- 观察窗口：%s" % _md_cell(outcome.get("observation_window")))
    lines.append("- 归因方式：%s" % (outcome.get("attribution") or "（未填写）"))
    if outcome.get("events"):
        lines.append("")
        lines.append("| 事件 | 主体 | 发生时间 | 来源 | 哈希 |")
        lines.append("| --- | --- | --- | --- | --- |")
        for event in outcome.get("events") or []:
            lines.append("| %s | %s | %s | %s | `%s` |" % (
                _md_cell(event.get("event")), _md_cell(event.get("subject_ref")),
                _md_cell(event.get("occurred_at")), _md_cell(event.get("source_ref")),
                (event.get("event_hash") or "")[:24],
            ))
    if outcome.get("gaps"):
        lines.append("")
        lines.append("缺口：")
        for gap in outcome.get("gaps") or []:
            lines.append("- 事件 #%s：%s" % (gap.get("event_index"), "、".join(gap.get("problems") or [])))
    lines.append("")

    lines.append("## 因果边界")
    lines.append("")
    lines.append("- 状态：`%s`" % (receipt.get("causality") or {}).get("state"))
    lines.append("- %s" % (receipt.get("causality") or {}).get("note"))
    lines.append("")

    lines.append("## 历史时间线")
    lines.append("")
    if receipt.get("timeline"):
        lines.append("| 追加时间 | 回执 | 选择 | 交付 | 结果 | 因果 | 责任人 | 备注 |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for item in receipt.get("timeline") or []:
            lines.append("| %s | `%s` | `%s` | `%s` | `%s` | `%s` | %s | %s |" % (
                _md_cell(item.get("appended_at")), item.get("followup_id"),
                item.get("choice_state"), item.get("delivery_state"),
                item.get("outcome_state"), item.get("causality_state"),
                _md_cell(item.get("owner_ref")), _md_cell(item.get("note")),
            ))
    else:
        lines.append("尚未追加 follow-up。")
    lines.append("")

    notification = receipt.get("notification") or {}
    lines.append("## 通知")
    lines.append("")
    lines.append("- 状态：`%s`，授权：`%s`，外发：`%s`" % (
        notification.get("state"), notification.get("authorized"), notification.get("outbound")))
    lines.append("")

    if receipt.get("diagnostics"):
        lines.append("## 诊断")
        lines.append("")
        for item in receipt.get("diagnostics") or []:
            lines.append("- `%s`（%s）：%s" % (item.get("code"), item.get("axis"), item.get("detail")))
        lines.append("")

    lines.append("## 边界")
    lines.append("")
    lines.append(receipt.get("boundary") or BOUNDARY)
    lines.append("")
    lines.append("验证效果：`%s`；canonical 写入：`%s`。" % (
        receipt.get("verification_effect"), receipt.get("canonical_write")))
    lines.append("")
    return "\n".join(lines)


def _md_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    else:
        text = str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def render_receipt_html(receipt: Dict[str, Any]) -> str:
    e = html.escape
    snapshot = receipt.get("decision_snapshot") or {}
    states = receipt.get("states") or {}
    choice = receipt.get("choice") or {}
    delivery = receipt.get("delivery") or {}
    outcome = receipt.get("outcome") or {}
    notification = receipt.get("notification") or {}

    def kv_table(rows: List[Tuple[str, Any]]) -> str:
        body = []
        for label, value in rows:
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False, sort_keys=True)
            body.append("<tr><th>%s</th><td>%s</td></tr>" % (e(label), e(str(value if value is not None else ""))))
        return "<table>%s</table>" % "".join(body)

    timeline_rows = []
    for item in receipt.get("timeline") or []:
        timeline_rows.append(
            "<tr><td>%s</td><td><code>%s</code></td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                e(str(item.get("appended_at") or "")), e(str(item.get("followup_id") or "")),
                e(str(item.get("choice_state") or "")), e(str(item.get("delivery_state") or "")),
                e(str(item.get("outcome_state") or "")), e(str(item.get("causality_state") or "")),
                e(str(item.get("owner_ref") or "")), e(str(item.get("note") or "")),
            )
        )
    timeline = (
        "<table><thead><tr><th>追加时间</th><th>回执</th><th>选择</th><th>交付</th><th>结果</th>"
        "<th>因果</th><th>责任人</th><th>备注</th></tr></thead><tbody>%s</tbody></table>" % "".join(timeline_rows)
        if timeline_rows else "<p class=\"muted\">尚未追加 follow-up。</p>"
    )

    event_rows = []
    for event in outcome.get("events") or []:
        event_rows.append(
            "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td><code>%s</code></td></tr>" % (
                e(str(event.get("event") or "")), e(str(event.get("subject_ref") or "")),
                e(str(event.get("occurred_at") or "")), e(str(event.get("source_ref") or "")),
                e(str(event.get("event_hash") or "")[:24]),
            )
        )
    events = (
        "<table><thead><tr><th>事件</th><th>主体</th><th>发生时间</th><th>来源</th><th>哈希</th></tr></thead>"
        "<tbody>%s</tbody></table>" % "".join(event_rows)
        if event_rows else "<p class=\"muted\">没有进入正式 outcome 的事件。</p>"
    )

    gap_items = "".join(
        "<li>事件 #%s：%s</li>" % (e(str(gap.get("event_index"))), e("、".join(gap.get("problems") or [])))
        for gap in outcome.get("gaps") or []
    )

    ref_items = "".join(
        "<li><code>%s</code>（%s，exists=%s）</li>" % (
            e(str(item.get("ref") or "")), e(str(item.get("kind") or "")), e(str(item.get("exists"))))
        for item in delivery.get("refs") or []
    ) or "<li>未登记交付物引用</li>"

    diagnostics = "".join(
        "<li><code>%s</code>（%s）：%s</li>" % (e(str(item.get("code"))), e(str(item.get("axis"))), e(str(item.get("detail"))))
        for item in receipt.get("diagnostics") or []
    ) or "<li class=\"muted\">无诊断项</li>"

    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>决策回执 %s</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:0;background:#f6f7f9;color:#1f2328;line-height:1.55}
main{max-width:1080px;margin:0 auto;padding:32px 20px 60px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:18px;margin:28px 0 10px}
.muted{color:#6b7280}.card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:18px 20px;margin:14px 0}
table{border-collapse:collapse;width:100%%;margin:10px 0;background:#fff}
th,td{border:1px solid #e5e7eb;padding:7px 9px;text-align:left;font-size:13px;vertical-align:top}
th{background:#f3f4f6;font-weight:600}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}
.axis{display:inline-block;padding:3px 9px;border-radius:999px;background:#eef2ff;margin-right:6px;font-size:13px}
.boundary{border-left:4px solid #d1d5db;padding:10px 14px;color:#4b5563;background:#fafafa}
</style>
</head>
<body>
<main id="follow-up">
<h1>决策回执：%s</h1>
<p class="muted">研究 <code>%s</code> · 链条 <code>%s</code> · 快照状态 <code>%s</code></p>
<div class="card">
<span class="axis">选择：%s</span><span class="axis">交付：%s</span><span class="axis">结果：%s</span><span class="axis">因果：%s</span>
</div>
<h2>原决定快照</h2>
<div class="card">%s</div>
<h2>选择</h2>
<div class="card">
<p>责任人：<code>%s</code> · 来源：<code>%s</code></p>
<p>理由：%s</p>
</div>
<h2>交付</h2>
<div class="card">
<p>状态：<code>%s</code> · 证据状态：<code>%s</code></p>
<ul>%s</ul>
</div>
<h2>结果事件</h2>
<div class="card">
<p>状态：<code>%s</code> · 观察窗口：%s · 归因：%s</p>
%s
%s
</div>
<h2>因果边界</h2>
<div class="card"><p>状态：<code>%s</code></p><p>%s</p></div>
<h2>历史时间线</h2>
%s
<h2>通知</h2>
<div class="card"><p>状态：<code>%s</code> · 授权：<code>%s</code> · 外发：<code>%s</code></p></div>
<h2>诊断</h2>
<div class="card"><ul>%s</ul></div>
<h2>边界</h2>
<div class="card boundary"><p>%s</p>
<p class="muted">验证效果：<code>%s</code> · canonical 写入：<code>%s</code> · 生成器：<code>%s@%s</code> · 输入指纹：<code>%s</code></p></div>
</main>
</body>
</html>
""" % (
        e(str(receipt.get("decision_id") or "")),
        e(str(receipt.get("decision_id") or "")),
        e(str(receipt.get("study_id") or "")),
        e(str(receipt.get("chain_id") or "")),
        e(str(receipt.get("snapshot_state") or "")),
        e(str(states.get("choice"))), e(str(states.get("delivery"))),
        e(str(states.get("outcome"))), e(str(states.get("causality"))),
        kv_table([
            ("决定人", snapshot.get("decision_maker")),
            ("责任 owner", snapshot.get("accountable_owner")),
            ("决定", snapshot.get("decision")),
            ("记录时间", snapshot.get("recorded_at")),
            ("快照指纹", snapshot.get("chain_fingerprint")),
            ("下一步", snapshot.get("next_action")),
        ]),
        e(str(choice.get("owner_ref") or "")),
        e(str(choice.get("source_ref") or "")),
        e(str(choice.get("reason") or "（未填写）")),
        e(str(delivery.get("state") or "")),
        e(str(delivery.get("evidence_state") or "")),
        ref_items,
        e(str(outcome.get("state") or "")),
        e(json.dumps(outcome.get("observation_window"), ensure_ascii=False) if outcome.get("observation_window") else ""),
        e(str(outcome.get("attribution") or "（未填写）")),
        events,
        ("<ul>%s</ul>" % gap_items) if gap_items else "",
        e(str((receipt.get("causality") or {}).get("state") or "")),
        e(str((receipt.get("causality") or {}).get("note") or "")),
        timeline,
        e(str(notification.get("state") or "")),
        e(str(notification.get("authorized"))),
        e(str(notification.get("outbound") or "")),
        diagnostics,
        e(str(receipt.get("boundary") or BOUNDARY)),
        e(str(receipt.get("verification_effect"))),
        e(str(receipt.get("canonical_write"))),
        e(str(receipt.get("generator"))),
        e(str(receipt.get("generator_version"))),
        e(str(receipt.get("input_fingerprint"))),
    )


def write_receipt(
    study_dir: Path,
    decision_id: str,
    *,
    out_dir: Any = None,
    at: str = "",
) -> Dict[str, Any]:
    receipt = build_receipt(study_dir, decision_id, at=at)
    study_dir = Path(study_dir).resolve()
    base = Path(out_dir) if out_dir else study_dir / REPORT_SUBDIR / _text(decision_id)
    base.mkdir(parents=True, exist_ok=True)
    files = {
        "json": base / "receipt.json",
        "markdown": base / "receipt.md",
        "html": base / "receipt.html",
    }
    files["json"].write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8")
    files["markdown"].write_text(render_receipt_md(receipt), encoding="utf-8")
    files["html"].write_text(render_receipt_html(receipt), encoding="utf-8")
    return {
        "status": "written",
        "decision_id": receipt["decision_id"],
        "files": {key: str(value) for key, value in files.items()},
        "input_fingerprint": receipt["input_fingerprint"],
        "canonical_write": False,
        "effects": EFFECTS,
    }


def list_followups(study_dir: Path, *, decision_id: str = "") -> Dict[str, Any]:
    records = load_followups(study_dir, decision_id=decision_id)
    return {
        "kind": "askovo.decision-followup-list",
        "schema_version": SCHEMA_VERSION,
        "count": len(records),
        "followups": [{
            "followup_id": item.get("followup_id"),
            "appended_at": item.get("appended_at"),
            "decision_id": item.get("decision_id"),
            "choice_state": item.get("choice_state"),
            "delivery_state": item.get("delivery_state"),
            "outcome_state": item.get("outcome_state"),
            "causality_state": item.get("causality_state"),
            "owner_ref": item.get("owner_ref"),
            "snapshot_state": item.get("snapshot_state"),
            "note": item.get("note"),
        } for item in records],
        "path": str(followups_path(study_dir)),
        "boundary": BOUNDARY,
    }
