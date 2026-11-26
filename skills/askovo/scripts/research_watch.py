"""Persistent, explicitly ticked research reviews over an existing study.

A watch schedules local decision reviews and optional authorized local issue-delta
syncs. When a separately authorized research-run plan exists, serve executes that
bounded plan before review. It never promotes evidence or rewrites judgments.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import decision_review
import notification_outbox
import research_delta
import write_integrity
from study_context import StudyRepository

SCHEMA = "askovo.research-watch/1"
STATE_RELATIVE = Path("04-findings/research-watch.json")
HISTORY_RELATIVE = Path("04-findings/research-watch-runs.jsonl")
LOCAL_ONLY = "local_review_only"


def _instant(value: Optional[str] = None) -> datetime:
    text = str(value or "").strip()
    if not text:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("now must be an ISO-8601 timestamp") from exc
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _state_path(study_dir: Path) -> Path:
    return Path(study_dir).resolve() / STATE_RELATIVE


def _history_path(study_dir: Path) -> Path:
    return Path(study_dir).resolve() / HISTORY_RELATIVE


def _study_id(study_dir: Path) -> str:
    study = write_integrity.read_json(
        Path(study_dir).resolve() / "study.json", expected=dict, label="study contract")
    return str(study.get("study_id") or "")


def _load_state(study_dir: Path) -> Dict[str, Any]:
    state = write_integrity.read_json(
        _state_path(study_dir), missing_ok=True, expected=dict, label="research watch state")
    if state is None:
        return {"schema": SCHEMA, "study_id": _study_id(study_dir), "watches": []}
    if state.get("schema") != SCHEMA or not isinstance(state.get("watches"), list):
        raise ValueError("research watch state has an unsupported schema")
    return state


def _dump_state(state: Dict[str, Any]) -> str:
    return json.dumps(state, ensure_ascii=False, indent=2) + "\n"


def _find(state: Dict[str, Any], watch_id: str) -> Dict[str, Any]:
    for watch in state["watches"]:
        if str(watch.get("watch_id") or "") == str(watch_id):
            return watch
    raise ValueError("unknown research watch: %s" % watch_id)


def _source_fingerprint(study_dir: Path) -> str:
    manifest = StudyRepository(study_dir).version_manifest()
    excluded = {STATE_RELATIVE.as_posix(), HISTORY_RELATIVE.as_posix(),
                notification_outbox.OUTBOX_RELATIVE.as_posix(),
                write_integrity.JOURNAL_RELATIVE.as_posix(), write_integrity.LOCK_RELATIVE.as_posix()}
    projected = {key: value for key, value in manifest.items() if key not in excluded}
    canonical = json.dumps(projected, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def create(study_dir: Path, *, question: str, interval_hours: float,
           owner: str, now: Optional[str] = None, delta_file: str = "",
           delta_authorized_by: str = "") -> Dict[str, Any]:
    study_dir = Path(study_dir).resolve()
    question = str(question or "").strip()
    owner = str(owner or "").strip()
    if not question or not owner:
        raise ValueError("research watch requires a question and named owner")
    if isinstance(interval_hours, bool) or not isinstance(interval_hours, (int, float)):
        raise ValueError("interval_hours must be a finite positive number")
    if not math.isfinite(interval_hours) or interval_hours <= 0:
        raise ValueError("interval_hours must be a finite positive number")
    delta_file = str(delta_file or "").strip()
    delta_authorized_by = str(delta_authorized_by or "").strip()
    if bool(delta_file) != bool(delta_authorized_by):
        raise ValueError("delta_file and delta_authorized_by must be provided together")
    delta = None
    if delta_file:
        source = Path(delta_file).resolve()
        if not source.is_file():
            raise ValueError("authorized delta export not found: %s" % source)
        delta = {"file": str(source), "authorized_by": delta_authorized_by}
    stamp = _iso(_instant(now))
    with StudyRepository(study_dir).transaction("research-watch-create") as txn:
        state = _load_state(study_dir)
        if any(str(row.get("question") or "").strip().casefold() == question.casefold()
               and row.get("state") != "closed" for row in state["watches"]):
            raise ValueError("an equivalent research watch already exists")
        numbers = [int(str(row.get("watch_id") or "")[1:]) for row in state["watches"]
                   if str(row.get("watch_id") or "").startswith("W")
                   and str(row.get("watch_id") or "")[1:].isdigit()]
        watch = {
            "watch_id": "W%03d" % (max(numbers, default=0) + 1),
            "question": question,
            "owner": owner,
            "state": "active",
            "interval_hours": interval_hours,
            "created_at": stamp,
            "next_due_at": stamp,
            "last_run_at": "",
            "last_review_status": "",
            "last_source_sha256": "",
            "run_count": 0,
            "execution": LOCAL_ONLY,
            "new_evidence_collected": False,
            "background_worker": False,
            "delta": delta,
        }
        state["watches"].append(watch)
        txn.add(STATE_RELATIVE, _dump_state(state))
        txn.commit()
    return {"schema": SCHEMA, "status": "created", "watch": watch,
            "boundary": "External cron/host tick required; no network collection, canonical evidence promotion or decision mutation."}


def status(study_dir: Path, *, now: Optional[str] = None,
           due_only: bool = False) -> Dict[str, Any]:
    study_dir = Path(study_dir).resolve()
    instant = _instant(now)
    state = _load_state(study_dir)
    watches = []
    for stored in state["watches"]:
        watch = dict(stored)
        due = watch.get("state") == "active" and _instant(watch.get("next_due_at")) <= instant
        watch["due"] = due
        if not due_only or due:
            watches.append(watch)
    return {
        "schema": SCHEMA,
        "study_id": state.get("study_id", ""),
        "status": "ok",
        "checked_at": _iso(instant),
        "watch_count": len(watches),
        "due_count": sum(1 for watch in watches if watch["due"]),
        "watches": watches,
        "scheduler": "external_tick_or_watch_serve",
        "execution": LOCAL_ONLY,
        "new_evidence_collected": False,
    }


def set_paused(study_dir: Path, watch_id: str, paused: bool,
               *, now: Optional[str] = None) -> Dict[str, Any]:
    study_dir = Path(study_dir).resolve()
    stamp = _iso(_instant(now))
    with StudyRepository(study_dir).transaction("research-watch-pause") as txn:
        state = _load_state(study_dir)
        watch = _find(state, watch_id)
        watch["state"] = "paused" if paused else "active"
        if not paused:
            watch["next_due_at"] = stamp
        txn.add(STATE_RELATIVE, _dump_state(state))
        txn.commit()
    return {"schema": SCHEMA, "status": "paused" if paused else "resumed", "watch": watch}


def run_due(study_dir: Path, *, watch_id: str = "",
            now: Optional[str] = None) -> Dict[str, Any]:
    study_dir = Path(study_dir).resolve()
    instant = _instant(now)
    stamp = _iso(instant)
    with StudyRepository(study_dir).transaction("research-watch-run") as txn:
        state = _load_state(study_dir)
        if watch_id:
            _find(state, watch_id)
        selected = [watch for watch in state["watches"]
                    if watch.get("state") == "active"
                    and (not watch_id or watch.get("watch_id") == watch_id)
                    and _instant(watch.get("next_due_at")) <= instant]
        if not selected:
            return {"schema": SCHEMA, "status": "no_due_watches", "runs": [],
                    "checked_at": stamp, "scheduler": "external_tick_or_watch_serve"}
        history = write_integrity.read_jsonl(
            _history_path(study_dir), missing_ok=True, label="research watch history")
        runs: List[Dict[str, Any]] = []
        for watch in selected:
            source_before = _source_fingerprint(study_dir)
            previous = str(watch.get("last_source_sha256") or "")
            delta = watch.get("delta") if isinstance(watch.get("delta"), dict) else None
            record = {
                "schema": "askovo.research-watch-run/1",
                "run_id": "%s-R%04d" % (watch["watch_id"], int(watch.get("run_count", 0)) + 1),
                "watch_id": watch["watch_id"],
                "question": watch["question"],
                "owner": watch["owner"],
                "started_at": stamp,
                "completed_at": stamp,
                "status": "completed",
                "execution": "local_authorized_delta_and_review" if delta else LOCAL_ONLY,
                "new_evidence_collected": False,
                "new_source_snapshot_created": False,
                "canonical_evidence_promoted": False,
                "decision_mutated": False,
                "source_sha256_before": source_before,
                "source_sha256": source_before,
                "source_changed_since_last_run": False,
            }
            try:
                if delta:
                    try:
                        synced = research_delta.sync(
                            study_dir, delta["file"], authorized_by=delta["authorized_by"],
                            question=watch["question"])
                        record["delta"] = {
                            "status": "completed", "version": synced.get("version"),
                            "noop": bool(synced.get("noop")),
                            "has_changes": bool(synced.get("has_changes")),
                            "counts": synced.get("counts"),
                            "needs_re_review": bool(synced.get("needs_re_review")),
                            "decision_record_mutated": bool(synced.get("decision_record_mutated")),
                            "source_sha256": (synced.get("source") or {}).get("sha256"),
                        }
                        record["new_source_snapshot_created"] = bool(synced.get("has_changes"))
                    except Exception as exc:
                        record["status"] = "failed"
                        record["delta"] = {
                            "status": "failed",
                            "error": "%s: %s" % (type(exc).__name__, str(exc)[:500]),
                        }
                source_after = _source_fingerprint(study_dir)
                record["source_sha256"] = source_after
                record["source_changed_since_last_run"] = bool(previous and previous != source_after)
                review = decision_review.review(study_dir)
                record.update({
                    "review_status": review["status"],
                    "review_counts": review["counts"],
                    "review_json_path": review["json_path"],
                    "review_markdown_path": review["markdown_path"],
                })
            except Exception as exc:
                record.update({"status": "failed", "review_status": "not_completed",
                               "error": "%s: %s" % (type(exc).__name__, str(exc)[:500])})
            watch["run_count"] = int(watch.get("run_count", 0)) + 1
            watch["last_run_at"] = stamp
            watch["last_review_status"] = record["review_status"]
            watch["last_source_sha256"] = record["source_sha256"]
            watch["next_due_at"] = _iso(instant + timedelta(hours=float(watch["interval_hours"])))
            watch["needs_attention"] = record["status"] == "failed"
            history.append(record)
            runs.append(record)
        txn.add(STATE_RELATIVE, _dump_state(state))
        new_records = history[-len(runs):]
        payload = "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in new_records)
        txn.add(HISTORY_RELATIVE, payload, mode="append")
        event_payload = notification_outbox.events_for_txn(study_dir, runs)
        if event_payload:
            txn.add(notification_outbox.OUTBOX_RELATIVE, event_payload, mode="append")
        txn.commit()
    return {
        "schema": SCHEMA,
        "status": "completed" if all(run["status"] == "completed" for run in runs) else "failed",
        "checked_at": stamp,
        "runs": runs,
        "scheduler": "external_tick_or_watch_serve",
        "new_evidence_collected": False,
        "boundary": "A run syncs any configured authorized local export and reviews the study. Source snapshots are not canonical evidence or automatic product decisions.",
    }


def serve(study_dir: Path, *, watch_id: str = "", now: Optional[str] = None,
          once: bool = False, poll_seconds: float = 300.0, max_cycles: int = 0,
          clock=None, sleeper=None) -> Dict[str, Any]:
    """Run due watches from Askovo itself; no host agent is used for the scheduler."""
    import time
    if poll_seconds <= 0:
        raise ValueError("poll_seconds must be positive")
    if max_cycles < 0:
        raise ValueError("max_cycles must be non-negative")
    clock = clock or (lambda: _iso(_instant(None)))
    sleeper = sleeper or time.sleep
    cycles = 0
    started = time.monotonic()
    while True:
        cycles += 1
        instant = _iso(_instant(now)) if now else clock()
        import research_run
        if research_run.state_path(study_dir).is_file():
            result = execute_due(study_dir, watch_id=watch_id, now=instant)
        else:
            result = run_due(study_dir, watch_id=watch_id, now=instant)
        active = [row for row in status(study_dir, now=instant)["watches"]
                  if row.get("state") == "active"]
        finished = once or (max_cycles and cycles >= max_cycles) or not active
        if finished:
            return {
                "schema": SCHEMA, "status": "tick_finished" if active else "schedule_finished",
                "run_status": result["status"], "runs": result.get("runs") or [],
                "cycles": cycles, "pending_notifications": len(notification_outbox.pending(study_dir)),
                "operations": {
                    "host_agent": "not_used", "scheduler_token_usage": 0,
                    "other_token_usage": "not_measured",
                    "elapsed_sec": round(time.monotonic() - started, 3),
                },
                "new_source_records_collected": int(result.get("new_source_records_collected") or 0),
                "new_source_material_collected": bool(result.get("new_source_material_collected")),
                "new_evidence_collected": False,
            }
        sleeper(poll_seconds)


def execute_due(study_dir: Path, *, watch_id: str = "", now: Optional[str] = None,
                max_steps: int = 1) -> Dict[str, Any]:
    """Run an already-authorized bounded research plan before the local due review."""
    due = status(study_dir, now=now, due_only=True)
    selected = [watch for watch in due["watches"]
                if not watch_id or watch.get("watch_id") == watch_id]
    if not selected:
        return {"schema": SCHEMA, "status": "no_due_watches", "runs": [],
                "scheduler": "external_tick_or_watch_serve",
                "new_source_records_collected": 0, "new_source_material_collected": False,
                "new_evidence_collected": False}
    import research_run
    collected = research_run.run(study_dir, max_steps=max_steps)
    run_state = collected.get("state") or {}
    actions = run_state.get("actions") or []
    fallback_records = sum(int((row.get("result") or {}).get("records") or 0) for row in actions)
    records = int(collected["new_records"]) if collected.get("new_records") is not None else fallback_records
    collection = {"status": run_state.get("status"), "run_id": run_state.get("run_id"),
                  "records": records,
                  "completed_actions": sum(row.get("state") == "completed" for row in actions)}
    if run_state.get("status") == "blocked":
        return {"schema": SCHEMA, "status": "failed", "collection": collection,
                "review_status": "not_run", "runs": [],
                "scheduler": "external_tick_or_watch_serve",
                "new_source_records_collected": records, "new_source_material_collected": records > 0,
                "new_evidence_collected": False, "canonical_evidence_promoted": False}
    reviewed = run_due(study_dir, watch_id=watch_id, now=now)
    return {
        "schema": SCHEMA,
        "status": reviewed.get("status"),
        "execution": "authorized_research_run_and_local_review",
        "collection": collection,
        "review_status": reviewed.get("status"),
        "runs": reviewed.get("runs") or [],
        "scheduler": "external_tick_or_watch_serve",
        "new_source_records_collected": records,
        "new_source_material_collected": records > 0,
        "new_evidence_collected": False,
        "canonical_evidence_promoted": False,
        "boundary": "Collection reuses the separately authorized research-run contract. New source material is not canonical evidence or an automatic decision mutation.",
    }
